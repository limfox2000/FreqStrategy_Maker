from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter

"""
AI-composed Strategy Artifact
preset=codex-xhigh
provider=openai
model=gpt-5.3-codex
mode=codex
reasoning=xhigh
persona=你是一位精通数学与统计学的加密货币量化策略专家，尤其擅长将**数学方法**（时间序列、概率论、线性代数、信号处理）转化为**可运行的 Freqtrade 策略代码**。你对技术指标的计算原理、数值稳定性、滞后性与过拟合成因有深刻理解，能设计
sources={'indicator_factor': 'mod_20260405_142833_05754f', 'position_adjustment': 'mod_20260405_145500_5e0865', 'risk_system': 'mod_20260405_151129_99c8bb'}
"""

class AssembleStrategyMVP(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = '5m'
    can_short = True

    # --- Risk system ---
    minimal_roi = {
        "0": 0.0
    }
    stoploss = -0.05
    trailing_stop = False
    trailing_stop_positive = 0.0
    trailing_stop_positive_offset = 0.0
    trailing_only_offset_is_reached = False
    use_exit_signal = True
    exit_profit_only = False

    # --- Position adjustment ---
    position_adjustment_enable = True
    max_entry_position_adjustment = 1
    stake_split = 2.0
    dca_trigger = 0.012
    reduce_profit_buffer = 0.0015
    ma_fast_len = 9
    ma_slow_len = 21
    reduce_fraction = 0.5

    # --- Hyperoptable parameters ---
    base_ema_len = IntParameter(120, 200, default=144, space='buy')
    fast_ema_len = IntParameter(4, 10, default=6, space='buy')
    slow_ema_len = IntParameter(10, 21, default=13, space='buy')
    base_offset = DecimalParameter(0.008, 0.03, default=0.01618, decimals=5, space='buy')
    zone_step = DecimalParameter(0.002, 0.012, default=0.005, decimals=4, space='buy')

    # Bollinger filter / reaction parameters
    bb_len = IntParameter(18, 40, default=20, space='buy')
    bb_std = DecimalParameter(1.6, 2.8, default=2.0, decimals=2, space='buy')
    bb_squeeze_thresh = DecimalParameter(0.010, 0.050, default=0.020, decimals=4, space='buy')
    zone_touch_buffer = DecimalParameter(0.000, 0.003, default=0.0005, decimals=4, space='buy')

    order_types = {
        'entry': 'limit',
        'exit': 'limit',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['ema_mid'] = ta.EMA(dataframe, timeperiod=int(self.base_ema_len.value))
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=int(self.fast_ema_len.value))
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=int(self.slow_ema_len.value))

        b = float(self.base_offset.value)
        s = float(self.zone_step.value)

        dataframe['u1'] = dataframe['ema_mid'] * (1.0 + b)
        dataframe['u2'] = dataframe['ema_mid'] * (1.0 + b + s)
        dataframe['u3'] = dataframe['ema_mid'] * (1.0 + b + 2.0 * s)

        dataframe['l1'] = dataframe['ema_mid'] * (1.0 - b)
        dataframe['l2'] = dataframe['ema_mid'] * (1.0 - b - s)
        dataframe['l3'] = dataframe['ema_mid'] * (1.0 - b - 2.0 * s)

        dataframe['in_high_zone'] = (
            (dataframe['close'] >= dataframe['u1']) &
            (dataframe['close'] <= dataframe['u3'])
        ).astype('int8')

        dataframe['in_low_zone'] = (
            (dataframe['close'] <= dataframe['l1']) &
            (dataframe['close'] >= dataframe['l3'])
        ).astype('int8')

        dataframe['above_high_zone'] = (dataframe['close'] > dataframe['u3']).astype('int8')
        dataframe['below_low_zone'] = (dataframe['close'] < dataframe['l3']).astype('int8')

        dataframe['cross_up'] = (
            (dataframe['ema_fast'] > dataframe['ema_slow']) &
            (dataframe['ema_fast'].shift(1) <= dataframe['ema_slow'].shift(1))
        ).astype('int8')

        dataframe['cross_down'] = (
            (dataframe['ema_fast'] < dataframe['ema_slow']) &
            (dataframe['ema_fast'].shift(1) >= dataframe['ema_slow'].shift(1))
        ).astype('int8')

        # Bollinger band with squeeze gating in middle zone
        bb = ta.BBANDS(
            dataframe,
            timeperiod=int(self.bb_len.value),
            nbdevup=float(self.bb_std.value),
            nbdevdn=float(self.bb_std.value),
            matype=0
        )
        dataframe['bb_upper'] = bb['upperband']
        dataframe['bb_mid'] = bb['middleband']
        dataframe['bb_lower'] = bb['lowerband']
        dataframe['bb_width'] = (dataframe['bb_upper'] - dataframe['bb_lower']) / dataframe['bb_mid'].replace(0, float('nan'))

        dataframe['bb_mid_zone'] = (
            (dataframe['close'] < dataframe['u1']) &
            (dataframe['close'] > dataframe['l1'])
        ).astype('int8')
        dataframe['bb_squeeze'] = (dataframe['bb_width'] <= float(self.bb_squeeze_thresh.value)).astype('int8')
        dataframe['suppress_cross_signal'] = (
            (dataframe['bb_mid_zone'] == 1) &
            (dataframe['bb_squeeze'] == 1)
        ).astype('int8')

        # Touch signals for reaction at u1/u2/l1/l2
        touch_buf = float(self.zone_touch_buffer.value)
        dataframe['touch_u1'] = (dataframe['high'] >= (dataframe['u1'] * (1.0 - touch_buf))).astype('int8')
        dataframe['touch_u2'] = (dataframe['high'] >= (dataframe['u2'] * (1.0 - touch_buf))).astype('int8')
        dataframe['touch_l1'] = (dataframe['low'] <= (dataframe['l1'] * (1.0 + touch_buf))).astype('int8')
        dataframe['touch_l2'] = (dataframe['low'] <= (dataframe['l2'] * (1.0 + touch_buf))).astype('int8')

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0
        dataframe['enter_tag'] = None

        cross_allowed = dataframe['suppress_cross_signal'] == 0
        long_cross = (dataframe['cross_up'] == 1) & cross_allowed
        short_cross = (dataframe['cross_down'] == 1) & cross_allowed

        long_low_priority = long_cross & (dataframe['in_low_zone'] == 1)
        long_neutral = long_cross & (dataframe['in_high_zone'] == 0)

        dataframe.loc[long_low_priority, 'enter_long'] = 1
        dataframe.loc[long_low_priority, 'enter_tag'] = 'L_cross_lowzone_priority'

        dataframe.loc[long_neutral & (dataframe['enter_long'] == 0), 'enter_long'] = 1
        dataframe.loc[long_neutral & (dataframe['enter_tag'].isna()), 'enter_tag'] = 'L_cross_neutral'

        short_high_priority = short_cross & (dataframe['in_high_zone'] == 1)
        short_neutral = short_cross & (dataframe['in_low_zone'] == 0)

        dataframe.loc[short_high_priority, 'enter_short'] = 1
        dataframe.loc[short_high_priority, 'enter_tag'] = 'S_cross_highzone_priority'

        dataframe.loc[short_neutral & (dataframe['enter_short'] == 0), 'enter_short'] = 1
        dataframe.loc[short_neutral & (dataframe['enter_tag'].isna()), 'enter_tag'] = 'S_cross_neutral'

        # If flat in backtest context, place limit-entry style signals near reaction levels
        dataframe.loc[(dataframe['touch_l1'] == 1) | (dataframe['touch_l2'] == 1), 'enter_long'] = 1
        dataframe.loc[(dataframe['touch_l1'] == 1) & (dataframe['enter_tag'].isna()), 'enter_tag'] = 'L_limit_l1'
        dataframe.loc[(dataframe['touch_l2'] == 1) & (dataframe['enter_tag'].isna()), 'enter_tag'] = 'L_limit_l2'

        dataframe.loc[(dataframe['touch_u1'] == 1) | (dataframe['touch_u2'] == 1), 'enter_short'] = 1
        dataframe.loc[(dataframe['touch_u1'] == 1) & (dataframe['enter_tag'].isna()), 'enter_tag'] = 'S_limit_u1'
        dataframe.loc[(dataframe['touch_u2'] == 1) & (dataframe['enter_tag'].isna()), 'enter_tag'] = 'S_limit_u2'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0

        dataframe.loc[
            (dataframe['cross_down'] == 1) |
            (dataframe['touch_u1'] == 1) |
            (dataframe['touch_u2'] == 1) |
            (dataframe['in_high_zone'] == 1) |
            (dataframe['above_high_zone'] == 1),
            'exit_long'
        ] = 1

        dataframe.loc[
            (dataframe['cross_up'] == 1) |
            (dataframe['touch_l1'] == 1) |
            (dataframe['touch_l2'] == 1) |
            (dataframe['in_low_zone'] == 1) |
            (dataframe['below_low_zone'] == 1),
            'exit_short'
        ] = 1

        return dataframe

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake, max_stake,
                            leverage, entry_tag, side, **kwargs):
        if proposed_stake is None:
            return None
        stake = proposed_stake / float(self.stake_split)
        if min_stake is not None:
            stake = max(stake, min_stake)
        if max_stake is not None:
            stake = min(stake, max_stake)
        return stake

    def adjust_trade_position(self, trade: Trade, current_time: datetime, current_rate: float, current_profit: float,
                              min_stake, max_stake, current_entry_rate, current_exit_rate,
                              current_entry_profit, current_exit_profit, **kwargs):
        if not hasattr(self, 'dp') or self.dp is None:
            return None

        df, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if df is None or len(df) < max(self.ma_fast_len, self.ma_slow_len) + 3:
            return None

        ma_fast = df['close'].rolling(self.ma_fast_len, min_periods=self.ma_fast_len).mean()
        ma_slow = df['close'].rolling(self.ma_slow_len, min_periods=self.ma_slow_len).mean()

        fast_now = ma_fast.iloc[-2]
        slow_now = ma_slow.iloc[-2]
        fast_prev = ma_fast.iloc[-3]
        slow_prev = ma_slow.iloc[-3]

        if any(v != v for v in [fast_now, slow_now, fast_prev, slow_prev]):
            return None

        c = df.iloc[-2]

        # zone reaction partial close first (u1/u2 for long, l1/l2 for short)
        if not trade.is_short:
            if bool(c.get('touch_u2', 0)) and current_profit > 0:
                reduce_amt = trade.stake_amount * 0.5
                if min_stake is not None:
                    reduce_amt = max(reduce_amt, min_stake)
                if max_stake is not None:
                    reduce_amt = min(reduce_amt, max_stake)
                if reduce_amt > 0:
                    return -reduce_amt
            if bool(c.get('touch_u1', 0)) and current_profit > 0:
                reduce_amt = trade.stake_amount * 0.25
                if min_stake is not None:
                    reduce_amt = max(reduce_amt, min_stake)
                if max_stake is not None:
                    reduce_amt = min(reduce_amt, max_stake)
                if reduce_amt > 0:
                    return -reduce_amt
        else:
            if bool(c.get('touch_l2', 0)) and current_profit > 0:
                reduce_amt = trade.stake_amount * 0.5
                if min_stake is not None:
                    reduce_amt = max(reduce_amt, min_stake)
                if max_stake is not None:
                    reduce_amt = min(reduce_amt, max_stake)
                if reduce_amt > 0:
                    return -reduce_amt
            if bool(c.get('touch_l1', 0)) and current_profit > 0:
                reduce_amt = trade.stake_amount * 0.25
                if min_stake is not None:
                    reduce_amt = max(reduce_amt, min_stake)
                if max_stake is not None:
                    reduce_amt = min(reduce_amt, max_stake)
                if reduce_amt > 0:
                    return -reduce_amt

        already_added = trade.nr_of_successful_entries - 1
        if already_added < int(self.max_entry_position_adjustment):
            if current_profit <= -float(self.dca_trigger):
                base_est = max(trade.stake_amount / float(self.stake_split), 0.0)
                add_stake = base_est
                if min_stake is not None:
                    add_stake = max(add_stake, min_stake)
                if max_stake is not None:
                    add_stake = min(add_stake, max_stake)
                if add_stake > 0:
                    return add_stake

        cross_down = (fast_prev >= slow_prev) and (fast_now < slow_now)
        cross_up = (fast_prev <= slow_prev) and (fast_now > slow_now)

        did_dca = trade.nr_of_successful_entries > 1
        profit_gate = current_profit > float(self.reduce_profit_buffer) if did_dca else current_profit > 0

        reduce_signal = False
        if (not trade.is_short) and cross_down:
            reduce_signal = True
        elif trade.is_short and cross_up:
            reduce_signal = True

        if reduce_signal and profit_gate:
            reduce_amt = trade.stake_amount * float(self.reduce_fraction)
            if min_stake is not None:
                reduce_amt = max(reduce_amt, min_stake)
            if max_stake is not None:
                reduce_amt = min(reduce_amt, max_stake)
            if reduce_amt > 0:
                return -reduce_amt

        return None
