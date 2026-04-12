from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .storage import FREQTRADE_PARAM_REGISTRY_PATH, PARAM_REGISTRY_PATH, read_json, write_json


REGISTRY_KEY_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*_[a-z][A-Za-z0-9]*_[a-z][A-Za-z0-9_]*$")

DEFAULT_PARAM_REGISTRY = {
    "naming_standard": "<Factor>_<Indicator>_<Property> e.g. Matrix_baseEMA_len",
    "key_regex": REGISTRY_KEY_PATTERN.pattern,
    "variables": {
        "Matrix_baseEMA_len": {
            "type": "int",
            "description": "Base EMA period",
            "default": 144,
            "min": 1,
            "max": 2000,
        }
    },
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_registry_file() -> None:
    studio_exists = PARAM_REGISTRY_PATH.exists()
    freqtrade_exists = FREQTRADE_PARAM_REGISTRY_PATH.exists()

    if studio_exists and freqtrade_exists:
        return
    if studio_exists and not freqtrade_exists:
        payload = _normalize_payload(read_json(PARAM_REGISTRY_PATH))
        write_json(FREQTRADE_PARAM_REGISTRY_PATH, payload)
        return
    if freqtrade_exists and not studio_exists:
        payload = _normalize_payload(read_json(FREQTRADE_PARAM_REGISTRY_PATH))
        write_json(PARAM_REGISTRY_PATH, payload)
        return

    payload = {
        **DEFAULT_PARAM_REGISTRY,
        "updated_at": _iso_now(),
    }
    write_json(PARAM_REGISTRY_PATH, payload)
    write_json(FREQTRADE_PARAM_REGISTRY_PATH, payload)


def _normalize_variable_meta(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"default": value}


def _normalize_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}

    naming_standard = str(raw.get("naming_standard", "")).strip() or DEFAULT_PARAM_REGISTRY["naming_standard"]
    variables_raw = raw.get("variables", {})
    variables: dict[str, dict[str, Any]] = {}
    if isinstance(variables_raw, dict):
        for key, value in variables_raw.items():
            name = str(key).strip()
            if not name:
                continue
            if not REGISTRY_KEY_PATTERN.fullmatch(name):
                continue
            variables[name] = _normalize_variable_meta(value)

    payload = {
        "naming_standard": naming_standard,
        "key_regex": REGISTRY_KEY_PATTERN.pattern,
        "variables": variables,
        "updated_at": str(raw.get("updated_at", "")).strip() or _iso_now(),
    }
    return payload


def read_param_registry() -> dict[str, Any]:
    _ensure_registry_file()
    studio_mtime = PARAM_REGISTRY_PATH.stat().st_mtime if PARAM_REGISTRY_PATH.exists() else -1.0
    freqtrade_mtime = FREQTRADE_PARAM_REGISTRY_PATH.stat().st_mtime if FREQTRADE_PARAM_REGISTRY_PATH.exists() else -1.0
    source = PARAM_REGISTRY_PATH if studio_mtime >= freqtrade_mtime else FREQTRADE_PARAM_REGISTRY_PATH
    payload = _normalize_payload(read_json(source))
    write_json(PARAM_REGISTRY_PATH, payload)
    write_json(FREQTRADE_PARAM_REGISTRY_PATH, payload)
    return payload


def list_registry_keys() -> set[str]:
    payload = read_param_registry()
    variables = payload.get("variables", {})
    if not isinstance(variables, dict):
        return set()
    return {str(key) for key in variables.keys()}


def validate_registry_keys(keys: set[str]) -> list[str]:
    clean_keys = {str(item).strip() for item in keys if str(item).strip()}
    if not clean_keys:
        return []

    allowed = list_registry_keys()
    if not allowed:
        # Empty registry means no strict restriction yet.
        return []

    unknown = sorted(key for key in clean_keys if key not in allowed)
    return unknown


def build_param_registry_prompt_block() -> str:
    payload = read_param_registry()
    variables = payload.get("variables", {})
    if not isinstance(variables, dict):
        variables = {}

    keys = list(variables.keys())
    preview_keys = keys[:80]
    preview_meta = {key: variables[key] for key in keys[:20]}

    return (
        "Parameter registry (single source of truth):\n"
        f"- source file: {FREQTRADE_PARAM_REGISTRY_PATH}\n"
        f"- naming standard: {payload.get('naming_standard', '')}\n"
        f"- key regex: {payload.get('key_regex', REGISTRY_KEY_PATTERN.pattern)}\n"
        f"- total variable keys: {len(keys)}\n"
        f"- key preview: {json.dumps(preview_keys, ensure_ascii=False)}\n"
        f"- metadata preview: {json.dumps(preview_meta, ensure_ascii=False)}\n"
        "Strict rule: only use variable names from this registry when defining pair-configurable parameters. "
        "Do not invent new key names."
    )
