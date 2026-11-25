import unittest

import pandas as pd

from algotrader.option_chain import OptionBacktestConfig, run_long_call_backtest


class OptionChainBacktestTests(unittest.TestCase):
    def test_long_call_backtest_accepts_real_chain_shape(self):
        dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
        rows = []
        for idx, date in enumerate(dates):
            rows.append(
                {
                    "quote_date": date,
                    "underlying_symbol": "XYZ",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 100.0,
                    "option_type": "C",
                    "bid": 4.0 + idx,
                    "ask": 4.2 + idx,
                    "last": 4.1 + idx,
                    "volume": 100,
                    "open_interest": 500,
                    "implied_volatility": 0.4,
                    "delta": 0.45,
                    "gamma": 0.02,
                    "theta": -0.03,
                    "vega": 0.1,
                    "rho": 0.01,
                    "underlying_price": 100.0 + idx,
                    "mid": 4.1 + idx,
                    "spread_pct": 0.2 / (4.1 + idx),
                    "contract_id": "XYZ_20250131_C_100.0",
                }
            )
        chain = pd.DataFrame(rows)
        weights = pd.DataFrame({"XYZ": [1.0, 1.0, 0.0]}, index=dates)
        result = run_long_call_backtest(
            chain,
            weights,
            1000.0,
            OptionBacktestConfig(max_hold_days=1, max_premium_fraction=0.50),
        )
        self.assertFalse(result["equity"].empty)
        self.assertGreaterEqual(len(result["orders"]), 2)

    def test_missing_liquidity_fields_are_optional(self):
        dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
        rows = []
        for idx, date in enumerate(dates):
            rows.append(
                {
                    "quote_date": date,
                    "underlying_symbol": "XYZ",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 100.0,
                    "option_type": "C",
                    "bid": 4.0 + idx,
                    "ask": 4.1 + idx,
                    "volume": pd.NA,
                    "open_interest": pd.NA,
                    "underlying_price": 100.0,
                    "mid": 4.05 + idx,
                    "spread_pct": 0.1 / (4.05 + idx),
                    "contract_id": "XYZ_20250131_C_100.0",
                }
            )
        chain = pd.DataFrame(rows)
        weights = pd.DataFrame({"XYZ": [1.0, 1.0]}, index=dates)
        result = run_long_call_backtest(
            chain,
            weights,
            1000.0,
            OptionBacktestConfig(max_hold_days=1, max_premium_fraction=0.50),
        )
        self.assertFalse(result["orders"].empty)

    def test_total_premium_cap_limits_new_positions(self):
        date = pd.Timestamp("2025-01-02")
        rows = []
        for symbol in ["AAA", "BBB", "CCC"]:
            rows.append(
                {
                    "quote_date": date,
                    "underlying_symbol": symbol,
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 100.0,
                    "option_type": "C",
                    "bid": 2.9,
                    "ask": 3.0,
                    "underlying_price": 100.0,
                    "mid": 2.95,
                    "spread_pct": 0.1 / 2.95,
                    "contract_id": f"{symbol}_20250131_C_100.0",
                }
            )
        chain = pd.DataFrame(rows)
        weights = pd.DataFrame({"AAA": [1.0], "BBB": [1.0], "CCC": [1.0]}, index=[date])
        result = run_long_call_backtest(
            chain,
            weights,
            1000.0,
            OptionBacktestConfig(max_premium_fraction=0.40, max_total_premium_fraction=0.70),
        )
        buys = result["orders"][result["orders"]["action"] == "BUY"]
        self.assertEqual(len(buys), 2)

    def test_close_on_monthly_loss_stop_liquidates_positions(self):
        dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
        rows = []
        for idx, date in enumerate(dates):
            rows.append(
                {
                    "quote_date": date,
                    "underlying_symbol": "XYZ",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 100.0,
                    "option_type": "C",
                    "bid": [4.0, 1.0][idx],
                    "ask": [4.1, 1.2][idx],
                    "underlying_price": 100.0,
                    "mid": [4.05, 1.1][idx],
                    "spread_pct": 0.1 / [4.05, 1.1][idx],
                    "contract_id": "XYZ_20250131_C_100.0",
                }
            )
        chain = pd.DataFrame(rows)
        weights = pd.DataFrame({"XYZ": [1.0, 1.0]}, index=dates)
        result = run_long_call_backtest(
            chain,
            weights,
            1000.0,
            OptionBacktestConfig(
                monthly_loss_stop=0.10,
                close_on_monthly_loss_stop=True,
                stop_loss=0.90,
                max_premium_fraction=0.50,
            ),
        )
        self.assertEqual(int(result["equity"]["open_positions"].iloc[-1]), 0)
        self.assertIn("monthly_loss_stop", set(result["events"]["event"]))

    def test_negative_weight_can_buy_put_when_enabled(self):
        date = pd.Timestamp("2025-01-02")
        chain = pd.DataFrame(
            [
                {
                    "quote_date": date,
                    "underlying_symbol": "XYZ",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 95.0,
                    "option_type": "P",
                    "bid": 2.9,
                    "ask": 3.0,
                    "underlying_price": 100.0,
                    "mid": 2.95,
                    "spread_pct": 0.1 / 2.95,
                    "contract_id": "XYZ_20250131_P_95.0",
                },
                {
                    "quote_date": date,
                    "underlying_symbol": "XYZ",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 105.0,
                    "option_type": "C",
                    "bid": 2.9,
                    "ask": 3.0,
                    "underlying_price": 100.0,
                    "mid": 2.95,
                    "spread_pct": 0.1 / 2.95,
                    "contract_id": "XYZ_20250131_C_105.0",
                },
            ]
        )
        weights = pd.DataFrame({"XYZ": [-1.0]}, index=[date])
        result = run_long_call_backtest(
            chain,
            weights,
            1000.0,
            OptionBacktestConfig(
                allow_put_entries=True,
                max_premium_fraction=0.50,
                min_otm_pct=0.0,
                max_otm_pct=0.10,
            ),
        )
        buys = result["orders"][result["orders"]["action"] == "BUY"]
        self.assertEqual(str(buys.iloc[0]["contract_id"]), "XYZ_20250131_P_95.0")

    def test_symbol_specific_moneyness_override(self):
        date = pd.Timestamp("2025-01-02")
        chain = pd.DataFrame(
            [
                {
                    "quote_date": date,
                    "underlying_symbol": "GLD",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 101.0,
                    "option_type": "C",
                    "bid": 2.9,
                    "ask": 3.0,
                    "underlying_price": 100.0,
                    "mid": 2.95,
                    "spread_pct": 0.1 / 2.95,
                    "contract_id": "GLD_20250131_C_101.0",
                },
                {
                    "quote_date": date,
                    "underlying_symbol": "GLD",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 105.0,
                    "option_type": "C",
                    "bid": 1.9,
                    "ask": 2.0,
                    "underlying_price": 100.0,
                    "mid": 1.95,
                    "spread_pct": 0.1 / 1.95,
                    "contract_id": "GLD_20250131_C_105.0",
                },
            ]
        )
        weights = pd.DataFrame({"GLD": [1.0]}, index=[date])
        result = run_long_call_backtest(
            chain,
            weights,
            1000.0,
            OptionBacktestConfig(
                min_otm_pct=0.04,
                max_otm_pct=0.08,
                min_otm_pct_by_symbol={"GLD": None},
                max_otm_pct_by_symbol={"GLD": 0.02},
                max_premium_fraction=0.50,
            ),
        )
        buys = result["orders"][result["orders"]["action"] == "BUY"]
        self.assertEqual(str(buys.iloc[0]["contract_id"]), "GLD_20250131_C_101.0")

    def test_profit_lock_exits_after_floor_break(self):
        dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
        rows = []
        for date, bid, ask in zip(dates, [4.0, 13.0, 11.9], [4.1, 13.4, 12.2]):
            rows.append(
                {
                    "quote_date": date,
                    "underlying_symbol": "XYZ",
                    "expiration": pd.Timestamp("2025-01-31"),
                    "strike": 100.0,
                    "option_type": "C",
                    "bid": bid,
                    "ask": ask,
                    "underlying_price": 100.0,
                    "mid": (bid + ask) / 2.0,
                    "spread_pct": (ask - bid) / ((bid + ask) / 2.0),
                    "contract_id": "XYZ_20250131_C_100.0",
                }
            )
        chain = pd.DataFrame(rows)
        weights = pd.DataFrame({"XYZ": [1.0, 1.0, 1.0]}, index=dates)
        result = run_long_call_backtest(
            chain,
            weights,
            1000.0,
            OptionBacktestConfig(
                max_premium_fraction=0.50,
                take_profit=3.00,
                stop_loss=0.90,
                max_hold_days=30,
                profit_lock_activation=2.0,
                profit_lock_floor=2.0,
                profit_lock_trail=0.50,
            ),
        )
        sells = result["orders"][result["orders"]["action"] == "SELL"]
        self.assertEqual(str(sells.iloc[0]["reason"]), "profit_lock_floor")


if __name__ == "__main__":
    unittest.main()
