import unittest

from algotrader.options import (
    black_scholes_greeks,
    black_scholes_price,
    implied_volatility,
    implied_volatility_inverse_gaussian,
)


class BlackScholesTests(unittest.TestCase):
    def test_known_call_price(self):
        price = black_scholes_price(100.0, 100.0, 1.0, 0.05, 0.20, "call")
        self.assertAlmostEqual(price, 10.4506, places=3)

    def test_put_call_parity_without_dividend(self):
        call = black_scholes_price(100.0, 95.0, 0.5, 0.03, 0.25, "call")
        put = black_scholes_price(100.0, 95.0, 0.5, 0.03, 0.25, "put")
        parity_gap = call - put - (100.0 - 95.0 * 2.718281828459045 ** (-0.03 * 0.5))
        self.assertAlmostEqual(parity_gap, 0.0, places=6)

    def test_implied_volatility_round_trip(self):
        price = black_scholes_price(100.0, 105.0, 0.75, 0.04, 0.33, "put")
        iv = implied_volatility(price, 100.0, 105.0, 0.75, 0.04, "put")
        self.assertAlmostEqual(iv, 0.33, places=4)

    def test_inverse_gaussian_implied_volatility_round_trip(self):
        for option_type in ["call", "put"]:
            price = black_scholes_price(100.0, 105.0, 0.75, 0.04, 0.33, option_type)
            iv = implied_volatility_inverse_gaussian(price, 100.0, 105.0, 0.75, 0.04, option_type)
            self.assertAlmostEqual(iv, 0.33, places=5)

    def test_inverse_gaussian_atm_round_trip(self):
        price = black_scholes_price(100.0, 100.0, 0.5, 0.0, 0.27, "call")
        iv = implied_volatility_inverse_gaussian(price, 100.0, 100.0, 0.5, 0.0, "call")
        self.assertAlmostEqual(iv, 0.27, places=5)

    def test_greeks_shape(self):
        greeks = black_scholes_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "call")
        self.assertGreater(greeks.delta, 0.0)
        self.assertGreater(greeks.gamma, 0.0)
        self.assertGreater(greeks.vega, 0.0)


if __name__ == "__main__":
    unittest.main()
