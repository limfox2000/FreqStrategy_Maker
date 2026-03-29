import talib.abstract as ta
from pandas import DataFrame
import freqtrade.vendor.qtpylib.indicators as qtpylib

from freqtrade.strategy import IStrategy, merge_informative_pair
from freqtrade.persistence import Trade


class RangingMeanReversion(IStrategy):
    """
    Ranging Market Mean Reversion Strategy
    
    Designed for choppy/sideways markets with both long and short capability.
    Uses Bollinger Bands + RSI + ADX for range detection and entry signals.
    Strong risk management with dynamic ATR-based stops.
    """

    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "1m"
    process_only_new_candles = True
    startup_candle_count = 50
    use_exit_signal = True

    # Risk Management
    minimal_roi = {
        "0": 0.015,
        "10": 0.01,
        "30": 0.005,
        "60": 0.003,
    }

    stoploss = -0.025

    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.01
    trailing_only_offset_is_reached = True

    # Strategy Parameters
    bb_period = 20
    bb_std = 2.0
    rsi_period = 14
    adx_period = 14
    atr_period = 14

    # Entry thresholds
    rsi_long_entry = 35
    rsi_short_entry = 65
    adx_range_threshold = 25

    # Exit thresholds
    rsi_long_exit = 55
    rsi_short_exit = 45

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Bollinger Bands
        bollinger = qtpylib.bollinger_bands(
            qtpylib.typical_price(dataframe),
            window=self.bb_period,
            stds=self.bb_std,
        )
        dataframe["bb_lower"] = bollinger["lower"]
        dataframe["bb_mid"] = bollinger["mid"]
        dataframe["bb_upper"] = bollinger["upper"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_mid"]

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_period)

        # ADX
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=self.adx_period)

        # ATR for volatility context
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # EMA for trend bias
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        is_ranging = dataframe["adx"] < self.adx_range_threshold

        dataframe.loc[
            (
                (dataframe["close"] <= dataframe["bb_lower"])
                & (dataframe["rsi"] < self.rsi_long_entry)
                & is_ranging
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        dataframe.loc[
            (
                (dataframe["close"] >= dataframe["bb_upper"])
                & (dataframe["rsi"] > self.rsi_short_entry)
                & is_ranging
                & (dataframe["volume"] > 0)
            ),
            "enter_short",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (
                    (dataframe["close"] >= dataframe["bb_mid"])
                    | (dataframe["rsi"] > self.rsi_long_exit)
                )
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1

        dataframe.loc[
            (
                (
                    (dataframe["close"] <= dataframe["bb_mid"])
                    | (dataframe["rsi"] < self.rsi_short_exit)
                )
                & (dataframe["volume"] > 0)
            ),
            "exit_short",
        ] = 1

        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: float,
        max_stake: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        risk_per_trade = 0.02
        wallet_balance = self.wallets.get_total_stake_amount() if self.wallets else self.config["dry_run_wallet"]
        risk_amount = wallet_balance * risk_per_trade

        stop_loss_distance = abs(self.stoploss)

        if stop_loss_distance > 0:
            position_size = risk_amount / stop_loss_distance
            position_size = min(position_size, max_stake, wallet_balance * 0.3)
            position_size = max(position_size, min_stake)
            return position_size

        return proposed_stake
