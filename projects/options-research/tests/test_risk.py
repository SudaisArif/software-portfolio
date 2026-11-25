import unittest

from algotrader.risk import ProfitLockConfig, option_exit_reason, update_profit_lock_state


class ProfitLockRuleTests(unittest.TestCase):
    def test_large_profit_arms_without_immediate_exit(self):
        config = ProfitLockConfig(activation=2.0, floor=2.0, trail=0.15)
        armed, max_pnl = update_profit_lock_state(2.12, False, None, config)

        self.assertTrue(armed)
        self.assertAlmostEqual(max_pnl, 2.12)
        self.assertEqual(
            option_exit_reason(2.12, 2, 14, 0.35, 2.25, 5, 5, armed, max_pnl, config),
            "",
        )

    def test_armed_position_exits_when_profit_floor_breaks(self):
        config = ProfitLockConfig(activation=2.0, floor=2.0, trail=0.15)
        armed, max_pnl = update_profit_lock_state(1.95, True, 2.12, config)

        self.assertTrue(armed)
        self.assertEqual(
            option_exit_reason(1.95, 2, 14, 0.35, 2.25, 5, 5, armed, max_pnl, config),
            "profit_lock_floor",
        )

    def test_armed_position_exits_on_trailing_giveback(self):
        config = ProfitLockConfig(activation=2.0, floor=2.0, trail=0.15)
        armed, max_pnl = update_profit_lock_state(2.14, True, 2.35, config)

        self.assertTrue(armed)
        self.assertEqual(
            option_exit_reason(2.14, 2, 14, 0.35, 2.25, 5, 5, armed, max_pnl, config),
            "profit_lock_trail",
        )

    def test_take_profit_keeps_priority(self):
        config = ProfitLockConfig(activation=2.0, floor=2.0, trail=0.15)
        self.assertEqual(
            option_exit_reason(2.30, 2, 14, 0.35, 2.25, 5, 5, True, 2.35, config),
            "take_profit",
        )


if __name__ == "__main__":
    unittest.main()
