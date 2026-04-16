from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd


MAX_SERIES_POINTS = 3200

INDICATOR_COLORS = {
    "ema_line": "#f5f1c5",
    "fast_ma": "#4aa3ff",
    "slow_ma": "#f39c12",
    "zone1_top": "#27ae60",
    "zone1_bottom": "#27ae60",
    "zone2_top": "#58d68d",
    "zone2_bottom": "#58d68d",
    "zone3_top": "#e74c3c",
    "zone3_bottom": "#e74c3c",
    "zone4_top": "#922b21",
    "zone4_bottom": "#922b21",
}

OVERLAY_COLUMNS = [
    "ema_line",
    "fast_ma",
    "slow_ma",
    "zone1_top",
    "zone1_bottom",
    "zone2_top",
    "zone2_bottom",
    "zone3_top",
    "zone3_bottom",
    "zone4_top",
    "zone4_bottom",
]


def timeframe_to_pandas(timeframe: str) -> str:
    if timeframe.endswith("m"):
        return timeframe.replace("m", "min")
    if timeframe.endswith("h"):
        return timeframe.replace("h", "H")
    if timeframe.endswith("d"):
        return timeframe.replace("d", "D")
    if timeframe.endswith("w"):
        return timeframe.replace("w", "W")
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def pair_to_symbol(pair: str) -> str:
    return pair.replace("/", "_").replace(":", "_")


def symbol_to_pair(symbol: str) -> str | None:
    parts = [token for token in symbol.split("_") if token]
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}:{parts[2]}"
    return None


def parse_timerange(timerange: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_raw, end_raw = timerange.split("-")
    start = pd.Timestamp(start_raw, tz="UTC")
    end = pd.Timestamp(end_raw, tz="UTC") + pd.Timedelta(days=1)
    return start, end


def _data_file_candidates(pair: str, timeframe: str) -> list[Path]:
    symbol = pair_to_symbol(pair)
    base = Path("/freqtrade/user_data/data/binance")
    if ":" in pair:
        return [
            base / "futures" / f"{symbol}-{timeframe}-futures.feather",
            base / "futures" / f"{symbol}-{timeframe}.feather",
        ]
    return [
        base / "spot" / f"{symbol}-{timeframe}.feather",
        base / f"{symbol}-{timeframe}.feather",
    ]


def _read_timeframe_data(pair: str, timeframe: str) -> pd.DataFrame:
    checked: list[str] = []
    for path in _data_file_candidates(pair, timeframe):
        checked.append(str(path))
        if not path.exists():
            continue
        df = pd.read_feather(path)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        return df[["date", "open", "high", "low", "close", "volume"]]
    raise FileNotFoundError(
        f"Data file not found for pair={pair} timeframe={timeframe}. Checked: {checked}"
    )


def _slice_timerange(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, timerange: str, timeframe: str) -> pd.DataFrame:
    sample = df[(df["date"] >= start) & (df["date"] < end)].copy()
    if sample.empty:
        data_start = pd.Timestamp(df["date"].min()).isoformat() if not df.empty else "n/a"
        data_end = pd.Timestamp(df["date"].max()).isoformat() if not df.empty else "n/a"
        raise RuntimeError(
            f"No data in timerange {timerange} for timeframe={timeframe}. "
            f"Available range: {data_start} -> {data_end}"
        )
    return sample


def _read_1m_data(pair: str) -> pd.DataFrame:
    df = _read_timeframe_data(pair, "1m")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


def resolve_pair_for_data(pair: str, timeframe: str) -> str:
    clean = str(pair).strip().upper()
    if "/" in clean:
        return clean

    base = Path("/freqtrade/user_data/data/binance")
    found: list[Path] = []
    for folder in (base / "futures", base / "spot", base):
        if not folder.exists():
            continue
        found.extend(sorted(folder.glob(f"{clean}_*-{timeframe}*.feather")))

    if not found:
        return clean

    picked = found[0]
    stem = picked.stem
    suffix = f"-{timeframe}-futures"
    if stem.endswith(suffix):
        symbol = stem[: -len(suffix)]
    else:
        suffix = f"-{timeframe}"
        if stem.endswith(suffix):
            symbol = stem[: -len(suffix)]
        else:
            symbol = stem

    resolved = symbol_to_pair(symbol)
    return resolved or clean


def load_ohlcv(pair: str, timeframe: str, timerange: str) -> pd.DataFrame:
    start, end = parse_timerange(timerange)
    if timeframe == "1m":
        base_1m = _read_1m_data(pair)
        sample_1m = _slice_timerange(base_1m, start, end, timerange, "1m")
        return sample_1m.reset_index(drop=True)

    try:
        direct = _read_timeframe_data(pair, timeframe)
        direct_sample = _slice_timerange(direct, start, end, timerange, timeframe)
        return direct_sample.reset_index(drop=True)
    except FileNotFoundError:
        pass

    base = _read_1m_data(pair)
    sample = _slice_timerange(base, start, end, timerange, "1m")
    rule = timeframe_to_pandas(timeframe)
    rs = (
        sample.set_index("date")
        .resample(rule, label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
        .reset_index()
    )
    if rs.empty:
        raise RuntimeError(
            f"Resampled dataframe is empty for timeframe={timeframe} from 1m source in {timerange}"
        )
    return rs


def _downsample(items: list[dict[str, Any]], max_points: int = MAX_SERIES_POINTS) -> list[dict[str, Any]]:
    if len(items) <= max_points:
        return items
    step = math.ceil(len(items) / max_points)
    return items[::step]


def _to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_builtin(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return [_to_builtin(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def load_strategy(strategy_path: Path):
    strategy_dir = strategy_path.parent
    if str(strategy_dir) not in sys.path:
        sys.path.insert(0, str(strategy_dir))

    spec = importlib.util.spec_from_file_location("tv_zone_strategy_preview_module", strategy_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    strategy_cls = None
    module_name = module.__name__
    for name in dir(module):
        candidate = getattr(module, name)
        if (
            isinstance(candidate, type)
            and getattr(candidate, "__module__", "") == module_name
            and not inspect.isabstract(candidate)
            and all(
                hasattr(candidate, method_name)
                for method_name in ("populate_indicators", "populate_entry_trend", "populate_exit_trend")
            )
        ):
            strategy_cls = candidate
            break

    if strategy_cls is None:
        raise RuntimeError(f"No valid strategy class found in {strategy_path}")
    return strategy_cls({"stake_amount": "unlimited"})


def _display_name(column: str, pair_params: dict[str, Any]) -> str:
    if column == "ema_line":
        return f"EMA_LONG({int(float(pair_params.get('ema_length', 0) or 0))})"
    if column == "fast_ma":
        return f"EMA_FAST({int(float(pair_params.get('fast_len', 0) or 0))})"
    if column == "slow_ma":
        return f"EMA_SLOW({int(float(pair_params.get('slow_len', 0) or 0))})"
    if column.startswith("zone") and (column.endswith("_top") or column.endswith("_bottom")):
        zone_id = column[4]
        side = "TOP" if column.endswith("_top") else "BOTTOM"
        return f"ZONE{zone_id}_{side}"
    return column


def _indicator_lines(
    df: pd.DataFrame,
    timestamps: pd.Series,
    max_points: int,
    pair_params: dict[str, Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for column in OVERLAY_COLUMNS:
        if column not in df.columns:
            continue

        series = pd.to_numeric(df[column], errors="coerce")
        points: list[dict[str, Any]] = []
        for idx, value in enumerate(series):
            if pd.isna(value):
                continue
            points.append(
                {
                    "time": int(timestamps.iat[idx]),
                    "value": round(float(value), 8),
                }
            )
        if len(points) < 2:
            continue
        output.append(
            {
                "name": _display_name(column, pair_params),
                "color": INDICATOR_COLORS.get(column, "#60a5fa"),
                "points": _downsample(points, max_points=max_points),
            }
        )
    return output


def _signal_markers(df: pd.DataFrame, timestamps: pd.Series, max_points: int) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []

    def _as_bool(raw: Any) -> bool:
        if raw is None:
            return False
        try:
            return bool(float(raw) > 0)
        except Exception:  # noqa: BLE001
            return bool(raw)

    for idx in range(len(df)):
        row = df.iloc[idx]
        ts = int(timestamps.iat[idx])

        if _as_bool(row.get("enter_long")):
            markers.append(
                {
                    "time": ts,
                    "position": "belowBar",
                    "color": "#22c55e",
                    "shape": "arrowUp",
                    "text": "enter long",
                }
            )
        if _as_bool(row.get("enter_short")):
            markers.append(
                {
                    "time": ts,
                    "position": "aboveBar",
                    "color": "#ef4444",
                    "shape": "arrowDown",
                    "text": "enter short",
                }
            )
        if _as_bool(row.get("exit_long")):
            markers.append(
                {
                    "time": ts,
                    "position": "aboveBar",
                    "color": "#f59e0b",
                    "shape": "circle",
                    "text": "exit long",
                }
            )
        if _as_bool(row.get("exit_short")):
            markers.append(
                {
                    "time": ts,
                    "position": "belowBar",
                    "color": "#f59e0b",
                    "shape": "circle",
                    "text": "exit short",
                }
            )

    return _downsample(markers, max_points=max_points)


def _pair_candidates(pair: str) -> list[str]:
    raw = str(pair).strip().upper()
    if not raw:
        return []
    if "/" not in raw:
        return [raw]
    base_quote, *rest = raw.split(":", 1)
    normalized = f"{base_quote}:{rest[0].upper()}" if rest else base_quote
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


def build_payload(
    strategy,
    requested_pair: str,
    resolved_pair: str,
    timeframe: str,
    timerange: str,
    df: pd.DataFrame,
    max_points: int,
) -> dict[str, Any]:
    metadata = {"pair": resolved_pair}
    ind = strategy.populate_indicators(df.copy(), metadata)
    ind = strategy.populate_entry_trend(ind, metadata)
    ind = strategy.populate_exit_trend(ind, metadata)

    timestamps = (pd.to_datetime(ind["date"], utc=True).astype("int64") // 10**9).astype(int)
    kline = [
        {
            "time": int(timestamps.iat[i]),
            "open": float(ind.iloc[i]["open"]),
            "high": float(ind.iloc[i]["high"]),
            "low": float(ind.iloc[i]["low"]),
            "close": float(ind.iloc[i]["close"]),
        }
        for i in range(len(ind))
    ]

    pair_params: dict[str, Any] = {}
    if hasattr(strategy, "_resolve_pair_params"):
        try:
            pair_params = dict(strategy._resolve_pair_params(metadata))  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pair_params = {}
    indicators = _indicator_lines(ind, timestamps, max_points=max_points, pair_params=pair_params)
    markers = _signal_markers(ind, timestamps, max_points=max_points)

    matched_key = None
    effective_attrs: dict[str, Any] = {}
    try:
        from pair_profile_helper import get_pair_attrs

        attrs, matched = get_pair_attrs(resolved_pair)
        if isinstance(attrs, dict):
            effective_attrs = attrs
        if isinstance(matched, str):
            matched_key = matched
    except Exception:  # noqa: BLE001
        pass

    zones: list[dict[str, Any]] = []
    for idx in range(1, 5):
        base_key = f"zone{idx}_base"
        width_key = f"zone{idx}_width"
        base = float(pair_params.get(base_key, 0.0))
        width = float(pair_params.get(width_key, 0.0))
        zones.append(
            {
                "name": f"zone{idx}",
                "base": base,
                "width": width,
                "top": base + width,
                "bottom": base - width,
            }
        )

    return {
        "requested_pair": requested_pair,
        "resolved_pair": resolved_pair,
        "pair_candidates": _pair_candidates(resolved_pair),
        "matched_pair_key": matched_key,
        "timeframe": timeframe,
        "timerange": timerange,
        "effective_attrs": _to_builtin(effective_attrs),
        "pair_params": _to_builtin(pair_params),
        "zones": _to_builtin(zones),
        "meta": {
            "rows": int(len(ind)),
            "data_start": pd.Timestamp(ind["date"].iloc[0]).isoformat() if len(ind) > 0 else None,
            "data_end": pd.Timestamp(ind["date"].iloc[-1]).isoformat() if len(ind) > 0 else None,
        },
        "series": {
            "kline": _downsample(kline, max_points=max_points),
            "markers": markers,
            "indicators": indicators,
        },
    }


def _is_valid_timeframe(value: str) -> bool:
    return bool(re.fullmatch(r"\d+[mhdw]", value.strip().lower()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", required=True)
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--timerange", default="20251220-20260306")
    parser.add_argument("--strategy", default="/freqtrade/user_data/strategies/TradingViewZoneStrategy.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-points", type=int, default=1800)
    args = parser.parse_args()

    timeframe = str(args.timeframe).strip().lower()
    if not _is_valid_timeframe(timeframe):
        raise SystemExit(f"Invalid timeframe: {args.timeframe}")

    max_points = int(max(400, min(6000, int(args.max_points))))
    requested_pair = str(args.pair).strip().upper()
    resolved_pair = resolve_pair_for_data(requested_pair, timeframe)

    strategy_path = Path(args.strategy)
    output_path = Path(args.output)

    strategy = load_strategy(strategy_path)
    ohlcv = load_ohlcv(pair=resolved_pair, timeframe=timeframe, timerange=args.timerange)
    payload = build_payload(
        strategy=strategy,
        requested_pair=requested_pair,
        resolved_pair=resolved_pair,
        timeframe=timeframe,
        timerange=args.timerange,
        df=ohlcv,
        max_points=max_points,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "pair": resolved_pair, "rows": payload["meta"]["rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
