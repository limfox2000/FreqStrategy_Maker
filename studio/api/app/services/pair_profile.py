from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..schemas.pair_profile import PairProfilePayload, PairProfileResponse, PairProfileValue
from .param_registry import validate_registry_keys
from .storage import FREQTRADE_PAIR_PROFILE_PATH, PAIR_PROFILE_PATH, read_json, write_json


DEFAULT_PAIR_PROFILE = {
    "defaults": {},
    "pairs": {},
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_pair_key(pair: str) -> str:
    raw = str(pair).strip()
    if not raw:
        return ""
    if "/" not in raw:
        return raw.upper()
    base_quote, *rest = raw.split(":", 1)
    base_quote = base_quote.upper()
    if rest:
        return f"{base_quote}:{rest[0].upper()}"
    return base_quote


def pair_key_candidates(pair: str) -> list[str]:
    normalized = normalize_pair_key(pair)
    if not normalized:
        return []

    candidates: list[str] = [normalized]
    if ":" in normalized:
        candidates.append(normalized.split(":", 1)[0])
    if "/" in normalized:
        candidates.append(normalized.split("/", 1)[0])

    dedup: list[str] = []
    seen: set[str] = set()
    for key in candidates:
        token = key.strip()
        if not token:
            continue
        upper = token.upper()
        if upper in seen:
            continue
        seen.add(upper)
        dedup.append(upper)
    return dedup


def _normalize_scalar(value: Any) -> PairProfileValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    raise ValueError(f"Only primitive values are supported in pair profile, got: {type(value).__name__}")


def _normalize_profile_map(raw: Any) -> dict[str, PairProfileValue]:
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, PairProfileValue] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            continue
        clean[name] = _normalize_scalar(value)
    return clean


def _normalize_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}

    defaults = _normalize_profile_map(raw.get("defaults"))
    pairs_raw = raw.get("pairs")
    pairs: dict[str, dict[str, PairProfileValue]] = {}
    if isinstance(pairs_raw, dict):
        for pair, attrs in pairs_raw.items():
            pair_key = normalize_pair_key(str(pair))
            if not pair_key:
                continue
            pairs[pair_key] = _normalize_profile_map(attrs)

    updated_at = str(raw.get("updated_at", "")).strip() or _iso_now()
    return {
        "defaults": defaults,
        "pairs": pairs,
        "updated_at": updated_at,
    }


def _ensure_profile_file() -> None:
    if PAIR_PROFILE_PATH.exists():
        return
    payload = {
        **DEFAULT_PAIR_PROFILE,
        "updated_at": _iso_now(),
    }
    write_json(PAIR_PROFILE_PATH, payload)
    write_json(FREQTRADE_PAIR_PROFILE_PATH, payload)


def _read_normalized() -> dict[str, Any]:
    _ensure_profile_file()
    payload = _normalize_payload(read_json(PAIR_PROFILE_PATH))
    # Always keep the freqtrade mirror in sync for strategy runtime.
    write_json(FREQTRADE_PAIR_PROFILE_PATH, payload)
    return payload


def _to_response(payload: dict[str, Any]) -> PairProfileResponse:
    return PairProfileResponse(
        defaults=payload["defaults"],
        pairs=payload["pairs"],
        updated_at=payload["updated_at"],
        storage_file=str(PAIR_PROFILE_PATH),
        freqtrade_file=str(FREQTRADE_PAIR_PROFILE_PATH),
    )


def get_pair_profile() -> PairProfileResponse:
    return _to_response(_read_normalized())


def save_pair_profile(payload: PairProfilePayload) -> PairProfileResponse:
    normalized = _normalize_payload(
        {
            "defaults": payload.defaults,
            "pairs": payload.pairs,
            "updated_at": _iso_now(),
        }
    )
    keys: set[str] = set(normalized["defaults"].keys())
    for attrs in normalized["pairs"].values():
        keys.update(attrs.keys())
    unknown_keys = validate_registry_keys(keys)
    if unknown_keys:
        preview = ", ".join(unknown_keys[:12])
        suffix = " ..." if len(unknown_keys) > 12 else ""
        raise ValueError(
            "Pair profile contains undefined variables. "
            f"Please declare them first in param_registry.json. unknown={preview}{suffix}"
        )
    write_json(PAIR_PROFILE_PATH, normalized)
    write_json(FREQTRADE_PAIR_PROFILE_PATH, normalized)
    return _to_response(normalized)


def _resolve_pair_profile_from_payload(
    payload: dict[str, Any],
    pair: str,
) -> tuple[dict[str, PairProfileValue], str | None, list[str]]:
    defaults = payload.get("defaults", {})
    pairs = payload.get("pairs", {})

    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(pairs, dict):
        pairs = {}

    effective: dict[str, PairProfileValue] = _normalize_profile_map(defaults)
    matched_key: str | None = None
    candidates = pair_key_candidates(pair)

    for candidate in candidates:
        attrs = pairs.get(candidate)
        if isinstance(attrs, dict):
            effective.update(_normalize_profile_map(attrs))
            matched_key = candidate
            break

    return effective, matched_key, candidates


def resolve_pair_profile(
    pair: str,
) -> tuple[dict[str, PairProfileValue], str | None, list[str]]:
    return _resolve_pair_profile_from_payload(_read_normalized(), pair)


def build_pair_profile_prompt_block(pair: str) -> str:
    payload = _read_normalized()
    effective, matched_key, candidates = _resolve_pair_profile_from_payload(payload, pair)
    pairs = payload.get("pairs", {})
    pair_items = list(pairs.items()) if isinstance(pairs, dict) else []

    preview_pairs: dict[str, Any] = {}
    for idx, (pair_key, attrs) in enumerate(pair_items):
        if idx >= 12:
            break
        if isinstance(attrs, dict):
            preview_pairs[pair_key] = attrs

    preview_payload = {
        "defaults": payload.get("defaults", {}),
        "pairs": preview_pairs,
    }

    return (
        "Pair profile configuration:\n"
        f"- source file: {FREQTRADE_PAIR_PROFILE_PATH}\n"
        f"- pair lookup candidates: {candidates or ['(none)']}\n"
        f"- matched pair key: {matched_key or 'none'}\n"
        f"- effective attrs for current pair: {json.dumps(effective, ensure_ascii=False)}\n"
        "- runtime helper available: pair_profile_helper.get_pair_int/get_pair_float/get_pair_value\n"
        "- generation rule: when a parameter can be pair-specific, read pair profile first; "
        "if missing, fallback to defaults, then fallback to in-code hard default.\n"
        f"- config preview: {json.dumps(preview_payload, ensure_ascii=False)}"
    )
