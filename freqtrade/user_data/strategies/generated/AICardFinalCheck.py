"""
AI-composed Strategy Artifact
preset=deepseek-chat
provider=deepseek
model=deepseek-chat
mode=chat
reasoning=medium
persona=你是一位精通数学与统计学的加密货币量化策略专家，尤其擅长将**数学方法**（时间序列、概率论、线性代数、信号处理）转化为**可运行的 Freqtrade 策略代码**。你对技术指标的计算原理、数值稳定性、滞后性与过拟合成因有深刻理解，能设计
sources={'indicator_factor': 'mod_20260404_072303_a661ee', 'position_adjustment': 'mod_20260404_072317_0a7dab', 'risk_system': 'mod_20260404_072323_d97fea'}
"""

import freqtrade.vendor.qtpylib.indicators as qtpylib
import talib.abstract as ta
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, Decimal, stoploss_from_open, TrailingStopLoss

class AICardFinalCheck(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = '15m'
    can_short = True
    
    # --- 仓位调整模块参数 ---
    position_adjustment_enable = True
    max_entry_position_adjustment = 3
    stake_split = 3
    add_threshold = -0.03
    reduce_threshold = 0.05
    reduce_ratio = 0.5
    
    # --- 风险系统模块参数 ---
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
    ignore_roi_if_entry_signal = False
    
    # --- 策略核心参数 ---
    process_only_new_candles = True
    use_exit_signal = True
    startup_candle_count = 50  # 确保EMA26和MACD有足够数据
    
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 计算EMA12和EMA26
        dataframe['ema12'] = ta.EMA(dataframe, timeperiod=12)
        dataframe['ema26'] = ta.EMA(dataframe, timeperiod=26)
        # 计算MACD及其信号线
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']
        # 计算RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        return dataframe
    
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头入场逻辑：EMA12上穿EMA26（金叉），MACD线在信号线上方（MACD确认），且RSI > 45
        dataframe.loc[
            (
                (qtpylib.crossed_above(dataframe['ema12'], dataframe['ema26'])) &
                (dataframe['macd'] > dataframe['macdsignal']) &
                (dataframe['rsi'] > 45)
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'ema_macd_rsi_long')
        
        # 空头入场逻辑：EMA12下穿EMA26（死叉），MACD线在信号线下方（MACD确认），且RSI < 55
        dataframe.loc[
            (
                (qtpylib.crossed_below(dataframe['ema12'], dataframe['ema26'])) &
                (dataframe['macd'] < dataframe['macdsignal']) &
                (dataframe['rsi'] < 55)
            ),
            ['enter_short', 'enter_tag']
        ] = (1, 'ema_macd_rsi_short')
        
        return dataframe
    
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头离场逻辑：EMA12下穿EMA26（死叉）或MACD线下穿信号线
        dataframe.loc[
            (
                (qtpylib.crossed_below(dataframe['ema12'], dataframe['ema26'])) |
                (qtpylib.crossed_below(dataframe['macd'], dataframe['macdsignal']))
            ),
            'exit_long'
        ] = 1
        
        # 空头离场逻辑：EMA12上穿EMA26（金叉）或MACD线上穿信号线
        dataframe.loc[
            (
                (qtpylib.crossed_above(dataframe['ema12'], dataframe['ema26'])) |
                (qtpylib.crossed_above(dataframe['macd'], dataframe['macdsignal']))
            ),
            'exit_short'
        ] = 1
        
        return dataframe
    
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                           proposed_stake: float, min_stake: float | None, max_stake: float,
                           leverage: float, entry_tag: str | None, side: str,
                           **kwargs) -> float:
        """
        将总仓位分成3份，每次入场只使用一份。
        """
        if self.stake_split > 1:
            return proposed_stake / self.stake_split
        return proposed_stake
    
    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_liquidation_rate: float, leverage: float,
                              entry_tag: str | None, side: str, **kwargs) -> tuple[float | None, str | None] | None:
        """
        根据需求执行加减仓逻辑：
        1. 在浮亏-3%时加仓一次。
        2. 在浮盈+5%时减仓50%。
        """
        if trade.nr_of_successful_entries >= self.max_entry_position_adjustment:
            return None
        
        if current_profit <= self.add_threshold:
            if trade.nr_of_successful_entries < self.stake_split:
                return (trade.stake_amount, f"add_on_drawdown_{current_profit:.2%}")
        
        if current_profit >= self.reduce_threshold:
            if trade.nr_of_successful_exits == 0:
                return (-trade.stake_amount * self.reduce_ratio, f"reduce_on_profit_{current_profit:.2%}")
        
        return None