from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, Union

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, IntParameter

import pandas as pd
import numpy as np

class MvpComposeVerify(IStrategy):
    """
    MvpComposeVerify Strategy
    Integrates EMA cross with RSI filtering, position scaling, and trailing stop risk management.
    """
    
    # Strategy metadata
    INTERFACE_VERSION = 3
    timeframe = '1m'
    can_short = True
    
    # Risk system parameters (from risk_system module)
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
    
    # Position adjustment parameters (from position_adjustment module)
    position_adjustment_enable = True
    max_entry_position_adjustment = 3
    stake_split = 3
    
    # Hyperparameters for optimization
    ema_short_period = IntParameter(10, 30, default=20, space='buy')
    ema_long_period = IntParameter(40, 80, default=60, space='buy')
    rsi_period = IntParameter(10, 20, default=14, space='buy')
    rsi_overbought = IntParameter(60, 80, default=70, space='buy')
    rsi_oversold = IntParameter(20, 40, default=30, space='buy')
    
    # Required columns for Freqtrade interface
    def informative_pairs(self):
        return []
    
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Calculate technical indicators: EMA20, EMA60, RSI, and cross signals.
        Mathematical formulation:
        EMA_t(α) = α * Price_t + (1-α) * EMA_{t-1}, where α = 2/(N+1)
        RSI_t = 100 - 100/(1 + RS_t), RS_t = AvgGain_t / AvgLoss_t over 14 periods
        Cross signal: sgn(EMA20 - EMA60) ∈ {-1, 0, 1}
        """
        
        # Calculate EMAs with dynamic periods for optimization
        ema_short = self.ema_short_period.value
        ema_long = self.ema_long_period.value
        
        dataframe['ema_short'] = ta.EMA(dataframe, timeperiod=ema_short)
        dataframe['ema_long'] = ta.EMA(dataframe, timeperiod=ema_long)
        
        # Calculate RSI with dynamic period
        rsi_period_val = self.rsi_period.value
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=rsi_period_val)
        
        # Calculate EMA cross signal using vectorized operations
        # Cross signal: 1 when short EMA > long EMA, -1 when short EMA < long EMA
        dataframe['ema_cross'] = 0
        dataframe.loc[dataframe['ema_short'] > dataframe['ema_long'], 'ema_cross'] = 1
        dataframe.loc[dataframe['ema_short'] < dataframe['ema_long'], 'ema_cross'] = -1
        
        # Note: For the first (ema_short + ema_long) bars, EMA values are NaN due to warmup.
        # This creates boundary effects but prevents lookahead bias.
        
        return dataframe
    
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Generate entry signals based on EMA cross with RSI filtering.
        Mathematical conditions:
        Long entry: EMA_short crosses above EMA_long ∧ RSI < RSI_overbought
        Short entry: EMA_short crosses below EMA_long ∧ RSI > RSI_oversold
        Cross detection: cross_t = 1 if (signal_t = 1 ∧ signal_{t-1} = -1) else 0
        """
        
        # Get dynamic RSI thresholds
        rsi_ob = self.rsi_overbought.value
        rsi_os = self.rsi_oversold.value
        
        # Initialize entry columns
        dataframe.loc[:, 'enter_long'] = 0
        dataframe.loc[:, 'enter_short'] = 0
        dataframe.loc[:, 'enter_tag'] = ''
        
        # Long entry condition: EMA short crosses above EMA long AND RSI not overbought
        long_mask = (
            (dataframe['ema_cross'] == 1) &
            (dataframe['ema_cross'].shift(1) == -1) &
            (dataframe['rsi'] < rsi_ob)
        )
        dataframe.loc[long_mask, 'enter_long'] = 1
        dataframe.loc[long_mask, 'enter_tag'] = 'ema_cross_long'
        
        # Short entry condition: EMA short crosses below EMA long AND RSI not oversold
        short_mask = (
            (dataframe['ema_cross'] == -1) &
            (dataframe['ema_cross'].shift(1) == 1) &
            (dataframe['rsi'] > rsi_os)
        )
        dataframe.loc[short_mask, 'enter_short'] = 1
        dataframe.loc[short_mask, 'enter_tag'] = 'ema_cross_short'
        
        return dataframe
    
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Generate exit signals based on EMA cross reversal.
        Mathematical conditions:
        Exit long: EMA_short crosses below EMA_long
        Exit short: EMA_short crosses above EMA_long
        """
        
        # Initialize exit columns
        dataframe.loc[:, 'exit_long'] = 0
        dataframe.loc[:, 'exit_short'] = 0
        
        # Exit long condition: EMA short crosses below EMA long
        exit_long_mask = (
            (dataframe['ema_cross'] == -1) &
            (dataframe['ema_cross'].shift(1) == 1)
        )
        dataframe.loc[exit_long_mask, 'exit_long'] = 1
        
        # Exit short condition: EMA short crosses above EMA long
        exit_short_mask = (
            (dataframe['ema_cross'] == 1) &
            (dataframe['ema_cross'].shift(1) == -1)
        )
        dataframe.loc[exit_short_mask, 'exit_short'] = 1
        
        return dataframe
    
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: Optional[float], max_stake: float,
                            leverage: float, entry_tag: Optional[str], side: str,
                            **kwargs) -> float:
        """
        Split total position into 3 equal parts for phased entry.
        Mathematical: stake_per_entry = total_stake / stake_split
        """
        return proposed_stake / self.stake_split
    
    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: Optional[float], max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_liquidation_rate: float, leverage: float,
                              entry_tag: Optional[str], side: str, **kwargs) -> Union[Tuple[Optional[float], Optional[str]], Optional[float]]:
        """
        Position adjustment logic with mathematical conditions:
        Add position: if current_profit ≤ -3% and entry count < max_entries
        Reduce position: if current_profit ≥ +5%, close 50% of position
        """
        
        # Add position condition: loss reaches -3%
        if current_profit <= -0.03:
            # Check if maximum entries reached
            if trade.nr_of_successful_entries >= self.max_entry_position_adjustment:
                return None
            
            # Calculate stake amount for one split
            stake_amount = trade.stake_amount / self.stake_split
            
            # Ensure total position doesn't exceed max stake
            if trade.stake_amount + stake_amount <= max_stake:
                return stake_amount, "add_on_dip"
        
        # Reduce position condition: profit reaches +5%
        elif current_profit >= 0.05:
            # Calculate 50% of current position
            reduce_amount = trade.amount * 0.5
            
            # Ensure remaining position is positive
            if trade.amount - reduce_amount > 0:
                # Negative value indicates position reduction
                return -reduce_amount, "take_partial_profit"
        
        return None
    
    # Fix: Add missing required methods for IStrategy interface
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Legacy method for backward compatibility.
        Maps to populate_entry_trend for long entries.
        """
        dataframe = self.populate_entry_trend(dataframe, metadata)
        dataframe['buy'] = dataframe['enter_long']
        return dataframe
    
    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Legacy method for backward compatibility.
        Maps to populate_exit_trend for long exits.
        """
        dataframe = self.populate_exit_trend(dataframe, metadata)
        dataframe['sell'] = dataframe['exit_long']
        return dataframe
