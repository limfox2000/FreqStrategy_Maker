from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, CategoricalParameter
from pair_profile_helper import get_pair_float, get_pair_int

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

    trade_direction = CategoricalParameter(["onlyLong", "onlyShort", "bothway"], default="bothway", space="buy")

    position_adjustment_enable = True
    max_entry_position_adjustment = 1
    stake_split = 2.0
    dca_trigger = 0.012
    reduce_profit_buffer = 0.0015

    add_below_mid = 0.30
    reduce_below_mid = 0.20
    add_low_zone = 0.40
    reduce_low_zone = 0.20

    reduce_above_mid = 0.30
    add_above_mid = 0.20
    reduce_high_zone = 0.50
    add_high_zone = 0.20

    base_ema_len = IntParameter(120, 200, default=144, space='buy')
    base_offset = DecimalParameter(0.008, 0.03, default=0.01618, decimals=5, space='buy')
    zone_step = DecimalParameter(0.002, 0.012, default=0.005, decimals=4, space='buy')
    vwma_len = IntParameter(9, 9, default=9, space='buy')

    order_types = {
        'entry': 'limit',
        'exit': 'limit',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
    }

    @staticmethod
    def _cross_up(a, b):
        return (a > b) & (a.shift(1) <= b.shift(1))

    @staticmethod
    def _cross_down(a, b):
        return (a < b) & (a.shift(1) >= b.shift(1))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair_key = str(metadata.get('pair') or '')
        legacy_base_ema_len = get_pair_int(pair_key, "base_ema_len", int(self.base_ema_len.value))
        base_ema_len = max(1, get_pair_int(pair_key, "Matrix_baseEMA_len", legacy_base_ema_len))
        base_offset = get_pair_float(pair_key, "base_offset", float(self.base_offset.value))
        zone_step = get_pair_float(pair_key, "zone_step", float(self.zone_step.value))
        vwma_len = max(1, get_pair_int(pair_key, "vwma_len", int(self.vwma_len.value)))

        dataframe['ema_mid'] = ta.EMA(dataframe, timeperiod=base_ema_len)

        b = base_offset
        s = zone_step

        dataframe['u1'] = dataframe['ema_mid'] * (1.0 + b)
        dataframe['u2'] = dataframe['ema_mid'] * (1.0 + b + s)
        dataframe['u3'] = dataframe['ema_mid'] * (1.0 + b + 2.0 * s)

        dataframe['l1'] = dataframe['ema_mid'] * (1.0 - b)
        dataframe['l2'] = dataframe['ema_mid'] * (1.0 - b - s)
        dataframe['l3'] = dataframe['ema_mid'] * (1.0 - b - 2.0 * s)

        dataframe['in_high_zone'] = ((dataframe['close'] >= dataframe['u1']) & (dataframe['close'] <= dataframe['u3'])).astype('int8')
        dataframe['in_low_zone'] = ((dataframe['close'] <= dataframe['l1']) & (dataframe['close'] >= dataframe['l3'])).astype('int8')
        dataframe['above_high_zone'] = (dataframe['close'] > dataframe['u3']).astype('int8')
        dataframe['below_low_zone'] = (dataframe['close'] < dataframe['l3']).astype('int8')

        price_vwma1 = dataframe['high'].where(dataframe['close'] >= dataframe['open'], dataframe['low'])
        price_vwma2 = dataframe['low'].where(dataframe['close'] >= dataframe['open'], dataframe['high'])
        vol = dataframe['volume']
        w = vwma_len

        vol_sum = vol.rolling(w, min_periods=w).sum()
        dataframe['vwma1'] = (price_vwma1 * vol).rolling(w, min_periods=w).sum() / vol_sum.replace(0, float('nan'))
        dataframe['vwma2'] = (price_vwma2 * vol).rolling(w, min_periods=w).sum() / vol_sum.replace(0, float('nan'))

        dataframe['cross_up'] = self._cross_up(dataframe['vwma1'], dataframe['vwma2']).astype('int8')
        dataframe['cross_down'] = self._cross_down(dataframe['vwma1'], dataframe['vwma2']).astype('int8')

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0
        dataframe['enter_tag'] = None

        long_cross = dataframe['cross_up'] == 1
        short_cross = dataframe['cross_down'] == 1

        dataframe.loc[long_cross, 'enter_long'] = 1
        dataframe.loc[long_cross, 'enter_tag'] = 'L_vwma_cross_up'

        dataframe.loc[short_cross, 'enter_short'] = 1
        dataframe.loc[short_cross, 'enter_tag'] = 'S_vwma_cross_down'

        mode = self.trade_direction.value
        if mode == 'onlyLong':
            dataframe['enter_short'] = 0
        elif mode == 'onlyShort':
            dataframe['enter_long'] = 0

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0

        dataframe.loc[dataframe['cross_down'] == 1, 'exit_long'] = 1
        dataframe.loc[dataframe['cross_up'] == 1, 'exit_short'] = 1

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
        if df is None or len(df) < 3:
            return None

        c = df.iloc[-2]
        p = df.iloc[-3]

        if any(col not in c for col in ['vwma1', 'vwma2', 'ema_mid', 'in_low_zone', 'in_high_zone']):
            return None

        v1_now = c['vwma1']
        v2_now = c['vwma2']
        v1_prev = p['vwma1']
        v2_prev = p['vwma2']

        if any(v != v for v in [v1_now, v2_now, v1_prev, v2_prev]):
            return None

        cross_up = (v1_prev <= v2_prev) and (v1_now > v2_now)
        cross_down = (v1_prev >= v2_prev) and (v1_now < v2_now)

        in_low_zone = bool(int(c['in_low_zone']) == 1)
        in_high_zone = bool(int(c['in_high_zone']) == 1)
        below_mid = bool(c['close'] < c['ema_mid']) if c['ema_mid'] == c['ema_mid'] else False

        already_added = trade.nr_of_successful_entries - 1
        if already_added < int(self.max_entry_position_adjustment) and current_profit <= -float(self.dca_trigger):
            base_est = max(trade.stake_amount / float(self.stake_split), 0.0)

            if in_low_zone:
                add_frac = float(self.add_low_zone)
            elif in_high_zone:
                add_frac = float(self.add_high_zone)
            else:
                add_frac = float(self.add_below_mid if below_mid else self.add_above_mid)

            add_stake = base_est * add_frac
            if min_stake is not None:
                add_stake = max(add_stake, min_stake)
            if max_stake is not None:
                add_stake = min(add_stake, max_stake)
            if add_stake > 0:
                return add_stake

        did_dca = trade.nr_of_successful_entries > 1
        profit_gate = current_profit > float(self.reduce_profit_buffer) if did_dca else current_profit > 0

        reduce_signal = (not trade.is_short and cross_down) or (trade.is_short and cross_up)

        if reduce_signal and profit_gate:
            if in_high_zone:
                reduce_frac = float(self.reduce_high_zone)
            elif in_low_zone:
                reduce_frac = float(self.reduce_low_zone)
            else:
                reduce_frac = float(self.reduce_below_mid if below_mid else self.reduce_above_mid)

            reduce_amt = trade.stake_amount * reduce_frac
            if min_stake is not None:
                reduce_amt = max(reduce_amt, min_stake)
            if max_stake is not None:
                reduce_amt = min(reduce_amt, max_stake)
            if reduce_amt > 0:
                return -reduce_amt

        return None
