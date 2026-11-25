import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.apply_paper_fills import POSITION_COLUMNS, prune_profit_locks


class ProfitLockCleanupTests(unittest.TestCase):
    def test_prune_profit_locks_keeps_only_open_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            locks = pd.DataFrame(
                [
                    {"contract_id": "AAPL_20260515_C_280", "armed": True, "max_pnl_pct": 2.1},
                    {"contract_id": "GOOGL_20260515_C_370", "armed": True, "max_pnl_pct": 2.2},
                ]
            )
            locks.to_csv(state_dir / "profit_locks.csv", index=False)
            positions = pd.DataFrame(
                [
                    {
                        "contract_id": "AAPL_20260515_C_280",
                        "underlying_symbol": "AAPL",
                        "expiration": pd.Timestamp("2026-05-15"),
                        "strike": 280.0,
                        "option_type": "C",
                        "quantity": 1,
                        "entry_date": pd.Timestamp("2026-05-01"),
                        "entry_price": 4.0,
                        "entry_cost": 400.0,
                    }
                ],
                columns=POSITION_COLUMNS,
            )

            prune_profit_locks(state_dir, positions)

            out = pd.read_csv(state_dir / "profit_locks.csv")
            self.assertEqual(out["contract_id"].tolist(), ["AAPL_20260515_C_280"])


if __name__ == "__main__":
    unittest.main()
