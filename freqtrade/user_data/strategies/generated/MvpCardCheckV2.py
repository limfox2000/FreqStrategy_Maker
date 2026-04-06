"""
AI-composed Strategy Artifact
preset=deepseek-chat
provider=deepseek
model=deepseek-chat
mode=chat
reasoning=medium
persona=你是一位精通数学与统计学的加密货币量化策略专家，尤其擅长将**数学方法**（时间序列、概率论、线性代数、信号处理）转化为**可运行的 Freqtrade 策略代码**。你对技术指标的计算原理、数值稳定性、滞后性与过拟合成因有深刻理解，能设计
sources={'indicator_factor': 'mod_20260404_064349_1447f2', 'position_adjustment': 'mod_20260404_064359_975976', 'risk_system': 'mod_20260404_064405_956aa2'}
"""

from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


class MvpCardCheckV2(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 240

    minimal_roi = {
    "0": 0.04,
    "60": 0.02,
    "120": 0.01,
    "240": 0
    }
    stoploss = -0.06
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True
    use_exit_signal = True
    exit_profit_only = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 计算EMA 12和EMA 26
        dataframe['ema_12'] = ta.EMA(dataframe, timeperiod=12)
        dataframe['ema_26'] = ta.EMA(dataframe, timeperiod=26)
        # 计算MACD及其信号线
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']
        # 计算RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        return dataframe


    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头入场条件：EMA金叉（12上穿26）且MACD确认（MACD > 信号线）且RSI > 45
        dataframe.loc[
            (
                (dataframe['ema_12'] > dataframe['ema_26']) &
                (dataframe['macd'] > dataframe['macdsignal']) &
                (dataframe['rsi'] > 45)
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'ema_macd_rsi_long')
        # 空头入场条件：EMA死叉（12下穿26）且MACD确认（MACD < 信号线）且RSI < 55（作为对称参考，用户未指定，设为55）
        dataframe.loc[
            (
                (dataframe['ema_12'] < dataframe['ema_26']) &
                (dataframe['macd'] < dataframe['macdsignal']) &
                (dataframe['rsi'] < 55)
            ),
            ['enter_short', 'enter_tag']
        ] = (1, 'ema_macd_rsi_short')
        return dataframe


    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 多头离场条件：EMA死叉（12下穿26）或MACD转弱（MACD < 信号线）
        dataframe.loc[
            (
                (dataframe['ema_12'] < dataframe['ema_26']) |
                (dataframe['macd'] < dataframe['macdsignal'])
            ),
            'exit_long'
        ] = 1
        # 空头离场条件：EMA金叉（12上穿26）或MACD转强（MACD > 信号线）
        dataframe.loc[
            (
                (dataframe['ema_12'] > dataframe['ema_26']) |
                (dataframe['macd'] > dataframe['macdsignal'])
            ),
            'exit_short'
        ] = 1
        return dataframe

    position_adjustment_enable = True
    max_entry_position_adjustment = 3
    stake_split = 3

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                           proposed_stake: float, min_stake: Optional[float], max_stake: float,
                           leverage: float, entry_tag: Optional[str], side: str,
                           **kwargs) -> float:
        if entry_tag:
            return proposed_stake / self.stake_split
        return proposed_stake


    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: Optional[float], max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_liquidation_rate: float, leverage: float,
                              entry_tag: Optional[str], side: str, **kwargs) -> Optional[Union[float, Tuple[float, str]]]:
        if trade.nr_of_successful_entries >= self.max_entry_position_adjustment:
            return None
        if current_profit <= -0.03:
            stake_amount = self.wallets.get_trade_stake_amount(trade.pair, None)
            adjusted_stake = stake_amount / self.stake_split
            if adjusted_stake >= min_stake:
                return adjusted_stake, 'add_at_drawdown'
        if current_profit >= 0.05:
            return -trade.stake_amount * 0.5, 'reduce_at_profit'
        return None
