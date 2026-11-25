import unittest

from algotrader.alpaca import contract_id_to_option_symbol, option_symbol_to_contract_id


class AlpacaSymbolTests(unittest.TestCase):
    def test_contract_id_to_option_symbol(self):
        self.assertEqual(contract_id_to_option_symbol("AAPL_20240119_C_190"), "AAPL240119C00190000")

    def test_option_symbol_to_contract_id(self):
        self.assertEqual(option_symbol_to_contract_id("AAPL240119P00170000"), "AAPL_20240119_P_170")


if __name__ == "__main__":
    unittest.main()
