from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..schemas.strategy import ComposeStrategyRequest, ComposeStrategyResponse
from .ai_runtime import get_ai_identity, optimize_strategy_code
from .llm_adapter import LlmAdapterError, complete_text
from .storage import BUILD_DIR, GENERATED_STRATEGY_DIR, MODULE_DIR, new_id, read_json, write_json


def _model_to_dict(model: Any) -> dict:
    if model is None:
        return {}
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _load_module(version_id: str) -> dict:
    path = MODULE_DIR / f"{version_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"module version not found: {version_id}")
    return read_json(path)


def _safe_class_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", name)
    if not cleaned:
        cleaned = "AssembleStrategy"
    if not cleaned[0].isalpha():
        cleaned = f"S{cleaned}"
    return cleaned


def _strip_code_fence(code: str) -> str:
    cleaned = code.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_+-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    candidate = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        clipped = candidate[start : end + 1]
        try:
            parsed = json.loads(clipped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI output is not valid JSON: {exc}") from exc

    raise ValueError("AI output is not a JSON object")


def _build_system_prompt(persona_md: str) -> str:
    return (
        "You are a freqtrade strategy integrator.\n"
        "Your task is to produce one production-ready freqtrade strategy file.\n"
        "You may either integrate module snippets or optimize an existing full strategy.\n\n"
        "Persona (must follow):\n"
        f"{persona_md.strip()}\n\n"
        "Hard rules:\n"
        "1) Output exactly one JSON object. No markdown, no code fences.\n"
        "2) JSON keys must be: strategy_code, explain.\n"
        "3) strategy_code must be a complete Python file, not a snippet.\n"
        "4) strategy_code must include: imports, IStrategy class, timeframe/can_short, and complete strategy logic.\n"
        "5) Respect explicit numeric constraints from user requirement.\n"
        "6) Keep runtime compatibility with freqtrade strategy imports.\n"
        "7) strategy_code must pass Python ast.parse."
    )


def _build_user_prompt(
    payload: ComposeStrategyRequest,
    strategy_name: str,
    indicator_module: dict,
    position_module: dict,
    risk_module: dict,
    feedback: str | None = None,
) -> str:
    feedback_block = f"\nPrevious output issue (must fix):\n{feedback.strip()}\n" if feedback else ""
    optimize_block = ""
    has_modules = any(
        str(module.get("module_code", "")).strip() or str(module.get("requirement", "")).strip()
        for module in (indicator_module, position_module, risk_module)
    )
    if payload.base_strategy_code:
        optimize_block = (
            "\nOptimization mode:\n"
            "- Optimize the existing full strategy below based on the new requirement.\n"
            "- Keep class name unchanged.\n"
            f"- Base build id: {payload.base_build_id or 'unknown'}\n"
            "[existing_strategy_code]\n"
            f"{payload.base_strategy_code.strip()}\n\n"
        )
    module_block = (
        "Modules to integrate:\n"
        f"[indicator_factor requirement]\n{indicator_module.get('requirement', '')}\n"
        f"[indicator_factor code]\n{indicator_module.get('module_code', '')}\n\n"
        f"[position_adjustment requirement]\n{position_module.get('requirement', '')}\n"
        f"[position_adjustment code]\n{position_module.get('module_code', '')}\n\n"
        f"[risk_system requirement]\n{risk_module.get('requirement', '')}\n"
        f"[risk_system code]\n{risk_module.get('module_code', '')}\n"
    )
    if not has_modules:
        module_block = (
            "Module constraints:\n"
            "- No module snippets are provided for this run.\n"
            "- You are allowed to redesign the strategy structure based on requirement and base strategy code.\n"
        )
    return (
        "Goal: generate a full freqtrade strategy file that can be backtested directly.\n\n"
        "Base config:\n"
        f"- class name: {strategy_name}\n"
        f"- timeframe: {payload.base.timeframe}\n"
        f"- can_short: {payload.base.can_short}\n\n"
        f"Strategy-level requirement:\n{payload.requirement.strip()}\n\n"
        f"{optimize_block}"
        f"{module_block}"
        f"{feedback_block}\n"
        "Output format (strict):\n"
        '{\n'
        '  "strategy_code": "full python file string",\n'
        '  "explain": "one sentence about integration choices"\n'
        '}\n'
        "Only output the JSON object."
    )


def _build_repair_system_prompt(persona_md: str) -> str:
    return (
        "You are a freqtrade strategy repair agent.\n"
        "Your job is to fix strategy validation/runtime errors while preserving the original strategy intent.\n\n"
        "Persona:\n"
        f"{persona_md.strip()}\n\n"
        "Rules:\n"
        "1) Output only one JSON object with keys strategy_code and explain.\n"
        "2) Keep the same class name and major strategy logic.\n"
        "3) Fix imports/signatures/invalid APIs/type mismatches causing failures.\n"
        "4) Ensure Python syntax correctness and freqtrade compatibility."
    )


def _build_repair_user_prompt(
    strategy_name: str,
    requirement: str,
    current_code: str,
    error_lines: list[str],
) -> str:
    tail = "\n".join(error_lines[-80:])
    return (
        f"Class name must remain: {strategy_name}\n"
        f"Strategy requirement:\n{requirement}\n\n"
        f"Runtime error logs:\n{tail}\n\n"
        f"Current strategy code:\n{current_code}\n\n"
        "Return JSON only:\n"
        '{\n'
        '  "strategy_code": "full fixed python file string",\n'
        '  "explain": "what you fixed for runtime compatibility"\n'
        '}'
    )


def _sanitize_strategy_code(strategy_code: str, strategy_name: str) -> str:
    code = _strip_code_fence(strategy_code).replace("\r\n", "\n").strip()

    remove_patterns = [
        r"(?m)^from __future__ import annotations\s*$\n?",
        r"(?m)^from freqtrade\.strategy import .*$\n?",
        r"(?m)^from freqtrade\.persistence import .*$\n?",
        r"(?m)^from pandas import .*$\n?",
        r"(?m)^import talib\.abstract as ta\s*$\n?",
        r"(?m)^from datetime import datetime\s*$\n?",
        r"(?m)^from typing import .*$\n?",
    ]
    for pattern in remove_patterns:
        code = re.sub(pattern, "", code)

    code = re.sub(r"\bRealParameter\s*\(", "DecimalParameter(", code)
    code = re.sub(r"(nbdevup\s*=\s*)(\d+)(?=\s*[,)\n])", r"\1\2.0", code)
    code = re.sub(r"(nbdevdn\s*=\s*)(\d+)(?=\s*[,)\n])", r"\1\2.0", code)
    code = re.sub(r"(nbdev\s*=\s*)(\d+)(?=\s*[,)\n])", r"\1\2.0", code)

    uses_qtpylib = "qtpylib." in code
    uses_np = "np." in code
    uses_pd = "pd." in code
    uses_optional_typing = any(token in code for token in ("Optional[", "Tuple[", "Union["))
    uses_int_parameter = "IntParameter(" in code
    uses_decimal_parameter = "DecimalParameter(" in code
    uses_categorical_parameter = "CategoricalParameter(" in code
    uses_boolean_parameter = "BooleanParameter(" in code
    uses_stoploss_from_open = "stoploss_from_open(" in code

    imports: list[str] = [
        "from __future__ import annotations",
        "",
        "from datetime import datetime",
    ]
    if uses_optional_typing:
        imports.append("from typing import Optional, Tuple, Union")
    imports.extend(
        [
            "",
            "import talib.abstract as ta",
            "from pandas import DataFrame",
            "",
            "from freqtrade.persistence import Trade",
            "from freqtrade.strategy import IStrategy",
        ]
    )

    insert_at = len(imports) - 2
    if uses_qtpylib:
        imports.insert(insert_at, "import freqtrade.vendor.qtpylib.indicators as qtpylib")
        insert_at += 1
    if uses_np:
        imports.insert(insert_at, "import numpy as np")
        insert_at += 1
    if uses_pd:
        imports.insert(insert_at, "import pandas as pd")

    strategy_symbols = ["IStrategy"]
    if uses_int_parameter:
        strategy_symbols.append("IntParameter")
    if uses_decimal_parameter:
        strategy_symbols.append("DecimalParameter")
    if uses_categorical_parameter:
        strategy_symbols.append("CategoricalParameter")
    if uses_boolean_parameter:
        strategy_symbols.append("BooleanParameter")
    if uses_stoploss_from_open:
        strategy_symbols.append("stoploss_from_open")

    for idx, line in enumerate(imports):
        if line.startswith("from freqtrade.strategy import "):
            imports[idx] = f"from freqtrade.strategy import {', '.join(strategy_symbols)}"
            break

    class_match = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*IStrategy\s*\)\s*:", code)
    if class_match and class_match.group(1) != strategy_name:
        code = re.sub(
            r"class\s+[A-Za-z_][A-Za-z0-9_]*\s*\(\s*IStrategy\s*\)\s*:",
            f"class {strategy_name}(IStrategy):",
            code,
            count=1,
        )

    merged = "\n".join(imports).strip() + "\n\n" + code.lstrip()
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip() + "\n"
    return merged


def _validate_strategy_code(strategy_code: str, strategy_name: str) -> None:
    required_tokens = [
        "from freqtrade.strategy import IStrategy",
        "from freqtrade.persistence import Trade",
        f"class {strategy_name}(IStrategy):",
        "INTERFACE_VERSION",
        "timeframe",
        "can_short",
        "def populate_indicators",
        "def populate_entry_trend",
        "def populate_exit_trend",
        "def custom_stake_amount",
        "def adjust_trade_position",
        "minimal_roi",
        "stoploss",
    ]
    missing = [token for token in required_tokens if token not in strategy_code]
    if missing:
        raise ValueError(f"Missing required strategy parts: {', '.join(missing)}")

    bad_strategy_import = re.search(
        r"^from\s+freqtrade\.strategy\s+import\s+(.+)$",
        strategy_code,
        flags=re.MULTILINE,
    )
    if bad_strategy_import:
        imported = {item.strip() for item in bad_strategy_import.group(1).split(",")}
        allowed = {
            "IStrategy",
            "IntParameter",
            "DecimalParameter",
            "CategoricalParameter",
            "BooleanParameter",
            "stoploss_from_open",
        }
        if not imported.issubset(allowed):
            raise ValueError(f"Unsupported freqtrade.strategy imports: {sorted(imported - allowed)}")

    if "```" in strategy_code:
        raise ValueError("strategy_code contains code fence")

    try:
        ast.parse(strategy_code)
    except SyntaxError as exc:
        raise ValueError(f"Generated strategy has syntax error: {exc}") from exc


def _run_static_validation(strategy_code: str, strategy_name: str) -> tuple[bool, list[str], str | None]:
    logs = ["[mvp-static] validating strategy syntax and required structure"]
    try:
        _validate_strategy_code(strategy_code, strategy_name)
        logs.append("[mvp-static] validation passed")
        return True, logs, None
    except ValueError as exc:
        logs.append(f"[mvp-static] validation failed: {exc}")
        return False, logs, str(exc)


def _generate_strategy_via_llm(
    payload: ComposeStrategyRequest,
    strategy_name: str,
    indicator_module: dict,
    position_module: dict,
    risk_module: dict,
) -> tuple[str, str]:
    identity = get_ai_identity()
    system_prompt = _build_system_prompt(identity.persona_md)

    feedback: str | None = None
    last_error = "unknown"

    for _ in range(2):
        user_prompt = _build_user_prompt(
            payload=payload,
            strategy_name=strategy_name,
            indicator_module=indicator_module,
            position_module=position_module,
            risk_module=risk_module,
            feedback=feedback,
        )
        try:
            completion = complete_text(identity, system_prompt, user_prompt)
            data = _extract_json_object(completion.text)
            strategy_code = _sanitize_strategy_code(
                _strip_code_fence(str(data.get("strategy_code", ""))),
                strategy_name=strategy_name,
            )
            explain = str(data.get("explain", "")).strip() or "AI composed full strategy code."
            if not strategy_code:
                raise ValueError("strategy_code is empty")
            _validate_strategy_code(strategy_code, strategy_name)
            return strategy_code, explain
        except ValueError as exc:
            last_error = str(exc)
            feedback = f"Output invalid: {last_error}"
            continue
        except LlmAdapterError as exc:
            raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    raise HTTPException(status_code=502, detail=f"AI output invalid after retries: {last_error}")


def _repair_strategy_via_llm(
    strategy_name: str,
    requirement: str,
    current_code: str,
    error_lines: list[str],
) -> tuple[str, str]:
    identity = get_ai_identity()
    system_prompt = _build_repair_system_prompt(identity.persona_md)
    user_prompt = _build_repair_user_prompt(
        strategy_name=strategy_name,
        requirement=requirement,
        current_code=current_code,
        error_lines=error_lines,
    )
    try:
        completion = complete_text(identity, system_prompt, user_prompt)
        data = _extract_json_object(completion.text)
        strategy_code = _sanitize_strategy_code(
            _strip_code_fence(str(data.get("strategy_code", ""))),
            strategy_name=strategy_name,
        )
        explain = str(data.get("explain", "")).strip() or "AI repaired strategy issues."
        _validate_strategy_code(strategy_code, strategy_name)
        return strategy_code, explain
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"AI repair output invalid: {exc}") from exc
    except LlmAdapterError as exc:
        raise HTTPException(status_code=502, detail=f"LLM repair call failed: {exc}") from exc


def repair_strategy_with_ai(
    strategy_name: str,
    requirement: str,
    current_code: str,
    error_lines: list[str],
) -> tuple[str, str]:
    return _repair_strategy_via_llm(
        strategy_name=strategy_name,
        requirement=requirement,
        current_code=current_code,
        error_lines=error_lines,
    )


def compose_strategy(payload: ComposeStrategyRequest) -> ComposeStrategyResponse:
    modules = payload.modules
    module_versions = {
        "indicator_factor": str(modules.indicator_factor_version_id).strip() if modules and modules.indicator_factor_version_id else "",
        "position_adjustment": str(modules.position_adjustment_version_id).strip() if modules and modules.position_adjustment_version_id else "",
        "risk_system": str(modules.risk_system_version_id).strip() if modules and modules.risk_system_version_id else "",
    }
    has_full_modules = all(module_versions.values())
    optimize_mode = bool(payload.base_strategy_code and payload.base_strategy_code.strip())

    if not has_full_modules and not optimize_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                "Compose requires 3 module versions for initial assembly. "
                "For strategy-only optimization, provide base_strategy_code."
            ),
        )

    if has_full_modules:
        indicator_module = _load_module(module_versions["indicator_factor"])
        position_module = _load_module(module_versions["position_adjustment"])
        risk_module = _load_module(module_versions["risk_system"])
    else:
        indicator_module = {"requirement": "", "module_code": ""}
        position_module = {"requirement": "", "module_code": ""}
        risk_module = {"requirement": "", "module_code": ""}

    strategy_name = _safe_class_name(payload.strategy_name)
    source_versions = {key: value for key, value in module_versions.items() if value}

    strategy_code, compose_note = _generate_strategy_via_llm(
        payload=payload,
        strategy_name=strategy_name,
        indicator_module=indicator_module,
        position_module=position_module,
        risk_module=risk_module,
    )

    strategy_path = GENERATED_STRATEGY_DIR / f"{strategy_name}.py"
    strategy_path.write_text(strategy_code, encoding="utf-8")

    validation_logs: list[str] = []
    validation_passed = True
    repair_rounds = 0
    repair_notes: list[str] = []

    if payload.validation.enable:
        ok, logs, error = _run_static_validation(strategy_code, strategy_name)
        validation_logs.extend([f"[validate:init] {line}" for line in logs[-120:]])

        while not ok and repair_rounds < payload.validation.max_repair_rounds:
            repair_rounds += 1
            strategy_code, repair_note = _repair_strategy_via_llm(
                strategy_name=strategy_name,
                requirement=payload.requirement,
                current_code=strategy_code,
                error_lines=logs,
            )
            repair_notes.append(f"round={repair_rounds}: {repair_note}")
            strategy_path.write_text(strategy_code, encoding="utf-8")

            ok, logs, error = _run_static_validation(strategy_code, strategy_name)
            validation_logs.extend([f"[validate:repair{repair_rounds}] {line}" for line in logs[-120:]])

        validation_passed = ok
        if not validation_passed:
            tail = "\n".join(validation_logs[-40:])
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Static strategy validation failed after {repair_rounds} repair rounds. "
                    f"Last error: {error}\n{tail}"
                ),
            )

    strategy_code, optimize_note = optimize_strategy_code(strategy_code, source_versions)
    strategy_code = _sanitize_strategy_code(strategy_code, strategy_name=strategy_name)
    _validate_strategy_code(strategy_code, strategy_name)

    warnings: list[str] = []
    lint_ok = True
    try:
        ast.parse(strategy_code)
    except SyntaxError as exc:
        lint_ok = False
        warnings.append(f"SyntaxError: {exc}")

    if not lint_ok:
        raise HTTPException(status_code=502, detail=f"AI composed strategy is invalid: {'; '.join(warnings)}")

    strategy_path.write_text(strategy_code, encoding="utf-8")

    optimization_note = " ".join(
        part for part in [compose_note, *repair_notes, optimize_note] if part
    ).strip()

    build_id = new_id("build")
    build_record = {
        "build_id": build_id,
        "strategy_name": strategy_name,
        "strategy_file": str(strategy_path),
        "strategy_code": strategy_code,
        "base": _model_to_dict(payload.base),
        "modules": _model_to_dict(payload.modules),
        "requirement": payload.requirement,
        "base_build_id": payload.base_build_id,
        "optimize_mode": optimize_mode,
        "validation": _model_to_dict(payload.validation),
        "validation_passed": validation_passed,
        "validation_logs": validation_logs,
        "repair_rounds": repair_rounds,
        "lint_ok": lint_ok,
        "warnings": warnings,
        "optimization_note": optimization_note,
        "source_versions": source_versions,
    }
    write_json(BUILD_DIR / f"{build_id}.json", build_record)

    return ComposeStrategyResponse(
        build_id=build_id,
        strategy_file=str(strategy_path),
        lint_ok=lint_ok,
        warnings=warnings,
        optimization_note=optimization_note,
        source_versions=source_versions,
        strategy_code=strategy_code,
        validation_passed=validation_passed,
        validation_logs=validation_logs[-120:],
        repair_rounds=repair_rounds,
    )


def repair_strategy_file(strategy_file: Path, strategy_name: str) -> None:
    if not strategy_file.exists():
        return
    original = strategy_file.read_text(encoding="utf-8")
    repaired = _sanitize_strategy_code(original, strategy_name=strategy_name)
    _validate_strategy_code(repaired, strategy_name=strategy_name)
    if repaired != original:
        strategy_file.write_text(repaired, encoding="utf-8")


def load_build(build_id: str) -> dict:
    path = BUILD_DIR / f"{build_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"build not found: {build_id}")
    payload = read_json(path)
    strategy_file = Path(payload["strategy_file"])
    if not strategy_file.exists():
        raise HTTPException(status_code=404, detail=f"strategy file not found: {strategy_file}")
    return payload
