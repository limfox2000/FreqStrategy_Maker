from __future__ import annotations

import os

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IStrategy, IntParameter


class TradingViewZoneStrategy(IStrategy):
    """
    Port of tradingview/zone_strategy.pine (fixed-price zone version).

    The original Pine logic is preserved, but converted to proper Freqtrade
    parameter objects so periods, zone prices, widths and thresholds are all variables.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 400

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Keep ROI/SL permissive so exits are mostly controlled by strategy signals.
    minimal_roi = {"0": 10.0}
    stoploss = -0.99
    trailing_stop = False

    # Core periods
    ema_length = IntParameter(20, 400, default=144, space="buy", optimize=False, load=True)
    fast_len = IntParameter(3, 100, default=7, space="buy", optimize=False, load=True)
    slow_len = IntParameter(5, 200, default=21, space="buy", optimize=False, load=True)
    rsi_period = IntParameter(7, 50, default=14, space="buy", optimize=False, load=True)

    # Fixed-price zones (Pine equivalent)
    zone1_base = DecimalParameter(0.0, 1_000_000.0, default=4100.0, decimals=2, space="buy", optimize=False, load=True)
    zone1_width = DecimalParameter(0.01, 100_000.0, default=30.0, decimals=2, space="buy", optimize=False, load=True)
    zone2_base = DecimalParameter(0.0, 1_000_000.0, default=4200.0, decimals=2, space="buy", optimize=False, load=True)
    zone2_width = DecimalParameter(0.01, 100_000.0, default=30.0, decimals=2, space="buy", optimize=False, load=True)
    zone3_base = DecimalParameter(0.0, 1_000_000.0, default=4300.0, decimals=2, space="buy", optimize=False, load=True)
    zone3_width = DecimalParameter(0.01, 100_000.0, default=30.0, decimals=2, space="buy", optimize=False, load=True)
    zone4_base = DecimalParameter(0.0, 1_000_000.0, default=4400.0, decimals=2, space="buy", optimize=False, load=True)
    zone4_width = DecimalParameter(0.01, 100_000.0, default=30.0, decimals=2, space="buy", optimize=False, load=True)

    # Entry mode: aggressive / dual / conservative
    entry_mode = CategoricalParameter(
        ["aggressive", "dual", "conservative"],
        default="dual",
        space="buy",
        optimize=False,
        load=True,
    )

    # Thresholds from Pine logic
    long_zone_pos_max = DecimalParameter(0.05, 0.49, default=0.30, decimals=2, space="buy", optimize=False, load=True)
    short_zone_pos_min = DecimalParameter(0.51, 0.95, default=0.70, decimals=2, space="buy", optimize=False, load=True)
    long_ma_diff_min = DecimalParameter(-5.0, 5.0, default=-0.5, decimals=2, space="buy", optimize=False, load=True)
    short_ma_diff_max = DecimalParameter(-5.0, 5.0, default=0.5, decimals=2, space="buy", optimize=False, load=True)
    long_macd_trend_min = DecimalParameter(-5.0, 5.0, default=-0.2, decimals=2, space="buy", optimize=False, load=True)
    short_macd_trend_max = DecimalParameter(-5.0, 5.0, default=0.2, decimals=2, space="buy", optimize=False, load=True)
    long_rsi_min = IntParameter(1, 99, default=40, space="buy", optimize=False, load=True)
    short_rsi_max = IntParameter(1, 99, default=60, space="buy", optimize=False, load=True)

    # Exit multipliers from Pine logic
    long_exit_ema_mult = DecimalParameter(1.0000, 1.0200, default=1.0030, decimals=4, space="sell", optimize=False, load=True)
    short_exit_ema_mult = DecimalParameter(0.9800, 1.0000, default=0.9970, decimals=4, space="sell", optimize=False, load=True)

    plot_config = {
        "main_plot": {
            "ema_line": {"color": "#8e63d6"},
            "fast_ma": {"color": "#2e86de"},
            "slow_ma": {"color": "#f39c12"},
            "zone1_top": {"color": "#27ae60"},
            "zone1_bottom": {"color": "#27ae60"},
            "zone2_top": {"color": "#58d68d"},
            "zone2_bottom": {"color": "#58d68d"},
            "zone3_top": {"color": "#e74c3c"},
            "zone3_bottom": {"color": "#e74c3c"},
            "zone4_top": {"color": "#922b21"},
            "zone4_bottom": {"color": "#922b21"},
            "zone_mid": {"color": "#7f8c8d"},
        }
    }

    def _entry_mode(self) -> str:
        raw = os.getenv("TV_ZONE_ENTRY_MODE", "").strip().lower()
        if not raw:
            raw = str(self.entry_mode.value).strip().lower()

        aliases = {
            "aggressive": "aggressive",
            "zone": "aggressive",
            "dual": "dual",
            "conservative": "conservative",
            "indicator": "conservative",
        }
        return aliases.get(raw, "dual")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_length = int(self.ema_length.value)
        fast_len = int(self.fast_len.value)
        slow_len = int(self.slow_len.value)
        rsi_period = int(self.rsi_period.value)

        zone1_base = float(self.zone1_base.value)
        zone1_width = float(self.zone1_width.value)
        zone2_base = float(self.zone2_base.value)
        zone2_width = float(self.zone2_width.value)
        zone3_base = float(self.zone3_base.value)
        zone3_width = float(self.zone3_width.value)
        zone4_base = float(self.zone4_base.value)
        zone4_width = float(self.zone4_width.value)

        long_zone_pos_max = float(self.long_zone_pos_max.value)
        short_zone_pos_min = float(self.short_zone_pos_min.value)
        long_ma_diff_min = float(self.long_ma_diff_min.value)
        short_ma_diff_max = float(self.short_ma_diff_max.value)
        long_macd_trend_min = float(self.long_macd_trend_min.value)
        short_macd_trend_max = float(self.short_macd_trend_max.value)
        long_rsi_min = int(self.long_rsi_min.value)
        short_rsi_max = int(self.short_rsi_max.value)
        long_exit_ema_mult = float(self.long_exit_ema_mult.value)
        short_exit_ema_mult = float(self.short_exit_ema_mult.value)

        dataframe["ema_line"] = ta.EMA(dataframe, timeperiod=ema_length)
        dataframe["fast_ma"] = ta.EMA(dataframe, timeperiod=fast_len)
        dataframe["slow_ma"] = ta.EMA(dataframe, timeperiod=slow_len)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd_line"] = macd["macd"]
        dataframe["macd_signal"] = macd["macdsignal"]
        dataframe["macd_trend"] = dataframe["macd_line"] - dataframe["macd_signal"]
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=rsi_period)

        dataframe["ma_diff"] = dataframe["fast_ma"] - dataframe["slow_ma"]

        dataframe["zone1_top"] = zone1_base + zone1_width
        dataframe["zone1_bottom"] = zone1_base - zone1_width
        dataframe["zone2_top"] = zone2_base + zone2_width
        dataframe["zone2_bottom"] = zone2_base - zone2_width
        dataframe["zone3_top"] = zone3_base + zone3_width
        dataframe["zone3_bottom"] = zone3_base - zone3_width
        dataframe["zone4_top"] = zone4_base + zone4_width
        dataframe["zone4_bottom"] = zone4_base - zone4_width

        dataframe["in_zone1"] = (dataframe["close"] >= dataframe["zone1_bottom"]) & (
            dataframe["close"] <= dataframe["zone1_top"]
        )
        dataframe["in_zone2"] = (dataframe["close"] >= dataframe["zone2_bottom"]) & (
            dataframe["close"] <= dataframe["zone2_top"]
        )
        dataframe["in_zone3"] = (dataframe["close"] >= dataframe["zone3_bottom"]) & (
            dataframe["close"] <= dataframe["zone3_top"]
        )
        dataframe["in_zone4"] = (dataframe["close"] >= dataframe["zone4_bottom"]) & (
            dataframe["close"] <= dataframe["zone4_top"]
        )

        dataframe["is_above_ema"] = dataframe["close"] > dataframe["ema_line"]
        dataframe["is_below_ema"] = dataframe["close"] < dataframe["ema_line"]
        dataframe["in_long_zone"] = dataframe["is_below_ema"] & (
            dataframe["in_zone1"] | dataframe["in_zone2"]
        )
        dataframe["in_short_zone"] = dataframe["is_above_ema"] & (
            dataframe["in_zone3"] | dataframe["in_zone4"]
        )

        dataframe["current_zone"] = np.select(
            [
                dataframe["in_zone1"],
                dataframe["in_zone2"],
                dataframe["in_zone3"],
                dataframe["in_zone4"],
            ],
            [1, 2, 3, 4],
            default=0,
        )

        dataframe["zone_top"] = np.select(
            [
                dataframe["current_zone"] == 1,
                dataframe["current_zone"] == 2,
                dataframe["current_zone"] == 3,
                dataframe["current_zone"] == 4,
            ],
            [
                dataframe["zone1_top"],
                dataframe["zone2_top"],
                dataframe["zone3_top"],
                dataframe["zone4_top"],
            ],
            default=np.nan,
        )

        dataframe["zone_bottom"] = np.select(
            [
                dataframe["current_zone"] == 1,
                dataframe["current_zone"] == 2,
                dataframe["current_zone"] == 3,
                dataframe["current_zone"] == 4,
            ],
            [
                dataframe["zone1_bottom"],
                dataframe["zone2_bottom"],
                dataframe["zone3_bottom"],
                dataframe["zone4_bottom"],
            ],
            default=np.nan,
        )

        dataframe["zone_mid"] = (dataframe["zone_top"] + dataframe["zone_bottom"]) / 2.0
        dataframe["zone_span"] = dataframe["zone_top"] - dataframe["zone_bottom"]
        dataframe["zone_position"] = np.where(
            dataframe["zone_span"] != 0,
            (dataframe["close"] - dataframe["zone_bottom"]) / dataframe["zone_span"],
            np.nan,
        )

        dataframe["long_zone_trigger"] = (
            dataframe["in_long_zone"]
            & (dataframe["zone_position"] < long_zone_pos_max)
            & (dataframe["close"] < dataframe["open"].shift(1))
        )
        dataframe["short_zone_trigger"] = (
            dataframe["in_short_zone"]
            & (dataframe["zone_position"] > short_zone_pos_min)
            & (dataframe["close"] > dataframe["open"].shift(1))
        )

        dataframe["long_indicator_ok"] = (
            (dataframe["ma_diff"] > long_ma_diff_min)
            | (dataframe["macd_trend"] > long_macd_trend_min)
            | (dataframe["rsi"] > long_rsi_min)
        )
        dataframe["short_indicator_ok"] = (
            (dataframe["ma_diff"] < short_ma_diff_max)
            | (dataframe["macd_trend"] < short_macd_trend_max)
            | (dataframe["rsi"] < short_rsi_max)
        )

        dataframe["long_indicator_strong"] = qtpylib.crossed_above(
            dataframe["fast_ma"], dataframe["slow_ma"]
        ) | ((dataframe["ma_diff"] > 0) & (dataframe["macd_trend"] > 0))

        dataframe["short_indicator_strong"] = qtpylib.crossed_below(
            dataframe["fast_ma"], dataframe["slow_ma"]
        ) | ((dataframe["ma_diff"] < 0) & (dataframe["macd_trend"] < 0))

        dataframe["long_exit_zone"] = (dataframe["close"] > dataframe["zone_top"]) | (
            dataframe["close"] < dataframe["zone_bottom"]
        )
        dataframe["long_exit_ema"] = dataframe["close"] > (dataframe["ema_line"] * long_exit_ema_mult)
        dataframe["long_exit_signal"] = qtpylib.crossed_below(
            dataframe["fast_ma"], dataframe["slow_ma"]
        ) & (dataframe["close"] < dataframe["zone_mid"])

        dataframe["short_exit_zone"] = (dataframe["close"] < dataframe["zone_bottom"]) | (
            dataframe["close"] > dataframe["zone_top"]
        )
        dataframe["short_exit_ema"] = dataframe["close"] < (dataframe["ema_line"] * short_exit_ema_mult)
        dataframe["short_exit_signal"] = qtpylib.crossed_above(
            dataframe["fast_ma"], dataframe["slow_ma"]
        ) & (dataframe["close"] > dataframe["zone_mid"])

        dataframe["long_exit"] = (
            dataframe["long_exit_zone"] | dataframe["long_exit_ema"] | dataframe["long_exit_signal"]
        )
        dataframe["short_exit"] = (
            dataframe["short_exit_zone"] | dataframe["short_exit_ema"] | dataframe["short_exit_signal"]
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0

        volume_ok = dataframe["volume"] > 0
        mode = self._entry_mode()

        if mode == "aggressive":
            long_condition = dataframe["long_zone_trigger"]
            short_condition = dataframe["short_zone_trigger"]
            long_tag = "zone_aggressive_long"
            short_tag = "zone_aggressive_short"
        elif mode == "conservative":
            long_condition = dataframe["in_long_zone"] & dataframe["long_indicator_strong"]
            short_condition = dataframe["in_short_zone"] & dataframe["short_indicator_strong"]
            long_tag = "indicator_conservative_long"
            short_tag = "indicator_conservative_short"
        else:
            long_condition = dataframe["long_zone_trigger"] & dataframe["long_indicator_ok"]
            short_condition = dataframe["short_zone_trigger"] & dataframe["short_indicator_ok"]
            long_tag = "dual_long"
            short_tag = "dual_short"

        dataframe.loc[long_condition & volume_ok, "enter_long"] = 1
        dataframe.loc[short_condition & volume_ok, "enter_short"] = 1
        dataframe.loc[long_condition & volume_ok, "enter_tag"] = long_tag
        dataframe.loc[short_condition & volume_ok, "enter_tag"] = short_tag

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        volume_ok = dataframe["volume"] > 0

        dataframe.loc[dataframe["long_exit"] & volume_ok, "exit_long"] = 1
        dataframe.loc[dataframe["short_exit"] & volume_ok, "exit_short"] = 1

        return dataframe
