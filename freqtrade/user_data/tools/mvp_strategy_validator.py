from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd


def timeframe_to_pandas(timeframe: str) -> str:
    if timeframe.endswith("m"):
        return timeframe.replace("m", "min")
    if timeframe.endswith("h"):
        return timeframe.replace("h", "H")
    if timeframe.endswith("d"):
        return timeframe.replace("d", "D")
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def pair_to_symbol(pair: str) -> str:
    return pair.replace("/", "_").replace(":", "_")


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
        raise RuntimeError(f"Resampled dataframe is empty for timeframe={timeframe}")
    return rs


def load_strategy(strategy_path: Path):
    spec = importlib.util.spec_from_file_location("generated_strategy_module", strategy_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    strategy_cls = None
    for name in dir(module):
        candidate = getattr(module, name)
        if isinstance(candidate, type) and all(
            hasattr(candidate, method_name)
            for method_name in ("populate_indicators", "populate_entry_trend", "populate_exit_trend")
        ):
            strategy_cls = candidate
            break

    if strategy_cls is None:
        raise RuntimeError(f"No valid strategy class found in {strategy_path}")
    strategy = strategy_cls({"stake_amount": "unlimited"})

    if not hasattr(strategy, "wallets"):
        strategy.wallets = SimpleNamespace(get_trade_stake_amount=lambda *_args, **_kwargs: 100.0)
    return strategy


def _call_with_supported_kwargs(func, candidate_kwargs: dict[str, Any]):
    signature = inspect.signature(func)
    accepts_var_kw = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    if accepts_var_kw:
        return func(**candidate_kwargs)

    allowed = {name for name, param in signature.parameters.items() if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
    filtered = {key: value for key, value in candidate_kwargs.items() if key in allowed}
    return func(**filtered)


def validate_strategy_runtime(strategy, dataframe: pd.DataFrame, pair: str) -> None:
    df = dataframe.copy().reset_index(drop=True)
    df = strategy.populate_indicators(df, {"pair": pair})
    df = strategy.populate_entry_trend(df, {"pair": pair})
    df = strategy.populate_exit_trend(df, {"pair": pair})

    for col in ("enter_long", "enter_short", "exit_long", "exit_short"):
        if col not in df.columns:
            raise RuntimeError(f"Missing required column after strategy methods: {col}")

    if df.empty:
        raise RuntimeError("Strategy returned empty dataframe")
    row = df.iloc[-1]
    now = datetime.now(timezone.utc)
    current_rate = float(row["close"])

    if hasattr(strategy, "custom_stake_amount"):
        _call_with_supported_kwargs(
            strategy.custom_stake_amount,
            {
                "pair": pair,
                "current_time": now,
                "current_rate": current_rate,
                "proposed_stake": 100.0,
                "min_stake": 10.0,
                "max_stake": 1000.0,
                "leverage": 1.0,
                "entry_tag": "validate",
                "side": "long",
            },
        )

    if hasattr(strategy, "adjust_trade_position"):
        dummy_trade = SimpleNamespace(
            pair=pair,
            stake_amount=100.0,
            nr_of_successful_entries=1,
            nr_of_successful_exits=0,
            amount=50.0,
        )
        _call_with_supported_kwargs(
            strategy.adjust_trade_position,
            {
                "trade": dummy_trade,
                "current_time": now,
                "current_rate": current_rate,
                "current_profit": 0.01,
                "min_stake": 10.0,
                "max_stake": 1000.0,
                "current_entry_rate": current_rate,
                "current_exit_rate": current_rate,
                "current_entry_profit": 0.01,
                "current_exit_profit": 0.01,
                "current_liquidation_rate": 0.0,
                "leverage": 1.0,
                "entry_tag": "validate",
                "side": "long",
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated strategy runtime in freqtrade env.")
    parser.add_argument("--strategy", required=True, help="Strategy file path inside container.")
    parser.add_argument("--pair", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--timerange", required=True)
    args = parser.parse_args()

    strategy_path = Path(args.strategy)
    print(f"[mvp-validate] loading strategy: {strategy_path}")
    print(f"[mvp-validate] loading ohlcv: pair={args.pair} timeframe={args.timeframe} range={args.timerange}")

    try:
        strategy = load_strategy(strategy_path)
        df = load_ohlcv(args.pair, args.timeframe, args.timerange)
        sample = df.tail(1200).reset_index(drop=True)
        print(f"[mvp-validate] dataframe rows: {len(sample)}")
        validate_strategy_runtime(strategy, sample, args.pair)
        print(json.dumps({"ok": True, "rows": len(sample)}))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(traceback.format_exc())
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
