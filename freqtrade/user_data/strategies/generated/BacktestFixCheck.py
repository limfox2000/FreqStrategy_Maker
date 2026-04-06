"""
AI-composed Strategy Artifact
preset=deepseek-chat
provider=deepseek
model=deepseek-chat
mode=chat
reasoning=medium
persona=你是一位精通数学与统计学的加密货币量化策略专家，尤其擅长将**数学方法**（时间序列、概率论、线性代数、信号处理）转化为**可运行的 Freqtrade 策略代码**。你对技术指标的计算原理、数值稳定性、滞后性与过拟合成因有深刻理解，能设计
sources={'indicator_factor': 'mod_20260404_075136_18feac', 'position_adjustment': 'mod_20260404_075148_e7590f', 'risk_system': 'mod_20260404_075155_3a5bc0'}
"""

from __future__ import annotations

from datetime import datetime

import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
class BacktestFixCheck(IStrategy):
    """
    结合EMA交叉、RSI过滤、分步入场、动态仓位调整与风险管理的综合策略。
    """
    INTERFACE_VERSION = 3
    timeframe = '5m'
    can_short = True

    # --- 风险系统参数 (Module 3) ---
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

    # --- 仓位调整参数 (Module 2) ---
    position_adjustment_enable = True
    max_entry_position_adjustment = 3
    stake_split = 3

    # --- 策略参数 ---
    # EMA周期参数
    ema_short_period = IntParameter(10, 30, default=20, space="buy", optimize=True)
    ema_long_period = IntParameter(50, 100, default=60, space="buy", optimize=True)
    # RSI参数
    rsi_period = IntParameter(10, 20, default=14, space="buy", optimize=True)
    rsi_overbought = IntParameter(65, 80, default=70, space="sell", optimize=True)
    rsi_oversold = IntParameter(20, 35, default=30, space="sell", optimize=True)
    # 仓位调整阈值参数
    add_position_threshold = RealParameter(-0.05, -0.01, default=-0.03, space="protection", optimize=True)
    reduce_position_threshold = RealParameter(0.02, 0.08, default=0.05, space="protection", optimize=True)
    reduce_position_ratio = RealParameter(0.3, 0.7, default=0.5, space="protection", optimize=True)

    def version(self) -> str:
        return "1.0"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        计算技术指标：EMA与RSI。
        数学原理：
        - EMA_t = α * Price_t + (1-α) * EMA_{t-1}, 其中 α = 2/(N+1)
        - RSI_t = 100 - 100/(1 + RS), RS = AvgGain / AvgLoss (使用指数移动平均)
        边界效应：前N-1个数据点（N为最大周期60）的EMA与RSI因窗口不完整而不可靠。
        """
        # 计算EMA指标
        dataframe['ema_short'] = ta.EMA(dataframe, timeperiod=self.ema_short_period.value)
        dataframe['ema_long'] = ta.EMA(dataframe, timeperiod=self.ema_long_period.value)
        # 计算RSI指标
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=self.rsi_period.value)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        生成入场信号。
        数学条件（多头）：
        Let C_t = I(ema_short_t > ema_long_t) ∧ I(ema_short_{t-1} ≤ ema_long_{t-1})  (金叉事件)
        Let R_t = I(rsi_t < rsi_overbought)  (非超买)
        Entry_long_t = C_t ∧ R_t
        空头条件对称。
        """
        # 多头入场条件：EMA短线上穿长线 且 RSI < 超买阈值
        dataframe.loc[
            (
                (dataframe['ema_short'] > dataframe['ema_long']) &
                (dataframe['ema_short'].shift(1) <= dataframe['ema_long'].shift(1)) &
                (dataframe['rsi'] < self.rsi_overbought.value)
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'ema_cross_rsi_filter')
        # 空头入场条件：EMA短线下穿长线 且 RSI > 超卖阈值
        dataframe.loc[
            (
                (dataframe['ema_short'] < dataframe['ema_long']) &
                (dataframe['ema_short'].shift(1) >= dataframe['ema_long'].shift(1)) &
                (dataframe['rsi'] > self.rsi_oversold.value)
            ),
            ['enter_short', 'enter_tag']
        ] = (1, 'ema_cross_rsi_filter')
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        生成出场信号（与风险系统的止盈止损并行）。
        数学条件（多头离场）：
        Exit_long_t = I(ema_short_t < ema_long_t ∧ ema_short_{t-1} ≥ ema_long_{t-1}) ∨ I(rsi_t > rsi_overbought)
        空头条件对称。
        """
        # 多头离场条件：EMA短线下穿长线 或 RSI > 超买阈值
        dataframe.loc[
            (
                (dataframe['ema_short'] < dataframe['ema_long']) &
                (dataframe['ema_short'].shift(1) >= dataframe['ema_long'].shift(1))
            ) | (dataframe['rsi'] > self.rsi_overbought.value),
            'exit_long'
        ] = 1
        # 空头离场条件：EMA短线上穿长线 或 RSI < 超卖阈值
        dataframe.loc[
            (
                (dataframe['ema_short'] > dataframe['ema_long']) &
                (dataframe['ema_short'].shift(1) <= dataframe['ema_long'].shift(1))
            ) | (dataframe['rsi'] < self.rsi_oversold.value),
            'exit_short'
        ] = 1
        return dataframe

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                           proposed_stake: float, min_stake: float | None, max_stake: float,
                           leverage: float, entry_tag: str | None, side: str,
                           **kwargs) -> float:
        """
        将总仓位分成 stake_split 份，每次入场使用 1/stake_split 的仓位。
        数学原理：等分仓位管理，降低单次入场风险。
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
                              **kwargs) -> tuple[float | None, str | None] | None:
        """
        根据当前盈亏动态调整仓位。
        数学条件：
        - 加仓：若 current_profit ≤ add_position_threshold 且入场次数未达上限，则增加一份初始仓位。
        - 减仓：若 current_profit ≥ reduce_position_threshold，则平仓 reduce_position_ratio 比例的现有仓位。
        注意：所有计算基于已实现盈亏，无未来偏差。
        """
        # 检查是否已达到最大加仓次数
        if trade.nr_of_successful_entries >= self.max_entry_position_adjustment:
            return None

        # 加仓条件：亏损达到阈值
        if current_profit <= self.add_position_threshold.value:
            stake_amount = self.wallets.get_trade_stake_amount(trade.pair, None)
            if stake_amount is not None and (min_stake is None or stake_amount >= min_stake):
                return stake_amount, f'add_at_{self.add_position_threshold.value:.2%}'

        # 减仓条件：盈利达到阈值
        if current_profit >= self.reduce_position_threshold.value:
            if min_stake is None or trade.stake_amount > min_stake:
                reduce_amount = -trade.stake_amount * self.reduce_position_ratio.value
                return reduce_amount, f'reduce_{self.reduce_position_ratio.value:.0%}_at_{self.reduce_position_threshold.value:.2%}'

        return None

    # 数学参数优化建议：
    # 1. ema_short_period / ema_long_period: 控制趋势响应的灵敏度与滞后性。比值决定交叉频率。
    # 2. rsi_period: RSI平滑窗口，影响超买超卖信号的噪声水平。
    # 3. rsi_overbought / rsi_oversold: 阈值概率，需适配资产波动特性（如加密货币通常更高）。
    # 4. add_position_threshold: 凯利公式或波动率缩放下的加仓风险阈值。
    # 5. reduce_position_threshold/ratio: 部分止盈的期望值优化参数。

    # 数学上的失效条件：
    # 1. 市场非平稳（趋势突变）：EMA交叉产生大量假信号。
    # 2. 厚尾分布（极端波动）：RSI阈值失效，止损被击穿。
    # 3. 低波动震荡市：EMA持续缠绕，无趋势可循。
    # 4. 自相关性突变：指标滞后性导致信号延迟。
