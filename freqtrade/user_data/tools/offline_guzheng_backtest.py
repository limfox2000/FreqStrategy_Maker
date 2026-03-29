from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


FEE_RATE = 0.0005
STARTING_BALANCE = 1000.0


@dataclass
class Position:
    side: str
    open_time: pd.Timestamp
    open_index: int
    base_stake: float
    current_stake: float
    qty: float
    avg_price: float
    entries: int
    enter_tag: str
    realized_pnl: float = 0.0


def load_strategy(strategy_path: Path):
    spec = importlib.util.spec_from_file_location("offline_guzheng_strategy", strategy_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    strategy = module.GuzhengStrategy({"stake_amount": "unlimited"})
    return strategy


def parse_timerange(timerange: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_raw, end_raw = timerange.split("-")
    start = pd.Timestamp(start_raw, tz="UTC")
    end = pd.Timestamp(end_raw, tz="UTC") + pd.Timedelta(days=1)
    return start, end


def finalize_position(position: Position, price: float, reason: str) -> tuple[float, dict]:
    notional = position.qty * price
    fee = notional * FEE_RATE
    if position.side == "long":
        pnl = (price - position.avg_price) * position.qty - fee
    else:
        pnl = (position.avg_price - price) * position.qty - fee

    total_pnl = position.realized_pnl + pnl
    trade = {
        "side": position.side,
        "open_time": position.open_time.isoformat(),
        "close_time": None,
        "base_stake": position.base_stake,
        "max_stake": position.current_stake,
        "profit_abs": total_pnl,
        "profit_ratio": total_pnl / STARTING_BALANCE,
        "enter_tag": position.enter_tag,
        "exit_reason": reason,
        "duration": None,
    }
    return total_pnl, trade


def simulate(strategy, dataframe: pd.DataFrame, mode: str) -> dict:
    os.environ["GUZHENG_DIRECTION_MODE"] = mode

    df = strategy.populate_indicators(dataframe.copy(), {})
    df = strategy.populate_entry_trend(df, {})

    equity = STARTING_BALANCE
    equity_curve: list[float] = []
    position: Position | None = None
    trades: list[dict] = []
    gross_profit = 0.0
    gross_loss = 0.0

    for idx in range(1, len(df)):
        row = df.iloc[idx]
        prev_row = df.iloc[idx - 1]
        timestamp = row["date"]
        price = float(row["close"])

        if position is not None:
            current_profit = (
                (price - position.avg_price) / position.avg_price
                if position.side == "long"
                else (position.avg_price - price) / position.avg_price
            )

            if current_profit <= strategy.stoploss:
                pnl, trade = finalize_position(position, price, "stoploss")
                trade["close_time"] = timestamp.isoformat()
                trade["duration"] = idx - position.open_index
                trades.append(trade)
                equity += pnl
                gross_profit += max(pnl, 0.0)
                gross_loss += min(pnl, 0.0)
                position = None
            else:
                current_zone = strategy._action_zone_from_candle(row)
                previous_zone = strategy._action_zone_from_candle(prev_row)

                if timestamp > position.open_time and current_zone != previous_zone:
                    desired_multiplier = strategy._target_multiplier(
                        current_zone,
                        position.side == "short",
                    )
                    desired_stake = position.base_stake * desired_multiplier
                    stake_delta = desired_stake - position.current_stake

                    if abs(stake_delta) >= position.base_stake * strategy.rebalance_buffer:
                        if stake_delta > 0 and position.entries < strategy.max_entry_position_adjustment + 1:
                            add_stake = stake_delta
                            add_qty = add_stake / price
                            fee = add_stake * FEE_RATE
                            new_qty = position.qty + add_qty
                            position.avg_price = (
                                (position.avg_price * position.qty) + (price * add_qty)
                            ) / new_qty
                            position.qty = new_qty
                            position.current_stake += add_stake
                            position.entries += 1
                            position.realized_pnl -= fee
                        elif stake_delta < 0:
                            reduce_stake = min(-stake_delta, position.current_stake)
                            reduce_qty = min(position.qty, reduce_stake / price)
                            fee = reduce_qty * price * FEE_RATE

                            if position.side == "long":
                                pnl = (price - position.avg_price) * reduce_qty - fee
                            else:
                                pnl = (position.avg_price - price) * reduce_qty - fee

                            position.realized_pnl += pnl
                            position.qty -= reduce_qty
                            position.current_stake = max(0.0, position.current_stake - reduce_stake)

                            if desired_multiplier <= 0.05 or position.qty <= 1e-12:
                                pnl, trade = finalize_position(position, price, "target_close")
                                trade["close_time"] = timestamp.isoformat()
                                trade["duration"] = idx - position.open_index
                                trades.append(trade)
                                equity += pnl
                                gross_profit += max(pnl, 0.0)
                                gross_loss += min(pnl, 0.0)
                                position = None

        if position is None:
            enter_long = bool(row.get("enter_long", 0))
            enter_short = bool(row.get("enter_short", 0))

            if enter_long ^ enter_short:
                side = "long" if enter_long else "short"
                unit_stake = equity / strategy.max_position_multiplier
                qty = unit_stake / price
                fee = unit_stake * FEE_RATE

                position = Position(
                    side=side,
                    open_time=timestamp,
                    open_index=idx,
                    base_stake=unit_stake,
                    current_stake=unit_stake,
                    qty=qty,
                    avg_price=price,
                    entries=1,
                    enter_tag=str(row.get("enter_tag", "")),
                    realized_pnl=-fee,
                )

        unrealized = 0.0
        if position is not None:
            if position.side == "long":
                unrealized = (price - position.avg_price) * position.qty
            else:
                unrealized = (position.avg_price - price) * position.qty
            unrealized += position.realized_pnl

        equity_curve.append(equity + unrealized)

    if position is not None:
        final_row = df.iloc[-1]
        final_price = float(final_row["close"])
        pnl, trade = finalize_position(position, final_price, "force_close")
        trade["close_time"] = final_row["date"].isoformat()
        trade["duration"] = len(df) - 1 - position.open_index
        trades.append(trade)
        equity += pnl
        gross_profit += max(pnl, 0.0)
        gross_loss += min(pnl, 0.0)

    win_count = sum(1 for trade in trades if trade["profit_abs"] > 0)
    peak = -math.inf
    max_drawdown = 0.0
    for value in equity_curve or [STARTING_BALANCE]:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)

    start_close = float(df.iloc[0]["close"])
    end_close = float(df.iloc[-1]["close"])
    long_trades = [trade for trade in trades if trade["side"] == "long"]
    short_trades = [trade for trade in trades if trade["side"] == "short"]

    return {
        "mode": mode,
        "trades": len(trades),
        "winrate": round((win_count / len(trades) * 100.0), 2) if trades else 0.0,
        "profit_total_pct": round(((equity - STARTING_BALANCE) / STARTING_BALANCE) * 100.0, 3),
        "profit_total_abs": round(equity - STARTING_BALANCE, 3),
        "profit_factor": round(gross_profit / abs(gross_loss), 3) if gross_loss < 0 else None,
        "max_drawdown_pct": round(max_drawdown * 100.0, 3),
        "market_change_pct": round(((end_close / start_close) - 1.0) * 100.0, 3),
        "long_trades": len(long_trades),
        "long_profit_pct": round(sum(t["profit_abs"] for t in long_trades) / STARTING_BALANCE * 100.0, 3),
        "short_trades": len(short_trades),
        "short_profit_pct": round(sum(t["profit_abs"] for t in short_trades) / STARTING_BALANCE * 100.0, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["both", "long_only", "short_only"], required=True)
    parser.add_argument("--timerange", required=True, help="YYYYMMDD-YYYYMMDD")
    parser.add_argument("--ma-period", type=int, default=169)
    parser.add_argument("--band-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--data",
        default="/freqtrade/user_data/data/binance/futures/XRP_USDT_USDT-1m-futures.feather",
    )
    parser.add_argument(
        "--strategy",
        default="/freqtrade/user_data/strategies/GuzhengStrategy.py",
    )
    args = parser.parse_args()

    start, end = parse_timerange(args.timerange)
    raw = pd.read_feather(args.data)
    raw["date"] = pd.to_datetime(raw["date"], utc=True)
    sample = raw[(raw["date"] >= start) & (raw["date"] < end)].copy()
    if sample.empty:
        raise SystemExit("No data in requested timerange.")

    os.environ["GUZHENG_MA_PERIOD"] = str(args.ma_period)
    os.environ["GUZHENG_BAND_OFFSET_MULTIPLIER"] = str(args.band_multiplier)
    strategy = load_strategy(Path(args.strategy))
    result = simulate(strategy, sample, args.mode)
    result["ma_period"] = args.ma_period
    result["band_multiplier"] = args.band_multiplier
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
