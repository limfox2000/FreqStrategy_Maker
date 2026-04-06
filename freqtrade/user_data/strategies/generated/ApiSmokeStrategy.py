from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


class ApiSmokeStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1m"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 240

    minimal_roi = {
        "0": 0.04,
        "120": 0.02,
        "360": 0.0
    }
    stoploss = -0.08
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True
    use_exit_signal = True
    exit_profit_only = False

    ema_fast = 20
    ema_slow = 60
    rsi_low = 35
    rsi_high = 65

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0
        dataframe.loc[:, "enter_tag"] = ""

        long_signal = (
            (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["rsi"] > self.rsi_low)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[long_signal, "enter_long"] = 1
        dataframe.loc[long_signal, "enter_tag"] = "ema_rsi_long"

        if True:
            short_signal = (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["rsi"] < self.rsi_high)
                & (dataframe["volume"] > 0)
            )
            dataframe.loc[short_signal, "enter_short"] = 1
            dataframe.loc[short_signal, "enter_tag"] = "ema_rsi_short"

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        exit_long = (dataframe["ema_fast"] < dataframe["ema_slow"]) | (dataframe["rsi"] > 75)
        exit_short = (dataframe["ema_fast"] > dataframe["ema_slow"]) | (dataframe["rsi"] < 25)

        dataframe.loc[exit_long, "exit_long"] = 1
        dataframe.loc[exit_short, "exit_short"] = 1
        return dataframe

    position_adjustment_enable = True
    max_entry_position_adjustment = 2
    stake_split = 3.0

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        stake = max_stake / self.stake_split
        if self.config.get("stake_amount") != "unlimited":
            stake = proposed_stake / self.stake_split
        if min_stake is not None:
            stake = max(stake, min_stake)
        return min(stake, max_stake)

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> float | None | tuple[float | None, str | None]:
        if current_profit <= -0.03 and trade.nr_of_successful_entries < self.max_entry_position_adjustment + 1:
            add_stake = max_stake / self.stake_split
            if min_stake is not None and add_stake < min_stake:
                return None
            return add_stake, "pyramiding_add"

        if current_profit >= 0.05:
            return -(trade.stake_amount * 0.5), "take_partial_profit"
        return None
