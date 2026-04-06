from __future__ import annotations

import argparse
import importlib.util
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


FEE_RATE = 0.0005
DEFAULT_STARTING_BALANCE = 150.0
DEFAULT_TRADABLE_RATIO = 0.75
MAX_SERIES_POINTS = 4000
INDICATOR_COLOR_PALETTE = [
    "#22d3ee",
    "#f59e0b",
    "#a78bfa",
    "#34d399",
    "#fb7185",
    "#60a5fa",
]
UNSUITABLE_OVERLAY_TOKENS = (
    "rsi",
    "macd",
    "stoch",
    "cci",
    "adx",
    "mfi",
    "roc",
    "mom",
    "willr",
    "ao",
    "ppo",
    "uo",
    "trix",
    "obv",
    "volume",
)


@dataclass
class Position:
    side: str
    open_time: pd.Timestamp
    open_index: int
    qty: float
    entry_price: float


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


def _to_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _extract_wallet_from_config(payload: dict[str, Any]) -> float:
    wallet = payload.get("dry_run_wallet")
    if isinstance(wallet, (int, float, str)):
        return max(_to_float(wallet, DEFAULT_STARTING_BALANCE), 0.0)

    if isinstance(wallet, dict):
        for key in ("USDT", "usdt"):
            if key in wallet:
                return max(_to_float(wallet.get(key), DEFAULT_STARTING_BALANCE), 0.0)
        for value in wallet.values():
            if isinstance(value, (int, float, str)):
                parsed = _to_float(value, DEFAULT_STARTING_BALANCE)
                if parsed > 0:
                    return parsed

    return DEFAULT_STARTING_BALANCE


def load_capital_config(config_path: Path = Path("/freqtrade/user_data/config.json")) -> tuple[float, float]:
    if not config_path.exists():
        return DEFAULT_STARTING_BALANCE, DEFAULT_TRADABLE_RATIO

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return DEFAULT_STARTING_BALANCE, DEFAULT_TRADABLE_RATIO

    wallet = _extract_wallet_from_config(payload)
    if wallet <= 0:
        wallet = DEFAULT_STARTING_BALANCE
    ratio = _to_float(payload.get("tradable_balance_ratio"), DEFAULT_TRADABLE_RATIO)
    ratio = min(max(ratio, 0.01), 1.0)
    return wallet, ratio


def _is_unsuitable_overlay_indicator(name: str) -> bool:
    key = name.lower()
    return any(token in key for token in UNSUITABLE_OVERLAY_TOKENS)


def extract_indicator_lines(
    df: pd.DataFrame,
    allowed_columns: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "enter_long",
        "enter_short",
        "exit_long",
        "exit_short",
    }
    close_median = abs(float(pd.to_numeric(df["close"], errors="coerce").median())) if "close" in df.columns else 0.0
    timestamps = (pd.to_datetime(df["date"], utc=True).astype("int64") // 10**9).astype(int)

    output: list[dict[str, Any]] = []
    for col in df.columns:
        if allowed_columns is not None and col not in allowed_columns:
            continue
        if col in excluded:
            continue
        if _is_unsuitable_overlay_indicator(col):
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        valid = series.dropna()
        if valid.empty:
            continue
        if valid.nunique() <= 3:
            continue
        if len(valid) / max(len(series), 1) < 0.35:
            continue

        median_abs = abs(float(valid.median()))
        if close_median > 0:
            ratio = median_abs / close_median
            # Overlay only price-like indicators to avoid distorting the K chart scale.
            if ratio < 0.05 or ratio > 20:
                continue

        points: list[dict[str, Any]] = []
        for i in range(len(series)):
            value = series.iat[i]
            if pd.isna(value):
                continue
            f_value = float(value)
            if not math.isfinite(f_value):
                continue
            points.append({"time": int(timestamps.iat[i]), "value": round(f_value, 6)})
        if len(points) < 2:
            continue
        output.append(
            {
                "name": col,
                "color": INDICATOR_COLOR_PALETTE[len(output) % len(INDICATOR_COLOR_PALETTE)],
                "points": _downsample(points),
            }
        )
    return output


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
    return strategy_cls({"stake_amount": "unlimited"})


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
        raise RuntimeError(
            f"Resampled dataframe is empty for timeframe={timeframe} from 1m source in {timerange}"
        )
    return rs


def _downsample(items: list[dict[str, Any]], max_points: int = MAX_SERIES_POINTS) -> list[dict[str, Any]]:
    if len(items) <= max_points:
        return items
    step = math.ceil(len(items) / max_points)
    return items[::step]


def simulate(
    strategy,
    dataframe: pd.DataFrame,
    pair: str,
    starting_balance: float,
    tradable_ratio: float,
) -> dict[str, Any]:
    df = strategy.populate_indicators(dataframe.copy(), {"pair": pair})
    indicator_columns = set(df.columns)
    df = strategy.populate_entry_trend(df, {"pair": pair})
    df = strategy.populate_exit_trend(df, {"pair": pair})

    for col in ("enter_long", "enter_short", "exit_long", "exit_short"):
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(0)

    cash = starting_balance
    position: Position | None = None
    trades: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    equity_points: list[dict[str, Any]] = []
    drawdown_points: list[dict[str, Any]] = []
    peak_equity = starting_balance

    for idx in range(1, len(df)):
        row = df.iloc[idx]
        timestamp = pd.Timestamp(row["date"])
        price = float(row["close"])
        unix_time = int(timestamp.timestamp())

        enter_long = bool(row.get("enter_long", 0))
        enter_short = bool(row.get("enter_short", 0))
        exit_long = bool(row.get("exit_long", 0))
        exit_short = bool(row.get("exit_short", 0))

        if position is None:
            if enter_long ^ enter_short:
                side = "long" if enter_long else "short"
                stake = cash * tradable_ratio
                if stake <= 0:
                    continue
                qty = stake / price
                entry_fee = stake * FEE_RATE
                cash -= entry_fee
                position = Position(
                    side=side,
                    open_time=timestamp,
                    open_index=idx,
                    qty=qty,
                    entry_price=price,
                )
                markers.append(
                    {
                        "time": unix_time,
                        "position": "belowBar" if side == "long" else "aboveBar",
                        "color": "#16a34a" if side == "long" else "#ef4444",
                        "shape": "arrowUp" if side == "long" else "arrowDown",
                        "text": f"Entry {side}",
                    }
                )
        else:
            should_close = False
            close_reason = "signal"
            if position.side == "long" and (exit_long or enter_short):
                should_close = True
            if position.side == "short" and (exit_short or enter_long):
                should_close = True

            if should_close:
                gross = (
                    (price - position.entry_price) * position.qty
                    if position.side == "long"
                    else (position.entry_price - price) * position.qty
                )
                exit_fee = (position.qty * price) * FEE_RATE
                pnl = gross - exit_fee
                cash += pnl
                trades.append(
                    {
                        "side": position.side,
                        "open_time": position.open_time.isoformat(),
                        "close_time": timestamp.isoformat(),
                        "entry_price": position.entry_price,
                        "exit_price": price,
                        "profit_abs": pnl,
                        "profit_pct": (pnl / starting_balance) * 100.0,
                        "duration": idx - position.open_index,
                        "reason": close_reason,
                    }
                )
                markers.append(
                    {
                        "time": unix_time,
                        "position": "aboveBar" if position.side == "long" else "belowBar",
                        "color": "#eab308",
                        "shape": "circle",
                        "text": f"Exit {position.side}",
                    }
                )
                position = None

        unrealized = 0.0
        if position is not None:
            if position.side == "long":
                unrealized = (price - position.entry_price) * position.qty
            else:
                unrealized = (position.entry_price - price) * position.qty

        equity = cash + unrealized
        peak_equity = max(peak_equity, equity)
        drawdown = 0.0 if peak_equity <= 0 else ((peak_equity - equity) / peak_equity) * 100.0

        equity_points.append({"time": unix_time, "value": round(equity, 4)})
        drawdown_points.append({"time": unix_time, "value": round(drawdown, 4)})

    if position is not None:
        last = df.iloc[-1]
        timestamp = pd.Timestamp(last["date"])
        price = float(last["close"])
        gross = (
            (price - position.entry_price) * position.qty
            if position.side == "long"
            else (position.entry_price - price) * position.qty
        )
        exit_fee = (position.qty * price) * FEE_RATE
        pnl = gross - exit_fee
        cash += pnl
        trades.append(
            {
                "side": position.side,
                "open_time": position.open_time.isoformat(),
                "close_time": timestamp.isoformat(),
                "entry_price": position.entry_price,
                "exit_price": price,
                "profit_abs": pnl,
                "profit_pct": (pnl / starting_balance) * 100.0,
                "duration": len(df) - 1 - position.open_index,
                "reason": "force_close",
            }
        )

    wins = sum(1 for trade in trades if trade["profit_abs"] > 0)
    gross_profit = sum(trade["profit_abs"] for trade in trades if trade["profit_abs"] > 0)
    gross_loss = sum(trade["profit_abs"] for trade in trades if trade["profit_abs"] < 0)
    end_equity = equity_points[-1]["value"] if equity_points else starting_balance
    max_drawdown_pct = max((point["value"] for point in drawdown_points), default=0.0)

    start_close = float(df.iloc[0]["close"])
    end_close = float(df.iloc[-1]["close"])

    kline = [
        {
            "time": int(pd.Timestamp(r["date"]).timestamp()),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        }
        for _, r in df.iterrows()
    ]

    summary = {
        "trades": len(trades),
        "winrate": round((wins / len(trades)) * 100.0, 2) if trades else 0.0,
        "profit_total_pct": round(((end_equity - starting_balance) / starting_balance) * 100.0, 3),
        "profit_total_abs": round(end_equity - starting_balance, 3),
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "profit_factor": round(gross_profit / abs(gross_loss), 3) if gross_loss < 0 else None,
        "market_change_pct": round(((end_close / start_close) - 1.0) * 100.0, 3),
        "starting_balance": round(starting_balance, 3),
        "tradable_balance_ratio": round(tradable_ratio, 4),
    }
    indicator_lines = extract_indicator_lines(df, allowed_columns=indicator_columns)
    series = {
        "kline": _downsample(kline),
        "markers": _downsample(markers, max_points=1200),
        "equity": _downsample(equity_points),
        "drawdown": _downsample(drawdown_points),
        "indicators": indicator_lines,
    }
    return {"summary": summary, "series": series, "trades": trades[:400]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--pair", required=True)
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--timerange", required=True, help="YYYYMMDD-YYYYMMDD")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    strategy_path = Path(args.strategy)
    output_path = Path(args.output)

    print(f"[mvp-backtest] loading strategy: {strategy_path}")
    strategy = load_strategy(strategy_path)
    print(f"[mvp-backtest] loading ohlcv: pair={args.pair} timeframe={args.timeframe} range={args.timerange}")
    df = load_ohlcv(pair=args.pair, timeframe=args.timeframe, timerange=args.timerange)
    print(f"[mvp-backtest] dataframe rows: {len(df)}")
    starting_balance, tradable_ratio = load_capital_config()
    print(
        "[mvp-backtest] capital config: "
        f"dry_run_wallet={starting_balance} tradable_balance_ratio={tradable_ratio} "
        f"max_trade_notional={round(starting_balance * tradable_ratio, 4)}"
    )

    result = simulate(strategy, df, args.pair, starting_balance=starting_balance, tradable_ratio=tradable_ratio)
    result["artifacts"] = {
        "strategy_file": args.strategy,
        "output_file": args.output,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"[mvp-backtest] result written: {output_path}")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
