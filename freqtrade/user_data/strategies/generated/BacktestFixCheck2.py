"""
AI-composed Strategy Artifact
preset=deepseek-chat
provider=deepseek
model=deepseek-chat
mode=chat
reasoning=medium
persona=你是一位精通数学与统计学的加密货币量化策略专家，尤其擅长将**数学方法**（时间序列、概率论、线性代数、信号处理）转化为**可运行的 Freqtrade 策略代码**。你对技术指标的计算原理、数值稳定性、滞后性与过拟合成因有深刻理解，能设计
sources={'indicator_factor': 'mod_20260404_075435_9011ae', 'position_adjustment': 'mod_20260404_075447_052aab', 'risk_system': 'mod_20260404_075453_0b3fc4'}
"""

from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

import pandas as pd
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
from datetime import datetime, timedelta

class BacktestFixCheck2(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '5m'
    can_short = True
    
    # 风险系统参数
    minimal_roi = {
        "0": 0.04,
        "30": 0.02,
        "60": 0.01,
        "120": 0
    }
    stoploss = -0.06
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True
    use_exit_signal = True
    exit_profit_only = False
    
    # 仓位调整参数
    position_adjustment_enable = True
    max_entry_position_adjustment = 3
    stake_split = 3
    
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 计算EMA指标 - 指数移动平均，赋予近期价格更高权重
        # EMA(20): 短期趋势，EMA(60): 中长期趋势
        dataframe['ema_20'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_60'] = ta.EMA(dataframe, timeperiod=60)
        
        # 计算RSI指标 - 相对强弱指数，衡量价格动量
        # RSI(14): 14周期内涨跌幅的相对强度，范围[0,100]
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头入场条件：EMA20上穿EMA60（金叉）且 RSI < 70（过滤超买）
        # 数学条件：EMA20(t) > EMA60(t) ∧ EMA20(t-1) ≤ EMA60(t-1) ∧ RSI(t) < 70
        dataframe.loc[
            (
                (dataframe['ema_20'] > dataframe['ema_60']) &
                (dataframe['ema_20'].shift(1) <= dataframe['ema_60'].shift(1)) &
                (dataframe['rsi'] < 70)
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'ema_cross_rsi_filter')
        
        # 空头入场条件：EMA20下穿EMA60（死叉）且 RSI > 30（过滤超卖）
        # 数学条件：EMA20(t) < EMA60(t) ∧ EMA20(t-1) ≥ EMA60(t-1) ∧ RSI(t) > 30
        dataframe.loc[
            (
                (dataframe['ema_20'] < dataframe['ema_60']) &
                (dataframe['ema_20'].shift(1) >= dataframe['ema_60'].shift(1)) &
                (dataframe['rsi'] > 30)
            ),
            ['enter_short', 'enter_tag']
        ] = (1, 'ema_cross_rsi_filter')
        
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头离场条件：EMA20下穿EMA60（死叉）或 RSI > 80（超买）
        # 数学条件：[EMA20(t) < EMA60(t) ∧ EMA20(t-1) ≥ EMA60(t-1)] ∨ RSI(t) > 80
        dataframe.loc[
            (
                (dataframe['ema_20'] < dataframe['ema_60']) &
                (dataframe['ema_20'].shift(1) >= dataframe['ema_60'].shift(1))
            ) | (dataframe['rsi'] > 80),
            'exit_long'
        ] = 1
        
        # 空头离场条件：EMA20上穿EMA60（金叉）或 RSI < 20（超卖）
        # 数学条件：[EMA20(t) > EMA60(t) ∧ EMA20(t-1) ≤ EMA60(t-1)] ∨ RSI(t) < 20
        dataframe.loc[
            (
                (dataframe['ema_20'] > dataframe['ema_60']) &
                (dataframe['ema_20'].shift(1) <= dataframe['ema_60'].shift(1))
            ) | (dataframe['rsi'] < 20),
            'exit_short'
        ] = 1
        
        return dataframe
    
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        """
        将总仓位分成3份，每次入场使用1/3的仓位。
        数学原理：仓位分拆降低单次入场风险，符合凯利公式的风险分散原则
        """
        if self.stake_split > 0:
            stake_per_entry = proposed_stake / self.stake_split
            return stake_per_entry
        return proposed_stake

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_liquidation_rate: float, leverage: float,
                              entry_tag: str | None, side: str, **kwargs) -> tuple[float | None, str | None] | None:
        """
        根据当前盈亏调整仓位。
        加仓条件：当前亏损达到-3%时，加仓一份（总仓位的1/3）。
        减仓条件：当前盈利达到+5%时，平掉50%的仓位。
        
        数学原理：
        1. 亏损加仓：基于均值回归假设，在-3%亏损时加仓降低平均成本
        2. 盈利减仓：在+5%盈利时锁定部分利润，降低风险暴露
        """
        if trade.nr_of_successful_entries >= self.max_entry_position_adjustment:
            return None

        if current_profit <= -0.03:
            stake_amount = self.wallets.get_trade_stake_amount(trade.pair, None)
            if stake_amount is not None and stake_amount >= min_stake:
                return stake_amount, "add_position_due_to_loss"

        if current_profit >= 0.05:
            if trade.stake_amount > min_stake:
                reduce_amount = -trade.stake_amount * 0.5
                return reduce_amount, "reduce_position_due_to_profit"

        return None
