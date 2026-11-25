import unittest

import numpy as np
import pandas as pd

from algotrader.ml import fit_logistic_regression


class LogisticModelTests(unittest.TestCase):
    def test_model_learns_simple_direction(self):
        rng = np.random.default_rng(7)
        x = rng.normal(size=500)
        y = (x + rng.normal(scale=0.2, size=500) > 0).astype(float)
        frame = pd.DataFrame({"x": x, "target": y})
        model = fit_logistic_regression(frame, ["x"], "target", epochs=200, learning_rate=0.08)
        self.assertIsNotNone(model)
        probs = model.predict_proba(pd.DataFrame({"x": [-2.0, 2.0]}))
        self.assertLess(probs.iloc[0], 0.5)
        self.assertGreater(probs.iloc[1], 0.5)


if __name__ == "__main__":
    unittest.main()

