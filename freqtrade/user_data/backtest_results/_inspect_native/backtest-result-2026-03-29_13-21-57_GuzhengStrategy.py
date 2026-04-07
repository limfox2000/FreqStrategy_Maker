from __future__ import annotations

import os
from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute


class GuzhengStrategy(IStrategy):
    """
    Guzheng strategy:
    - Long EMA as the center axis.
    - Multi-layer fibonacci-style envelopes as the decision framework.
    - Position sizing follows band transitions instead of momentum filters.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "1m"
    process_only_new_candles = True
    startup_candle_count = 400

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    position_adjustment_enable = True
    max_entry_position_adjustment = 5
    use_custom_stoploss = True

    minimal_roi = {
        "0": 0.08,
    }

    stoploss = -0.18
    trailing_stop = False

    ma_period = 169
    atr_period = 34
    width_smooth_period = 89
    dual_entry_zone = 2
    max_position_multiplier = 4.8

    # Allowed values: both, long_only, short_only.
    # `GUZHENG_DIRECTION_MODE` environment variable overrides this value.
    trade_direction_mode = "both"

    envelope_scales = (0.236, 0.382, 0.500, 0.618, 0.786, 1.000)

    single_side_targets = {
        0: 0.60,
        1: 1.00,
        2: 1.55,
        3: 2.20,
        4: 2.95,
        5: 3.80,
        6: 4.80,
    }

    dual_long_targets = {
        -6: 0.80,
        -5: 1.10,
        -4: 1.50,
        -3: 2.00,
        -2: 2.60,
        -1: 3.20,
        0: 2.20,
        1: 1.35,
        2: 0.60,
    }

    dual_short_targets = {
        6: 0.80,
        5: 1.10,
        4: 1.50,
        3: 2.00,
        2: 2.60,
        1: 3.20,
        0: 2.20,
        -1: 1.35,
        -2: 0.60,
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

    def _zone_from_candle(self, candle) -> int:
        zone = 0
        for idx in range(1, len(self.envelope_scales) + 1):
            if candle["close"] >= candle[f"env_upper_{idx}"]:
                zone = idx
            if candle["close"] <= candle[f"env_lower_{idx}"]:
                zone = -idx
        return zone

    def _target_multiplier(self, zone: int, is_short: bool) -> float:
        mode = self._direction_mode()
        zone = max(-len(self.envelope_scales), min(len(self.envelope_scales), zone))

        if mode == "long_only":
            if is_short:
                return 0.0
            if zone <= -1:
                return 0.0
            zone_key = max(0, min(len(self.envelope_scales), zone))
            return self.single_side_targets.get(zone_key, 0.0)

        if mode == "short_only":
            if not is_short:
                return 0.0
            if zone >= 1:
                return 0.0
            zone_key = max(0, min(len(self.envelope_scales), abs(zone)))
            return self.single_side_targets.get(zone_key, 0.0)

        if is_short:
            return self.dual_short_targets.get(zone, 0.0)
        return self.dual_long_targets.get(zone, 0.0)

    def _entry_tags(self, current_zone: int) -> tuple[str, str]:
        mode = self._direction_mode()
        if mode == "long_only":
            return f"long_only_zone_{current_zone}", ""
        if mode == "short_only":
            return "", f"short_only_zone_{current_zone}"
        return f"dual_long_zone_{current_zone}", f"dual_short_zone_{current_zone}"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_center"] = ta.EMA(dataframe, timeperiod=self.ma_period)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)

        dataframe["center_gap"] = (
            (dataframe["close"] - dataframe["ema_center"]).abs() / dataframe["ema_center"]
        )
        dataframe["gap_mean"] = (
            dataframe["center_gap"].rolling(self.width_smooth_period, min_periods=10).mean()
        )
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["ema_center"]
        dataframe["band_unit"] = (
            dataframe["gap_mean"] * 0.45 + dataframe["atr_ratio"] * 0.55
        ).clip(lower=0.0018, upper=0.0250)

        for idx, scale in enumerate(self.envelope_scales, start=1):
            width = dataframe["band_unit"] * scale
            dataframe[f"env_upper_{idx}"] = dataframe["ema_center"] * (1.0 + width)
            dataframe[f"env_lower_{idx}"] = dataframe["ema_center"] * (1.0 - width)

        dataframe["close_zone"] = 0
        for idx in range(1, len(self.envelope_scales) + 1):
            dataframe.loc[dataframe["close"] >= dataframe[f"env_upper_{idx}"], "close_zone"] = idx
            dataframe.loc[dataframe["close"] <= dataframe[f"env_lower_{idx}"], "close_zone"] = -idx

        dataframe["zone_shift"] = dataframe["close_zone"].diff().fillna(0)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0

        prev_zone = dataframe["close_zone"].shift(1).fillna(0)
        zone_up = dataframe["close_zone"] > prev_zone
        zone_down = dataframe["close_zone"] < prev_zone
        volume_ok = dataframe["volume"] > 0

        long_tag, short_tag = self._entry_tags(0)

        if self._allow_long():
            if self._direction_mode() == "long_only":
                enter_long = zone_up & (prev_zone <= 0) & (dataframe["close_zone"] >= 1) & volume_ok
            else:
                enter_long = (
                    zone_up
                    & (prev_zone <= -self.dual_entry_zone)
                    & (dataframe["close_zone"] <= -1)
                    & volume_ok
                )
            dataframe.loc[enter_long, "enter_long"] = 1
            dataframe.loc[enter_long, "enter_tag"] = (
                long_tag if self._direction_mode() == "long_only" else "dual_long_recovery"
            )

        if self._allow_short():
            if self._direction_mode() == "short_only":
                enter_short = (
                    zone_down & (prev_zone >= 0) & (dataframe["close_zone"] <= -1) & volume_ok
                )
            else:
                enter_short = (
                    zone_down
                    & (prev_zone >= self.dual_entry_zone)
                    & (dataframe["close_zone"] >= 1)
                    & volume_ok
                )
            dataframe.loc[enter_short, "enter_short"] = 1
            dataframe.loc[enter_short, "enter_tag"] = (
                short_tag if self._direction_mode() == "short_only" else "dual_short_recovery"
            )

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        prev_zone = dataframe["close_zone"].shift(1).fillna(0)
        zone_up = dataframe["close_zone"] > prev_zone
        zone_down = dataframe["close_zone"] < prev_zone
        volume_ok = dataframe["volume"] > 0

        mode = self._direction_mode()

        emergency_long = dataframe["close"] <= dataframe[f"env_lower_{len(self.envelope_scales)}"]
        emergency_short = dataframe["close"] >= dataframe[f"env_upper_{len(self.envelope_scales)}"]

        if mode == "long_only":
            dataframe.loc[(zone_down & (dataframe["close_zone"] <= -1) & volume_ok) | emergency_long, "exit_long"] = 1
        elif mode == "short_only":
            dataframe.loc[(zone_up & (dataframe["close_zone"] >= 1) & volume_ok) | emergency_short, "exit_short"] = 1
        else:
            dataframe.loc[
                ((dataframe["close_zone"] >= 3) & zone_up & volume_ok) | emergency_long,
                "exit_long",
            ] = 1
            dataframe.loc[
                ((dataframe["close_zone"] <= -3) & zone_down & volume_ok) | emergency_short,
                "exit_short",
            ] = 1

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

        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe is None or len(dataframe) < 2:
            return None

        last_candle = dataframe.iloc[-1].squeeze()
        previous_candle = dataframe.iloc[-2].squeeze()

        current_zone = self._zone_from_candle(last_candle)
        previous_zone = self._zone_from_candle(previous_candle)

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

        # Ignore very small adjustments. This strategy is about band transitions,
        # not continuous micro rebalancing.
        if abs(stake_delta) < base_stake * 0.15:
            return None

        if stake_delta > 0:
            max_total_entries = self.max_entry_position_adjustment + 1
            if trade.nr_of_successful_entries >= max_total_entries:
                return None

            add_stake = min(stake_delta, max_stake)
            if min_stake is not None and add_stake < min_stake:
                return None

            return add_stake, f"zone_{previous_zone}_to_{current_zone}_add"

        reduce_stake = min(-stake_delta, current_stake)
        if desired_multiplier <= 0.05:
            return -current_stake, f"zone_{previous_zone}_to_{current_zone}_close"

        if min_stake is not None and reduce_stake < min_stake:
            return None

        return -reduce_stake, f"zone_{previous_zone}_to_{current_zone}_reduce"

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        if not self.dp:
            return None

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None

        last_candle = dataframe.iloc[-1].squeeze()
        buffer_value = float(last_candle["atr"] * 0.35)
        outer_idx = len(self.envelope_scales)

        if trade.is_short:
            stop_price = float(last_candle[f"env_upper_{outer_idx}"] + buffer_value)
            if current_profit > 0.02:
                stop_price = min(stop_price, float(last_candle["ema_center"] + buffer_value))
            if stop_price <= current_rate:
                return None
            return stoploss_from_absolute(
                stop_price,
                current_rate=current_rate,
                is_short=True,
                leverage=trade.leverage,
            )

        stop_price = float(last_candle[f"env_lower_{outer_idx}"] - buffer_value)
        if current_profit > 0.02:
            stop_price = max(stop_price, float(last_candle["ema_center"] - buffer_value))
        if stop_price >= current_rate:
            return None
        return stoploss_from_absolute(
            stop_price,
            current_rate=current_rate,
            is_short=False,
            leverage=trade.leverage,
        )
