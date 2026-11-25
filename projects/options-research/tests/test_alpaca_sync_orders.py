import unittest

from scripts.alpaca_sync_orders import symbol_from_contract_id


class AlpacaSyncOrdersTests(unittest.TestCase):
    def test_symbol_from_contract_id(self):
        self.assertEqual(symbol_from_contract_id("GOOGL_20260515_C_370.0"), "GOOGL")


if __name__ == "__main__":
    unittest.main()
