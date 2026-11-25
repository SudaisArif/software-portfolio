from AlgorithmImports import *


class MLFactorRotationAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2024, 1, 1)
        self.SetCash(1000)
        self.symbols = [
            self.AddEquity(ticker, Resolution.Daily).Symbol
            for ticker in ["AMZN", "GOOGL", "NVDA"]
        ]
        self.target_weights = {
            "AMZN": 0.35,
            "GOOGL": 0.35,
            "NVDA": 0.35,
        }
        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.AfterMarketOpen("SPY", 35),
            self.Rebalance,
        )

    def Rebalance(self):
        for symbol in self.symbols:
            weight = self.target_weights.get(symbol.Value, 0.0)
            self.SetHoldings(symbol, weight)

