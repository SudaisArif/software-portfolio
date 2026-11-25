import unittest

import pandas as pd

from algotrader.intraday_options import run_intraday_long_option_replay
from algotrader.option_chain import OptionBacktestConfig


def quote_rows(bids, asks):
    timestamps = pd.to_datetime(
        [
            "2025-01-02 09:45",
            "2025-01-02 09:50",
            "2025-01-02 09:55",
        ]
    )
    rows = []
    for timestamp, bid, ask in zip(timestamps, bids, asks):
        rows.append(
            {
                "timestamp": timestamp,
                "underlying_symbol": "XYZ",
                "expiration": pd.Timestamp("2025-01-31"),
                "strike": 105.0,
                "option_type": "C",
                "bid": bid,
                "ask": ask,
                "underlying_price": 100.0,
                "mid": (bid + ask) / 2.0,
                "spread_pct": (ask - bid) / ((bid + ask) / 2.0),
                "contract_id": "XYZ_20250131_C_105.0",
            }
        )
    return pd.DataFrame(rows)


class IntradayOptionReplayTests(unittest.TestCase):
    def test_intraday_stop_loss_exits_before_daily_close(self):
        quotes = quote_rows([4.0, 2.4, 2.2], [4.1, 2.6, 2.4])
        weights = pd.DataFrame({"XYZ": [1.0]}, index=[pd.Timestamp("2025-01-02")])
        result = run_intraday_long_option_replay(
            quotes,
            weights,
            1000.0,
            OptionBacktestConfig(
                min_dte=14,
                max_dte=45,
                max_premium_fraction=0.50,
                max_total_premium_fraction=0.80,
                min_contract_price=0.0,
                min_otm_pct=0.0,
                max_otm_pct=0.10,
                stop_loss=0.35,
                take_profit=3.0,
                max_hold_days=30,
            ),
            entry_start_time="09:45",
            entry_end_time="09:45",
            check_frequency_minutes=5,
        )
        sells = result["orders"][result["orders"]["action"] == "SELL"]
        self.assertEqual(str(sells.iloc[0]["reason"]), "stop_loss")
        self.assertEqual(pd.Timestamp(sells.iloc[0]["timestamp"]), pd.Timestamp("2025-01-02 09:50"))

    def test_intraday_profit_lock_exits_after_floor_break(self):
        quotes = quote_rows([4.0, 13.0, 11.9], [4.1, 13.4, 12.2])
        weights = pd.DataFrame({"XYZ": [1.0]}, index=[pd.Timestamp("2025-01-02")])
        result = run_intraday_long_option_replay(
            quotes,
            weights,
            1000.0,
            OptionBacktestConfig(
                min_dte=14,
                max_dte=45,
                max_premium_fraction=0.50,
                max_total_premium_fraction=0.80,
                min_contract_price=0.0,
                min_otm_pct=0.0,
                max_otm_pct=0.10,
                stop_loss=0.90,
                take_profit=3.0,
                profit_lock_activation=2.0,
                profit_lock_floor=2.0,
                profit_lock_trail=0.50,
                max_hold_days=30,
            ),
            entry_start_time="09:45",
            entry_end_time="09:45",
            check_frequency_minutes=5,
        )
        sells = result["orders"][result["orders"]["action"] == "SELL"]
        self.assertEqual(str(sells.iloc[0]["reason"]), "profit_lock_floor")
        self.assertEqual(pd.Timestamp(sells.iloc[0]["timestamp"]), pd.Timestamp("2025-01-02 09:55"))


if __name__ == "__main__":
    unittest.main()
