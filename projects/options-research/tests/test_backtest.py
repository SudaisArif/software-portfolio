import unittest

import pandas as pd

from algotrader.backtest import run_backtest
from algotrader.config import StrategyConfig


class BacktestTests(unittest.TestCase):
    def test_simple_positive_asset(self):
        dates = pd.date_range("2024-01-01", periods=5, freq="D")
        close = pd.DataFrame({"SPY": [100, 101, 102, 103, 104]}, index=dates)
        weights = pd.DataFrame({"SPY": [1, 1, 1, 1, 1]}, index=dates)
        result = run_backtest(close, weights, 1000.0, StrategyConfig(transaction_cost_bps=0.0), "SPY")
        self.assertGreater(result.equity_curve.iloc[-1], 1000.0)
        self.assertAlmostEqual(result.benchmark_equity.iloc[-1], 1040.0)


if __name__ == "__main__":
    unittest.main()

