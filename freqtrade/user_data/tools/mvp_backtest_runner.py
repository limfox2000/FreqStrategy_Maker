from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import subprocess
import zipfile
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


def extract_indicator_lines(df: pd.DataFrame, allowed_columns: set[str] | None = None) -> list[dict[str, Any]]:
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
        raise RuntimeError(f"Resampled dataframe is empty for timeframe={timeframe} from 1m source in {timerange}")
    return rs


def _downsample(items: list[dict[str, Any]], max_points: int = MAX_SERIES_POINTS) -> list[dict[str, Any]]:
    if len(items) <= max_points:
        return items
    step = math.ceil(len(items) / max_points)
    return items[::step]


def _extract_strategy_name(strategy_file: Path) -> str:
    text = strategy_file.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*IStrategy\s*\)", text)
    if m:
        return m.group(1)
    return strategy_file.stem


def _is_non_strategy_error(lines: list[str]) -> bool:
    text = "\n".join(lines)
    tokens = (
        "Could not load markets",
        "ExchangeNotAvailable",
        "Cannot connect to host",
        "TemporaryError",
        "download-data",
    )
    return any(token in text for token in tokens)


def _run_freqtrade_backtesting(
    strategy_file: Path,
    pair: str,
    timeframe: str,
    timerange: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    strategy_name = _extract_strategy_name(strategy_file)
    result_dir = Path("/freqtrade/user_data/backtest_results/mvp_native")
    result_dir.mkdir(parents=True, exist_ok=True)

    command = [
        "freqtrade",
        "backtesting",
        "--config",
        "/freqtrade/user_data/config.json",
        "--strategy-path",
        str(strategy_file.parent),
        "--strategy",
        strategy_name,
        "--pairs",
        pair,
        "--timeframe",
        timeframe,
        "--timerange",
        timerange,
        "--datadir",
        "/freqtrade/user_data/data/binance",
        "--export",
        "trades",
        "--cache",
        "none",
        "--backtest-directory",
        str(result_dir),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    stdout, _ = process.communicate(timeout=1800)
    lines = (stdout or "").splitlines()
    for line in lines:
        print(line)

    if process.returncode != 0:
        tail = "\n".join([line for line in lines if line.strip()][-40:])
        if _is_non_strategy_error(lines):
            raise RuntimeError(f"[mvp-backtest][non-strategy] freqtrade backtesting failed\n{tail}")
        raise RuntimeError(f"freqtrade backtesting exited with code {process.returncode}\n{tail}")

    latest_ref = result_dir / ".last_result.json"
    latest_name: str | None = None
    if latest_ref.exists():
        latest_obj = json.loads(latest_ref.read_text(encoding="utf-8-sig"))
        latest_name = str(latest_obj.get("latest_backtest") or "").strip() or None

    if latest_name:
        candidate = result_dir / latest_name
    else:
        zips = sorted(result_dir.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not zips:
            raise RuntimeError("Backtest completed but result archive not found")
        candidate = zips[0]

    if not candidate.exists():
        raise RuntimeError(f"Backtest result file not found: {candidate}")

    if candidate.suffix == ".zip":
        with zipfile.ZipFile(candidate, "r") as zf:
            json_members = [
                name
                for name in zf.namelist()
                if name.endswith(".json")
                and not name.endswith("_config.json")
                and "meta" not in name
            ]
            if not json_members:
                raise RuntimeError(f"No result JSON in archive: {candidate}")
            with zf.open(json_members[0]) as fp:
                payload = json.load(fp)
    else:
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))

    strategy_map = payload.get("strategy", {})
    if not isinstance(strategy_map, dict) or not strategy_map:
        raise RuntimeError("Invalid backtest payload: missing strategy results")
    strategy_result = strategy_map.get(strategy_name)
    if not isinstance(strategy_result, dict):
        strategy_result = next(iter(strategy_map.values()))
    if not isinstance(strategy_result, dict):
        raise RuntimeError("Invalid backtest payload: invalid strategy section")

    trades = strategy_result.get("trades", [])
    if not isinstance(trades, list):
        trades = []

    return strategy_result, trades, strategy_name


def _build_series_and_summary(
    strategy,
    ohlcv: pd.DataFrame,
    trades: list[dict[str, Any]],
    strategy_result: dict[str, Any],
    pair: str,
    starting_balance_default: float,
    tradable_ratio: float,
) -> dict[str, Any]:
    df = strategy.populate_indicators(ohlcv.copy(), {"pair": pair})
    indicator_columns = set(df.columns)

    timestamps = (pd.to_datetime(ohlcv["date"], utc=True).astype("int64") // 10**9).astype(int)
    kline = [
        {
            "time": int(timestamps.iat[i]),
            "open": float(ohlcv.iloc[i]["open"]),
            "high": float(ohlcv.iloc[i]["high"]),
            "low": float(ohlcv.iloc[i]["low"]),
            "close": float(ohlcv.iloc[i]["close"]),
        }
        for i in range(len(ohlcv))
    ]

    markers: list[dict[str, Any]] = []
    close_profit_by_ts: dict[int, float] = {}
    position_adjustments = 0

    for trade in trades:
        open_ts = int(_to_float(trade.get("open_timestamp"), 0.0) / 1000)
        close_ts = int(_to_float(trade.get("close_timestamp"), 0.0) / 1000)
        is_short = bool(trade.get("is_short", False))
        side = "short" if is_short else "long"

        if open_ts > 0:
            markers.append(
                {
                    "time": open_ts,
                    "position": "aboveBar" if is_short else "belowBar",
                    "color": "#ef4444" if is_short else "#16a34a",
                    "shape": "arrowDown" if is_short else "arrowUp",
                    "text": f"Entry {side}",
                }
            )

        if close_ts > 0:
            markers.append(
                {
                    "time": close_ts,
                    "position": "belowBar" if is_short else "aboveBar",
                    "color": "#eab308",
                    "shape": "circle",
                    "text": f"Exit {side}",
                }
            )

        profit_abs = _to_float(trade.get("profit_abs"), 0.0)
        if close_ts > 0:
            close_profit_by_ts[close_ts] = close_profit_by_ts.get(close_ts, 0.0) + profit_abs

        orders = trade.get("orders", [])
        if isinstance(orders, list) and orders:
            entry_count = sum(1 for o in orders if bool(o.get("ft_is_entry", False)))
            exit_count = sum(1 for o in orders if not bool(o.get("ft_is_entry", False)))
            position_adjustments += max(0, entry_count - 1) + max(0, exit_count - 1)

    starting_balance = _to_float(strategy_result.get("starting_balance"), starting_balance_default)
    equity_points: list[dict[str, Any]] = []
    drawdown_points: list[dict[str, Any]] = []
    equity = starting_balance
    peak = starting_balance

    for ts in timestamps:
        equity += close_profit_by_ts.get(int(ts), 0.0)
        peak = max(peak, equity)
        drawdown = 0.0 if peak <= 0 else ((peak - equity) / peak) * 100.0
        equity_points.append({"time": int(ts), "value": round(equity, 4)})
        drawdown_points.append({"time": int(ts), "value": round(drawdown, 4)})

    total_trades = int(strategy_result.get("total_trades", len(trades)))
    winrate_raw = _to_float(strategy_result.get("winrate"), 0.0)
    winrate_pct = winrate_raw * 100.0 if winrate_raw <= 1.0 else winrate_raw

    profit_total = _to_float(strategy_result.get("profit_total"), 0.0)
    market_change = _to_float(strategy_result.get("market_change"), 0.0)
    max_drawdown_ratio = _to_float(strategy_result.get("max_drawdown_account"), 0.0)

    summary = {
        "trades": total_trades,
        "winrate": round(winrate_pct, 2),
        "profit_total_pct": round(profit_total * 100.0, 3),
        "profit_total_abs": round(_to_float(strategy_result.get("profit_total_abs"), 0.0), 3),
        "max_drawdown_pct": round(max_drawdown_ratio * 100.0, 3),
        "profit_factor": strategy_result.get("profit_factor"),
        "market_change_pct": round(market_change * 100.0, 3),
        "starting_balance": round(starting_balance, 3),
        "tradable_balance_ratio": round(tradable_ratio, 4),
        "position_adjustments": int(position_adjustments),
    }

    indicator_lines = extract_indicator_lines(df, allowed_columns=indicator_columns)
    series = {
        "kline": _downsample(kline),
        "markers": _downsample(markers, max_points=1200),
        "equity": _downsample(equity_points),
        "drawdown": _downsample(drawdown_points),
        "indicators": indicator_lines,
    }

    return {
        "summary": summary,
        "series": series,
        "trades": trades[:400],
    }


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
    ohlcv = load_ohlcv(pair=args.pair, timeframe=args.timeframe, timerange=args.timerange)
    print(f"[mvp-backtest] dataframe rows: {len(ohlcv)}")

    starting_balance, tradable_ratio = load_capital_config()
    print(
        "[mvp-backtest] capital config: "
        f"dry_run_wallet={starting_balance} tradable_balance_ratio={tradable_ratio} "
        f"max_trade_notional={round(starting_balance * tradable_ratio, 4)}"
    )

    strategy_result, trades, strategy_name = _run_freqtrade_backtesting(
        strategy_file=strategy_path,
        pair=args.pair,
        timeframe=args.timeframe,
        timerange=args.timerange,
    )
    print(
        f"[mvp-backtest] freqtrade result loaded: strategy={strategy_name} "
        f"trades={len(trades)}"
    )

    result = _build_series_and_summary(
        strategy=strategy,
        ohlcv=ohlcv,
        trades=trades,
        strategy_result=strategy_result,
        pair=args.pair,
        starting_balance_default=starting_balance,
        tradable_ratio=tradable_ratio,
    )
    result["artifacts"] = {
        "strategy_file": args.strategy,
        "output_file": args.output,
        "engine": "freqtrade-backtesting",
        "strategy_name": strategy_name,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"[mvp-backtest] result written: {output_path}")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
