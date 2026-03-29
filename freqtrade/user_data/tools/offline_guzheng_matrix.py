from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from offline_guzheng_backtest import load_strategy, parse_timerange, simulate


CASES = (
    ("long_uptrend", "long_only", "20251229-20260108"),
    ("long_downtrend", "long_only", "20260127-20260206"),
    ("short_downtrend", "short_only", "20260127-20260206"),
    ("short_uptrend", "short_only", "20251229-20260108"),
    ("both_range", "both", "20260224-20260307"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ma-periods", nargs="+", type=int, required=True)
    parser.add_argument("--band-multipliers", nargs="+", type=float, required=True)
    parser.add_argument(
        "--data",
        default="/freqtrade/user_data/data/binance/futures/XRP_USDT_USDT-1m-futures.feather",
    )
    parser.add_argument(
        "--strategy",
        default="/freqtrade/user_data/strategies/GuzhengStrategy.py",
    )
    args = parser.parse_args()

    raw = pd.read_feather(args.data)
    raw["date"] = pd.to_datetime(raw["date"], utc=True)

    sample_cache: dict[str, pd.DataFrame] = {}
    for _, _, timerange in CASES:
        start, end = parse_timerange(timerange)
        sample_cache[timerange] = raw[(raw["date"] >= start) & (raw["date"] < end)].copy()

    results: list[dict] = []
    for ma_period in args.ma_periods:
        for band_multiplier in args.band_multipliers:
            os.environ["GUZHENG_MA_PERIOD"] = str(ma_period)
            os.environ["GUZHENG_BAND_OFFSET_MULTIPLIER"] = str(band_multiplier)
            combo_results: list[dict] = []
            total_profit_pct = 0.0
            worst_drawdown_pct = 0.0

            for label, mode, timerange in CASES:
                strategy = load_strategy(Path(args.strategy))
                sample = sample_cache[timerange].copy()
                result = simulate(strategy, sample, mode)
                result["case"] = label
                result["ma_period"] = ma_period
                result["band_multiplier"] = band_multiplier
                combo_results.append(result)
                total_profit_pct += result["profit_total_pct"]
                worst_drawdown_pct = max(worst_drawdown_pct, result["max_drawdown_pct"])

            results.append(
                {
                    "ma_period": ma_period,
                    "band_multiplier": band_multiplier,
                    "total_profit_pct": round(total_profit_pct, 3),
                    "worst_drawdown_pct": round(worst_drawdown_pct, 3),
                    "cases": combo_results,
                }
            )

    results.sort(key=lambda item: (item["total_profit_pct"], -item["worst_drawdown_pct"]), reverse=True)
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
