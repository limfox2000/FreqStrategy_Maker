from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..schemas.pair_profile import (
    PairProfilePayload,
    PairProfilePreviewRequest,
    PairProfilePreviewResponse,
    PairProfileResponse,
    PairProfileValue,
)
from .param_registry import validate_registry_keys
from .storage import (
    BACKTEST_RESULTS_DIR,
    FREQTRADE_DIR,
    FREQTRADE_PAIR_PROFILE_PATH,
    PAIR_PROFILE_PATH,
    new_id,
    read_json,
    write_json,
)


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


def _read_payload_file(path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return _normalize_payload(read_json(path))
    except Exception:  # noqa: BLE001
        return None


def _payload_updated_at_ts(payload: dict[str, Any] | None) -> float:
    if not isinstance(payload, dict):
        return -1.0
    raw = str(payload.get("updated_at", "")).strip()
    if not raw:
        return -1.0
    try:
        normalized = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:  # noqa: BLE001
        return -1.0


def _select_latest_payload(
    studio_payload: dict[str, Any] | None,
    freqtrade_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if studio_payload is None and freqtrade_payload is None:
        return {
            **DEFAULT_PAIR_PROFILE,
            "updated_at": _iso_now(),
        }
    if studio_payload is None:
        return freqtrade_payload or {**DEFAULT_PAIR_PROFILE, "updated_at": _iso_now()}
    if freqtrade_payload is None:
        return studio_payload

    studio_mtime = PAIR_PROFILE_PATH.stat().st_mtime if PAIR_PROFILE_PATH.exists() else -1.0
    freqtrade_mtime = FREQTRADE_PAIR_PROFILE_PATH.stat().st_mtime if FREQTRADE_PAIR_PROFILE_PATH.exists() else -1.0

    if freqtrade_mtime > studio_mtime:
        return freqtrade_payload
    if studio_mtime > freqtrade_mtime:
        return studio_payload

    # If mtime ties, fallback to updated_at inside payload.
    studio_updated = _payload_updated_at_ts(studio_payload)
    freqtrade_updated = _payload_updated_at_ts(freqtrade_payload)
    if freqtrade_updated > studio_updated:
        return freqtrade_payload
    return studio_payload


def _ensure_profile_file() -> None:
    studio_exists = PAIR_PROFILE_PATH.exists()
    freqtrade_exists = FREQTRADE_PAIR_PROFILE_PATH.exists()

    if studio_exists and freqtrade_exists:
        return

    if studio_exists and not freqtrade_exists:
        payload = _read_payload_file(PAIR_PROFILE_PATH) or {**DEFAULT_PAIR_PROFILE, "updated_at": _iso_now()}
        write_json(FREQTRADE_PAIR_PROFILE_PATH, payload)
        return

    if freqtrade_exists and not studio_exists:
        payload = _read_payload_file(FREQTRADE_PAIR_PROFILE_PATH) or {**DEFAULT_PAIR_PROFILE, "updated_at": _iso_now()}
        write_json(PAIR_PROFILE_PATH, payload)
        return

    payload = {**DEFAULT_PAIR_PROFILE, "updated_at": _iso_now()}
    write_json(PAIR_PROFILE_PATH, payload)
    write_json(FREQTRADE_PAIR_PROFILE_PATH, payload)


def _read_normalized() -> dict[str, Any]:
    _ensure_profile_file()
    studio_payload = _read_payload_file(PAIR_PROFILE_PATH)
    freqtrade_payload = _read_payload_file(FREQTRADE_PAIR_PROFILE_PATH)
    return _select_latest_payload(studio_payload, freqtrade_payload)


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

    existing_payload = _read_normalized()
    existing_keys: set[str] = set((existing_payload.get("defaults", {}) or {}).keys())
    for attrs in (existing_payload.get("pairs", {}) or {}).values():
        if isinstance(attrs, dict):
            existing_keys.update(str(key) for key in attrs.keys())

    unknown_keys = [key for key in validate_registry_keys(keys) if key not in existing_keys]
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


def _is_docker_daemon_unavailable(text: str) -> bool:
    raw = text.lower()
    tokens = (
        "dockerdesktoplinuxengine",
        "failed to connect to the docker api",
        "cannot find the file specified",
        "the system cannot find the file specified",
        "error during connect",
        "is the docker daemon running",
    )
    return any(token in raw for token in tokens)


def _docker_not_ready_detail(extra: str | None = None) -> str:
    base = (
        "Pair profile preview requires Docker Desktop (Linux engine) for now.\n"
        "Current Docker daemon is not ready.\n"
        "Please start Docker Desktop and wait until engine is Running, then retry.\n"
        "Quick check in terminal: `docker version` / `docker info` should both succeed."
    )
    if extra:
        return f"{base}\n\nRaw error:\n{extra}"
    return base


def _is_preview_data_missing_error(text: str) -> bool:
    raw = text.lower()
    tokens = (
        "no data in timerange",
        "data file not found for pair",
        "resampled dataframe is empty",
    )
    return any(token in raw for token in tokens)


def _preview_command(payload: PairProfilePreviewRequest, output_container_path: str) -> list[str]:
    return [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "python",
        "freqtrade",
        "/freqtrade/user_data/tools/tv_zone_profile_preview.py",
        "--pair",
        payload.pair,
        "--timeframe",
        payload.timeframe,
        "--timerange",
        payload.timerange,
        "--max-points",
        str(payload.max_points),
        "--output",
        output_container_path,
    ]


def _run_command_lines(command: list[str], timeout_sec: int) -> tuple[int | None, list[str], str | None]:
    try:
        process = subprocess.Popen(
            command,
            cwd=str(FREQTRADE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        return None, [], f"Docker command not found: {exc}"

    try:
        stdout, _ = process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        process.kill()
        return None, [], "command timeout"

    lines = (stdout or "").splitlines()
    return process.returncode, lines, None


def _download_preview_data(payload: PairProfilePreviewRequest) -> tuple[int | None, list[str], str | None]:
    timeframes: list[str] = []
    for item in (str(payload.timeframe).strip().lower(), "1m"):
        if not item:
            continue
        if item not in timeframes:
            timeframes.append(item)

    trading_mode = "futures" if ":" in str(payload.pair) else "spot"
    command = [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "freqtrade",
        "freqtrade",
        "download-data",
        "--config",
        "/freqtrade/user_data/config.json",
        "--pairs",
        payload.pair,
        "--timeframes",
        *timeframes,
        "--timerange",
        payload.timerange,
        "--trading-mode",
        trading_mode,
    ]
    return _run_command_lines(command, timeout_sec=1200)


def preview_pair_profile(payload: PairProfilePreviewRequest) -> PairProfilePreviewResponse:
    _read_normalized()

    try:
        check = subprocess.run(
            ["docker", "info"],
            cwd=str(FREQTRADE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Docker command not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=503, detail=_docker_not_ready_detail("`docker info` timeout")) from exc

    check_out = "\n".join([check.stdout or "", check.stderr or ""]).strip()
    if check.returncode != 0:
        if _is_docker_daemon_unavailable(check_out):
            raise HTTPException(status_code=503, detail=_docker_not_ready_detail(check_out[-1200:]))
        raise HTTPException(status_code=503, detail=f"Docker check failed.\n{check_out[-1200:]}")

    output_host_path = BACKTEST_RESULTS_DIR / f"pair_profile_preview_{new_id('pv')}.json"
    output_container_path = f"/freqtrade/user_data/backtest_results/{output_host_path.name}"
    preview_cmd = _preview_command(payload, output_container_path)
    code, lines, run_error = _run_command_lines(preview_cmd, timeout_sec=600)
    if run_error:
        if run_error == "command timeout":
            raise HTTPException(status_code=504, detail="pair profile preview timeout (over 10 minutes)")
        raise HTTPException(status_code=500, detail=run_error)

    if code != 0:
        tail = "\n".join([line for line in lines if line.strip()][-40:])
        if _is_docker_daemon_unavailable(tail):
            raise HTTPException(status_code=503, detail=_docker_not_ready_detail(tail))

        # Strictly use requested recent timerange. If data is missing, auto download and retry once.
        if _is_preview_data_missing_error(tail):
            dl_code, dl_lines, dl_error = _download_preview_data(payload)
            if dl_error:
                raise HTTPException(status_code=500, detail=f"Auto download failed: {dl_error}")
            if dl_code != 0:
                dl_tail = "\n".join([line for line in dl_lines if line.strip()][-40:])
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Pair profile preview failed and auto data download also failed.\n"
                        f"download-data tail:\n{dl_tail}"
                    ),
                )

            code, lines, run_error = _run_command_lines(preview_cmd, timeout_sec=600)
            if run_error:
                if run_error == "command timeout":
                    raise HTTPException(status_code=504, detail="pair profile preview timeout (over 10 minutes)")
                raise HTTPException(status_code=500, detail=run_error)
            if code != 0:
                tail = "\n".join([line for line in lines if line.strip()][-40:])
                if _is_docker_daemon_unavailable(tail):
                    raise HTTPException(status_code=503, detail=_docker_not_ready_detail(tail))
                raise HTTPException(
                    status_code=400,
                    detail=f"Pair profile preview failed after auto data download.\n{tail}",
                )
        else:
            detail = "Pair profile preview failed."
            if tail:
                detail += f"\n{tail}"
            raise HTTPException(status_code=400, detail=detail)

    if not output_host_path.exists():
        raise HTTPException(status_code=500, detail=f"preview output not found: {output_host_path}")

    try:
        preview_payload = read_json(output_host_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to parse preview output: {exc}") from exc

    if not isinstance(preview_payload, dict):
        raise HTTPException(status_code=500, detail="invalid preview output payload")

    return PairProfilePreviewResponse(
        requested_pair=str(preview_payload.get("requested_pair", payload.pair)),
        resolved_pair=str(preview_payload.get("resolved_pair", payload.pair)),
        pair_candidates=list(preview_payload.get("pair_candidates", []) or []),
        matched_pair_key=(
            str(preview_payload.get("matched_pair_key"))
            if preview_payload.get("matched_pair_key") is not None
            else None
        ),
        timeframe=str(preview_payload.get("timeframe", payload.timeframe)),
        timerange=str(preview_payload.get("timerange", payload.timerange)),
        effective_attrs=preview_payload.get("effective_attrs", {}) or {},
        pair_params=preview_payload.get("pair_params", {}) or {},
        zones=preview_payload.get("zones", []) or [],
        meta=preview_payload.get("meta", {}) or {},
        series=preview_payload.get("series", {}) or {},
    )
