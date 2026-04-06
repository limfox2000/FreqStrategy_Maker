from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

import freqtrade.vendor.qtpylib.indicators as qtpylib

"""
AI-composed Strategy Artifact
preset=deepseek-chat
provider=deepseek
model=deepseek-chat
mode=chat
reasoning=medium
persona=你是一位精通数学与统计学的加密货币量化策略专家，尤其擅长将**数学方法**（时间序列、概率论、线性代数、信号处理）转化为**可运行的 Freqtrade 策略代码**。你对技术指标的计算原理、数值稳定性、滞后性与过拟合成因有深刻理解，能设计
sources={'indicator_factor': 'mod_20260404_081557_91ee4c', 'position_adjustment': 'mod_20260404_081611_f07d64', 'risk_system': 'mod_20260404_081617_282838'}
"""

import freqtrade.vendor.qtpylib.indicators as qtpylib

import freqtrade.vendor.qtpylib.indicators as qtpylib
import pandas as pd
class ComposeValidateCheck(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '5m'
    can_short = True
    
    # Risk system parameters
    minimal_roi = {
        "0": 0.04
    }
    stoploss = -0.06
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True
    use_exit_signal = True
    exit_profit_only = False
    
    # Position adjustment parameters
    position_adjustment_enable = True
    max_entry_position_adjustment = 3
    stake_split = 3
    
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 计算EMA指标
        dataframe['ema20'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema60'] = ta.EMA(dataframe, timeperiod=60)

        # 计算RSI指标
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # 计算EMA交叉信号
        dataframe['ema_cross'] = 0
        dataframe.loc[dataframe['ema20'] > dataframe['ema60'], 'ema_cross'] = 1
        dataframe.loc[dataframe['ema20'] < dataframe['ema60'], 'ema_cross'] = -1

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头入场条件：EMA20上穿EMA60且RSI<70（不过热）
        dataframe.loc[
            (
                (dataframe['ema_cross'] == 1) &
                (dataframe['ema_cross'].shift(1) == -1) &
                (dataframe['rsi'] < 70)
            ),
            'enter_long'] = 1
        dataframe.loc[dataframe['enter_long'] == 1, 'enter_tag'] = 'ema_cross_long'

        # 空头入场条件：EMA20下穿EMA60且RSI>30（不超卖）
        dataframe.loc[
            (
                (dataframe['ema_cross'] == -1) &
                (dataframe['ema_cross'].shift(1) == 1) &
                (dataframe['rsi'] > 30)
            ),
            'enter_short'] = 1
        dataframe.loc[dataframe['enter_short'] == 1, 'enter_tag'] = 'ema_cross_short'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头离场条件：EMA20下穿EMA60
        dataframe.loc[
            (
                (dataframe['ema_cross'] == -1) &
                (dataframe['ema_cross'].shift(1) == 1)
            ),
            'exit_long'] = 1

        # 空头离场条件：EMA20上穿EMA60
        dataframe.loc[
            (
                (dataframe['ema_cross'] == 1) &
                (dataframe['ema_cross'].shift(1) == -1)
            ),
            'exit_short'] = 1

        return dataframe
    
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        """
        将总仓位资金分为3等份，用于分批入场。
        """
        return proposed_stake / self.stake_split

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_liquidation_rate: float, leverage: float,
                              entry_tag: str | None, side: str, **kwargs) -> tuple[float | None, str | None]:
        """
        根据当前盈亏进行加减仓。
        加仓条件：当前亏损达到-3%。
        减仓条件：当前盈利达到+5%，平掉50%的仓位。
        """
        if current_profit <= -0.03:
            # 加仓逻辑：亏损达到-3%时，增加一份仓位
            # 检查是否已达到最大加仓次数
            if trade.nr_of_successful_entries >= self.max_entry_position_adjustment:
                return None, None
            # 计算单份仓位价值
            stake_amount = trade.stake_amount / self.stake_split
            # 确保加仓后总仓位不超过最大允许仓位
            if trade.stake_amount + stake_amount <= max_stake:
                return stake_amount, "add_on_dip"

        elif current_profit >= 0.05:
            # 减仓逻辑：盈利达到+5%时，平掉50%的仓位
            # 计算需要平仓的数量（当前持仓量的一半）
            reduce_amount = trade.amount * 0.5
            # 确保平仓后不会导致仓位过小
            if trade.amount - reduce_amount > 0:
                # 返回负值表示减仓
                return -reduce_amount, "take_partial_profit"

        return None, None
