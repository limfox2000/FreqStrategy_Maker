from __future__ import annotations

import os
from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


class GuzhengStrategy(IStrategy):
    """
    Guzheng strategy:
    - EMA center line as the trading axis.
    - Fibonacci-style envelope bands as the only structural framework.
    - Position changes happen on key band crossings, not on indicator stacking.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "1m"
    process_only_new_candles = True
    startup_candle_count = 400

    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    position_adjustment_enable = True
    max_entry_position_adjustment = 2
    use_custom_stoploss = False

    minimal_roi = {
        "0": 10.0,
    }

    stoploss = -0.10
    trailing_stop = False

    ma_period = 169
    atr_period = 34
    width_smooth_period = 144
    axis_slope_period = 34
    axis_bias_threshold = 0.0005
    dual_entry_zone = 2
    raw_entry_threshold = 5
    max_position_multiplier = 5.0
    rebalance_buffer = 0.35

    # Allowed values: both, long_only, short_only.
    # `GUZHENG_DIRECTION_MODE` environment variable overrides this value.
    trade_direction_mode = "both"

    envelope_scales = (0.236, 0.382, 0.500, 0.618, 0.786, 1.000)
    action_levels = (2, 4, 6)

    single_side_targets = {
        0: 0.35,
        1: 1.0,
        2: 1.7,
        3: 2.6,
    }

    dual_long_targets = {
        -3: 0.45,
        -2: 0.90,
        -1: 1.35,
        0: 0.85,
        1: 0.35,
        2: 0.0,
        3: 0.0,
    }

    dual_short_targets = {
        3: 0.45,
        2: 0.90,
        1: 1.35,
        0: 0.85,
        -1: 0.35,
        -2: 0.0,
        -3: 0.0,
    }

    plot_config = {
        "main_plot": {
            "ema_center": {"color": "#f5f1c5"},
            "env_upper_1": {"color": "#9fd3a2"},
            "env_upper_3": {"color": "#72b37e"},
            "env_upper_6": {"color": "#4f8f62"},
            "env_lower_1": {"color": "#d6aaa6"},
            "env_lower_3": {"color": "#bc7f77"},
            "env_lower_6": {"color": "#8e5750"},
        }
    }

    def _direction_mode(self) -> str:
        raw_mode = os.getenv("GUZHENG_DIRECTION_MODE", self.trade_direction_mode).strip().lower()
        aliases = {
            "both": "both",
            "all": "both",
            "long": "long_only",
            "long_only": "long_only",
            "short": "short_only",
            "short_only": "short_only",
        }
        return aliases.get(raw_mode, "both")

    def _allow_long(self) -> bool:
        return self._direction_mode() in {"both", "long_only"}

    def _allow_short(self) -> bool:
        return self._direction_mode() in {"both", "short_only"}

    def _ma_period(self) -> int:
        raw_value = os.getenv("GUZHENG_MA_PERIOD", str(self.ma_period)).strip()
        try:
            value = int(raw_value)
        except ValueError:
            return self.ma_period
        return max(20, value)

    def _band_offset_multiplier(self) -> float:
        raw_value = os.getenv("GUZHENG_BAND_OFFSET_MULTIPLIER", "1.0").strip()
        try:
            value = float(raw_value)
        except ValueError:
            return 1.0
        return max(0.1, value)

    def _raw_zone_from_candle(self, candle) -> int:
        zone = 0
        for idx in range(1, len(self.envelope_scales) + 1):
            if candle["close"] >= candle[f"env_upper_{idx}"]:
                zone = idx
            if candle["close"] <= candle[f"env_lower_{idx}"]:
                zone = -idx
        return zone

    def _action_zone_from_candle(self, candle) -> int:
        zone = 0
        for bucket, idx in enumerate(self.action_levels, start=1):
            if candle["close"] >= candle[f"env_upper_{idx}"]:
                zone = bucket
            if candle["close"] <= candle[f"env_lower_{idx}"]:
                zone = -bucket
        return zone

    def _target_multiplier(self, zone: int, is_short: bool) -> float:
        mode = self._direction_mode()
        zone = max(-len(self.action_levels), min(len(self.action_levels), zone))

        if mode == "long_only":
            if is_short or zone < 0:
                return 0.0
            return self.single_side_targets.get(zone, 0.0)

        if mode == "short_only":
            if (not is_short) or zone > 0:
                return 0.0
            return self.single_side_targets.get(abs(zone), 0.0)

        if is_short:
            return self.dual_short_targets.get(zone, 0.0)
        return self.dual_long_targets.get(zone, 0.0)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ma_period = self._ma_period()
        band_offset_multiplier = self._band_offset_multiplier()

        dataframe["ema_center"] = ta.EMA(dataframe, timeperiod=ma_period)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)

        dataframe["center_gap"] = (
            (dataframe["close"] - dataframe["ema_center"]).abs() / dataframe["ema_center"]
        )
        dataframe["gap_mean"] = (
            dataframe["center_gap"].rolling(self.width_smooth_period, min_periods=10).mean()
        )
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["ema_center"]
        dataframe["axis_slope"] = (
            dataframe["ema_center"].pct_change(self.axis_slope_period).fillna(0.0)
        )

        # Widen the base envelope so 1m noise does not trigger every nearby band.
        dataframe["band_unit"] = (
            dataframe["gap_mean"] * 0.70 + dataframe["atr_ratio"] * 0.90
        ).clip(lower=0.0038, upper=0.0320) * band_offset_multiplier

        for idx, scale in enumerate(self.envelope_scales, start=1):
            width = dataframe["band_unit"] * scale
            dataframe[f"env_upper_{idx}"] = dataframe["ema_center"] * (1.0 + width)
            dataframe[f"env_lower_{idx}"] = dataframe["ema_center"] * (1.0 - width)

        dataframe["raw_zone"] = 0
        for idx in range(1, len(self.envelope_scales) + 1):
            dataframe.loc[dataframe["close"] >= dataframe[f"env_upper_{idx}"], "raw_zone"] = idx
            dataframe.loc[dataframe["close"] <= dataframe[f"env_lower_{idx}"], "raw_zone"] = -idx

        dataframe["action_zone"] = 0
        for bucket, idx in enumerate(self.action_levels, start=1):
            dataframe.loc[dataframe["close"] >= dataframe[f"env_upper_{idx}"], "action_zone"] = bucket
            dataframe.loc[dataframe["close"] <= dataframe[f"env_lower_{idx}"], "action_zone"] = -bucket

        dataframe["raw_zone_shift"] = dataframe["raw_zone"].diff().fillna(0)
        dataframe["action_zone_shift"] = dataframe["action_zone"].diff().fillna(0)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0

        prev_action = dataframe["action_zone"].shift(1).fillna(0)
        prev_raw = dataframe["raw_zone"].shift(1).fillna(0)
        action_up = dataframe["action_zone"] > prev_action
        action_down = dataframe["action_zone"] < prev_action
        volume_ok = dataframe["volume"] > 0
        below_axis = dataframe["close"] <= dataframe["ema_center"]
        above_axis = dataframe["close"] >= dataframe["ema_center"]
        long_bias = dataframe["axis_slope"] > self.axis_bias_threshold
        short_bias = dataframe["axis_slope"] < -self.axis_bias_threshold

        if self._allow_long():
            if self._direction_mode() == "long_only":
                enter_long = (
                    action_up
                    & (prev_action <= 0)
                    & (dataframe["action_zone"] >= 1)
                    & long_bias
                    & volume_ok
                )
                dataframe.loc[enter_long, "enter_long"] = 1
                dataframe.loc[enter_long, "enter_tag"] = "long_only_breakout"
            else:
                enter_long = (
                    action_up
                    & (prev_action <= -self.dual_entry_zone)
                    & (prev_raw <= -self.raw_entry_threshold)
                    & (dataframe["action_zone"] <= -1)
                    & below_axis
                    & volume_ok
                )
                dataframe.loc[enter_long, "enter_long"] = 1
                dataframe.loc[enter_long, "enter_tag"] = "dual_long_recovery"

        if self._allow_short():
            if self._direction_mode() == "short_only":
                enter_short = (
                    action_down
                    & (prev_action >= 0)
                    & (dataframe["action_zone"] <= -1)
                    & short_bias
                    & volume_ok
                )
                dataframe.loc[enter_short, "enter_short"] = 1
                dataframe.loc[enter_short, "enter_tag"] = "short_only_breakdown"
            else:
                enter_short = (
                    action_down
                    & (prev_action >= self.dual_entry_zone)
                    & (prev_raw >= self.raw_entry_threshold)
                    & (dataframe["action_zone"] >= 1)
                    & above_axis
                    & volume_ok
                )
                dataframe.loc[enter_short, "enter_short"] = 1
                dataframe.loc[enter_short, "enter_tag"] = "dual_short_recovery"

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0
        return dataframe

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
        if (side == "long" and not self._allow_long()) or (side == "short" and not self._allow_short()):
            return 0.0

        stake = max_stake / self.max_position_multiplier
        if self.config.get("stake_amount") != "unlimited":
            stake = proposed_stake / self.max_position_multiplier

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
        if trade.has_open_orders or not self.dp:
            return None
        if current_time <= trade.open_date_utc:
            return None

        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe is None or len(dataframe) < 2:
            return None

        last_candle = dataframe.iloc[-1].squeeze()
        previous_candle = dataframe.iloc[-2].squeeze()

        current_zone = self._action_zone_from_candle(last_candle)
        previous_zone = self._action_zone_from_candle(previous_candle)
        if current_zone == previous_zone:
            return None

        filled_entries = trade.select_filled_orders(trade.entry_side)
        if not filled_entries:
            return None

        base_stake = filled_entries[0].stake_amount_filled
        if not base_stake:
            return None

        desired_multiplier = self._target_multiplier(current_zone, trade.is_short)
        desired_stake = base_stake * desired_multiplier
        current_stake = trade.stake_amount
        stake_delta = desired_stake - current_stake

        if abs(stake_delta) < base_stake * self.rebalance_buffer:
            return None

        if stake_delta > 0:
            max_total_entries = self.max_entry_position_adjustment + 1
            if trade.nr_of_successful_entries >= max_total_entries:
                return None

            add_stake = min(stake_delta, max_stake)
            if min_stake is not None and add_stake < min_stake:
                return None

            return add_stake, f"action_{previous_zone}_to_{current_zone}_add"

        reduce_stake = min(-stake_delta, current_stake)
        if desired_multiplier <= 0.05:
            return -current_stake, f"action_{previous_zone}_to_{current_zone}_close"

        if min_stake is not None and reduce_stake < min_stake:
            return None

        return -reduce_stake, f"action_{previous_zone}_to_{current_zone}_reduce"
