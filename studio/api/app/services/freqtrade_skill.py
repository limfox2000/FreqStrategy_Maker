from __future__ import annotations

import ast
import json
import re
import textwrap
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from ..schemas.module import CardType, GenerateModuleRequest, GenerateModuleResponse
from .ai_runtime import AI_SECRETS_PATH, get_ai_identity
from .llm_adapter import LlmAdapterError, complete_text
from .param_registry import build_param_registry_prompt_block
from .pair_profile import build_pair_profile_prompt_block
from .storage import MODULE_DIR, new_id, write_json


@dataclass
class GeneratedModule:
    module_code: str
    params: dict[str, float | int | str | bool]
    explain: str


def _model_to_dict(model: Any) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _build_system_prompt(persona_md: str) -> str:
    return (
        "You are a freqtrade module code generator.\n"
        "Persona (must follow):\n"
        f"{persona_md.strip()}\n\n"
        "Global rules:\n"
        "1) Output exactly one JSON object. No markdown or code fences.\n"
        "2) JSON keys must be: module_code, params, explain.\n"
        "3) module_code must be a Python fragment for IStrategy class body only (no import/class).\n"
        "4) Generate code only for the requested module card type.\n"
        "5) Respect explicit numeric constraints in requirement.\n"
        "6) When parameters can be pair-specific, preserve default fallback behavior.\n"
        "7) For pair-configurable keys, only use names from parameter registry."
    )


def _build_module_brief(card_type: CardType, can_short: bool) -> str:
    if card_type == "indicator_factor":
        short_instruction = (
            "can_short=True: include enter_short logic."
            if can_short
            else "can_short=False: keep enter_short column but force it to 0 without short conditions."
        )
        return (
            "Module type: indicator_factor\n"
            "Goal: generate indicator + entry/exit logic.\n"
            "Required functions:\n"
            "- def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame\n"
            "- def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame\n"
            "- def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame\n"
            "Implementation rules:\n"
            "- Use ta.* indicators prepared by strategy imports.\n"
            "- Set enter_long/enter_short/enter_tag in entry function.\n"
            "- Set exit_long/exit_short in exit function.\n"
            f"- {short_instruction}\n"
            "Forbidden:\n"
            "- custom_stake_amount / adjust_trade_position / minimal_roi / stoploss"
        )

    if card_type == "position_adjustment":
        return (
            "Module type: position_adjustment\n"
            "Goal: generate position sizing and add/reduce logic.\n"
            "Required functions:\n"
            "- def custom_stake_amount(...)\n"
            "- def adjust_trade_position(...)\n"
            "Recommended class attrs:\n"
            "- position_adjustment_enable\n"
            "- max_entry_position_adjustment\n"
            "- stake_split or equivalent\n"
            "Forbidden:\n"
            "- populate_indicators/populate_entry_trend/populate_exit_trend\n"
            "- minimal_roi/stoploss/trailing_*"
        )

    return (
        "Module type: risk_system\n"
        "Goal: generate risk parameter block.\n"
        "Required attrs:\n"
        "- minimal_roi\n"
        "- stoploss\n"
        "- trailing_stop\n"
        "- trailing_stop_positive\n"
        "- trailing_stop_positive_offset\n"
        "- trailing_only_offset_is_reached\n"
        "- use_exit_signal\n"
        "- exit_profit_only\n"
        "Rules:\n"
        "- If requirement contains stoploss X%, set stoploss = -X/100.\n"
        "- If requirement contains take profit X%, set minimal_roi['0'] = X/100.\n"
        "Forbidden:\n"
        "- any populate_* / custom_stake_amount / adjust_trade_position"
    )


def _build_user_prompt(payload: GenerateModuleRequest, feedback: str | None = None) -> str:
    context = payload.context
    rules = _build_module_brief(payload.card_type, context.can_short)
    param_registry_block = build_param_registry_prompt_block()
    pair_profile_block = build_pair_profile_prompt_block(context.pair)
    feedback_block = f"\nPrevious output issue (must fix):\n{feedback.strip()}\n" if feedback else ""
    optimize_block = ""
    if payload.optimize_target_code:
        optimize_block = (
            "\nOptimization mode:\n"
            "- You must optimize the existing module code below, not rewrite from scratch.\n"
            "- Keep module boundaries unchanged for this card type.\n"
            "- Preserve useful existing logic unless it conflicts with the new requirement.\n"
            f"- Base version: {payload.optimize_from_version_id or 'unknown'}\n"
            "[existing_module_code]\n"
            f"{payload.optimize_target_code.strip()}\n"
        )
    return (
        f"{rules}\n\n"
        "Context:\n"
        f"- timeframe: {context.timeframe}\n"
        f"- pair: {context.pair}\n"
        f"- can_short: {context.can_short}\n\n"
        f"{param_registry_block}\n\n"
        f"{pair_profile_block}\n\n"
        f"User requirement:\n{payload.requirement.strip()}\n"
        f"{optimize_block}"
        f"{feedback_block}\n"
        "Output format (strict):\n"
        '{\n'
        '  "module_code": "string, Python code only",\n'
        '  "params": {"key": "value"},\n'
        '  "explain": "one sentence about optimization or generation"\n'
        '}\n'
        "Only output the JSON object."
    )


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


def _normalize_params(raw_params: Any) -> dict[str, float | int | str | bool]:
    if not isinstance(raw_params, dict):
        return {}

    clean: dict[str, float | int | str | bool] = {}
    for key, value in raw_params.items():
        name = str(key)
        if isinstance(value, bool):
            clean[name] = value
        elif isinstance(value, (int, float, str)):
            clean[name] = value
        elif value is None:
            clean[name] = "null"
        else:
            clean[name] = json.dumps(value, ensure_ascii=False)
    return clean


def _strip_code_fence(code: str) -> str:
    cleaned = code.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_+-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _normalize_module_code(module_code: str) -> str:
    raw = module_code.replace("\r\n", "\n").strip("\n")
    if not raw:
        return raw

    def_pattern = re.compile(r"^\s*def\s+\w+\s*\(", re.IGNORECASE)
    lines = raw.split("\n")
    attrs: list[str] = []
    functions: list[list[str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if def_pattern.match(line):
            def_line = line.strip()
            i += 1
            body_lines: list[str] = []
            while i < len(lines) and not def_pattern.match(lines[i]):
                body_lines.append(lines[i].rstrip())
                i += 1
            body_text = textwrap.dedent("\n".join(body_lines))
            normalized_body = [
                ("    " + body_line.rstrip()) if body_line.strip() else ""
                for body_line in body_text.split("\n")
            ]
            functions.append([def_line, *normalized_body])
            continue
        attrs.append(line.rstrip())
        i += 1

    normalized_attrs = [line.strip() for line in attrs if line.strip()]

    merged: list[str] = []
    if normalized_attrs:
        merged.extend(normalized_attrs)
    for fn in functions:
        if merged:
            merged.append("")
        merged.extend(fn)
    return "\n".join(merged).strip()


def _validate_fragment_python(module_code: str) -> None:
    probe_code = "class _Probe:\n" + textwrap.indent(module_code, "    ")
    try:
        ast.parse(probe_code)
    except SyntaxError as exc:
        raise ValueError(f"Generated python fragment has syntax error: {exc}") from exc


def _extract_percent_near_keyword(requirement: str, keywords: list[str]) -> float | None:
    for keyword in keywords:
        pattern = rf"{re.escape(keyword)}[^\d]{{0,10}}(\d+(?:\.\d+)?)\s*(?:%|％|percent)?"
        try:
            matched = re.search(pattern, requirement, re.IGNORECASE)
        except re.error:
            continue
        if matched:
            return float(matched.group(1))
    return None


def _extract_stoploss_from_code(module_code: str) -> float | None:
    matched = re.search(r"^\s*stoploss\s*=\s*(-?\d+(?:\.\d+)?)", module_code, re.MULTILINE)
    if matched:
        return float(matched.group(1))
    return None


def _extract_roi0_from_code(module_code: str) -> float | None:
    matched = re.search(r"[\"']0[\"']\s*:\s*(-?\d+(?:\.\d+)?)", module_code, re.IGNORECASE)
    if matched:
        return float(matched.group(1))
    return None


def _extract_stake_split_from_code(module_code: str) -> float | None:
    matched = re.search(r"^\s*stake_split\s*=\s*(\d+(?:\.\d+)?)", module_code, re.MULTILINE)
    if matched:
        return float(matched.group(1))
    return None


def _validate_requirement_alignment(card_type: CardType, requirement: str, module_code: str) -> None:
    if card_type == "risk_system":
        stoploss_pct = _extract_percent_near_keyword(requirement, ["止损", "stoploss", "stop loss", "sl"])
        if stoploss_pct is not None:
            actual_stoploss = _extract_stoploss_from_code(module_code)
            expected = -stoploss_pct / 100.0
            if actual_stoploss is None or abs(actual_stoploss - expected) > 0.002:
                raise ValueError(
                    f"stoploss mismatch. expected about {expected:.4f}, got {actual_stoploss}"
                )

        take_profit_pct = _extract_percent_near_keyword(
            requirement,
            ["目标止盈", "止盈", "take profit", "target profit", "tp"],
        )
        if take_profit_pct is not None:
            actual_roi0 = _extract_roi0_from_code(module_code)
            expected = take_profit_pct / 100.0
            if actual_roi0 is None or abs(actual_roi0 - expected) > 0.002:
                raise ValueError(f"minimal_roi['0'] mismatch. expected about {expected:.4f}, got {actual_roi0}")

    if card_type == "indicator_factor":
        ema_values = re.findall(r"EMA\s*(\d{1,3})", requirement, re.IGNORECASE)
        for ema in dict.fromkeys(ema_values):  # remove duplicates, keep order
            if re.search(rf"(?<!\d){re.escape(str(ema))}(?!\d)", module_code) is None:
                raise ValueError(f"EMA period {ema} is required but not reflected in module_code")

    if card_type == "position_adjustment":
        split_match = re.search(
            r"(?:拆成|分成|split)[^\d]{0,8}(\d+)\s*(?:份|part|batch|pieces?)?",
            requirement,
            re.IGNORECASE,
        )
        if split_match:
            expected_split = float(split_match.group(1))
            actual_split = _extract_stake_split_from_code(module_code)
            if actual_split is None or abs(actual_split - expected_split) > 0.01:
                raise ValueError(f"stake_split mismatch. expected {expected_split:g}, got {actual_split}")


def _validate_module_code(card_type: CardType, module_code: str) -> None:
    required_map: dict[CardType, list[str]] = {
        "indicator_factor": [
            "def populate_indicators",
            "def populate_entry_trend",
            "def populate_exit_trend",
        ],
        "position_adjustment": [
            "def custom_stake_amount",
            "def adjust_trade_position",
        ],
        "risk_system": [
            "minimal_roi",
            "stoploss",
        ],
    }
    forbidden_map: dict[CardType, list[str]] = {
        "indicator_factor": [
            "def custom_stake_amount",
            "def adjust_trade_position",
            "minimal_roi",
            "stoploss",
        ],
        "position_adjustment": [
            "def populate_indicators",
            "def populate_entry_trend",
            "def populate_exit_trend",
            "minimal_roi",
            "stoploss",
        ],
        "risk_system": [
            "def populate_indicators",
            "def populate_entry_trend",
            "def populate_exit_trend",
            "def custom_stake_amount",
            "def adjust_trade_position",
        ],
    }

    missing = [token for token in required_map[card_type] if token not in module_code]
    if missing:
        raise ValueError(f"Missing required code parts: {', '.join(missing)}")

    forbidden = [token for token in forbidden_map[card_type] if token in module_code]
    if forbidden:
        raise ValueError(f"Cross-module code detected: {', '.join(forbidden)}")


def _parse_generated_module(card_type: CardType, raw_text: str) -> GeneratedModule:
    payload = _extract_json_object(raw_text)

    module_code = _normalize_module_code(_strip_code_fence(str(payload.get("module_code", ""))))
    if not module_code:
        raise ValueError("module_code is empty")
    _validate_module_code(card_type, module_code)
    _validate_fragment_python(module_code)

    params = _normalize_params(payload.get("params"))
    explain = str(payload.get("explain", "")).strip() or "AI generated module code."

    return GeneratedModule(module_code=module_code, params=params, explain=explain)


def _generate_via_llm(payload: GenerateModuleRequest) -> GeneratedModule:
    identity = get_ai_identity()
    if not identity.api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider '{identity.provider}' API key is not configured. "
                f"Please set it in {AI_SECRETS_PATH} or provider environment variable."
            ),
        )

    system_prompt = _build_system_prompt(identity.persona_md)
    feedback: str | None = None
    last_error = "unknown"

    for _ in range(2):
        user_prompt = _build_user_prompt(payload, feedback=feedback)
        try:
            completion = complete_text(identity, system_prompt, user_prompt)
            generated = _parse_generated_module(payload.card_type, completion.text)
            _validate_requirement_alignment(payload.card_type, payload.requirement, generated.module_code)
            return generated
        except ValueError as exc:
            last_error = str(exc)
            feedback = f"杈撳嚭涓嶅悎鏍? {last_error}"
            continue
        except LlmAdapterError as exc:
            raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    raise HTTPException(status_code=502, detail=f"AI output invalid after retries: {last_error}")


def generate_module(payload: GenerateModuleRequest) -> GenerateModuleResponse:
    identity = get_ai_identity()
    generated = _generate_via_llm(payload)
    version_id = new_id("mod")

    record = {
        "version_id": version_id,
        "card_type": payload.card_type,
        "requirement": payload.requirement,
        "context": _model_to_dict(payload.context),
        "optimize_from_version_id": payload.optimize_from_version_id,
        "optimize_mode": bool(payload.optimize_target_code),
        "module_code": generated.module_code,
        "params": generated.params,
        "explain": (
            f"{generated.explain} "
            f"[preset={identity.preset_key} identity={identity.provider}/{identity.model}]"
        ),
    }
    write_json(MODULE_DIR / f"{version_id}.json", record)

    return GenerateModuleResponse(
        version_id=version_id,
        card_type=payload.card_type,
        module_code=generated.module_code,
        params=generated.params,
        explain=record["explain"],
    )


