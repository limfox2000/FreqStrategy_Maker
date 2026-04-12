from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_CACHE_PAYLOAD: dict[str, Any] | None = None
_CACHE_MTIME: float | None = None
_CACHE_PATH: Path | None = None


def _discover_default_profile_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == "user_data":
            return parent / "pair_profiles.json"
    return Path(__file__).resolve().parent / "pair_profiles.json"


def _normalize_pair_key(pair: str) -> str:
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


def _pair_candidates(pair: str) -> list[str]:
    normalized = _normalize_pair_key(pair)
    if not normalized:
        return []

    options = [normalized]
    if ":" in normalized:
        options.append(normalized.split(":", 1)[0])
    if "/" in normalized:
        options.append(normalized.split("/", 1)[0])

    dedup: list[str] = []
    seen: set[str] = set()
    for item in options:
        key = item.strip().upper()
        if not key or key in seen:
            continue
        seen.add(key)
        dedup.append(key)
    return dedup


def _select_profile_path(config_path: str | Path | None = None) -> Path:
    if config_path:
        candidate = Path(config_path)
        if candidate.exists():
            return candidate

    fixed = Path("/freqtrade/user_data/pair_profiles.json")
    if fixed.exists():
        return fixed

    local = _discover_default_profile_path()
    if local.exists():
        return local

    return fixed


def _sanitize_profile(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    defaults = payload.get("defaults")
    pairs = payload.get("pairs")
    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(pairs, dict):
        pairs = {}

    clean_pairs: dict[str, dict[str, Any]] = {}
    for pair_key, attrs in pairs.items():
        key = _normalize_pair_key(str(pair_key))
        if not key or not isinstance(attrs, dict):
            continue
        clean_pairs[key] = dict(attrs)

    return {
        "defaults": dict(defaults),
        "pairs": clean_pairs,
    }


def _load_payload(config_path: str | Path | None = None) -> dict[str, Any]:
    global _CACHE_PAYLOAD, _CACHE_MTIME, _CACHE_PATH

    path = _select_profile_path(config_path)
    mtime = path.stat().st_mtime if path.exists() else None

    with _LOCK:
        if _CACHE_PAYLOAD is not None and _CACHE_PATH == path and _CACHE_MTIME == mtime:
            return _CACHE_PAYLOAD

        if not path.exists():
            payload = {"defaults": {}, "pairs": {}}
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:  # noqa: BLE001
                payload = {"defaults": {}, "pairs": {}}

        sanitized = _sanitize_profile(payload)
        _CACHE_PAYLOAD = sanitized
        _CACHE_PATH = path
        _CACHE_MTIME = mtime
        return sanitized


def get_pair_attrs(pair: str, config_path: str | Path | None = None) -> tuple[dict[str, Any], str | None]:
    payload = _load_payload(config_path)
    defaults = payload.get("defaults", {})
    pairs = payload.get("pairs", {})

    effective = dict(defaults) if isinstance(defaults, dict) else {}
    matched_key: str | None = None

    if isinstance(pairs, dict):
        for candidate in _pair_candidates(pair):
            attrs = pairs.get(candidate)
            if isinstance(attrs, dict):
                effective.update(attrs)
                matched_key = candidate
                break

    return effective, matched_key


def get_pair_value(pair: str, key: str, default: Any, config_path: str | Path | None = None) -> Any:
    attrs, _ = get_pair_attrs(pair, config_path=config_path)
    return attrs.get(key, default)


def get_pair_int(pair: str, key: str, default: int, config_path: str | Path | None = None) -> int:
    value = get_pair_value(pair, key, default, config_path=config_path)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def get_pair_float(pair: str, key: str, default: float, config_path: str | Path | None = None) -> float:
    value = get_pair_value(pair, key, default, config_path=config_path)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

