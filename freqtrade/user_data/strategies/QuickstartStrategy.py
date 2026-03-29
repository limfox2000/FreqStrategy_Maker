from pandas import DataFrame

from freqtrade.strategy import IStrategy


class QuickstartStrategy(IStrategy):
    INTERFACE_VERSION = 3

    can_short = False
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 50
    use_exit_signal = True

    minimal_roi = {
        "0": 0.02
    }

    stoploss = -0.10

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0
        return dataframe
