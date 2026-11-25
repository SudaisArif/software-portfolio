from dataclasses import dataclass
from typing import Iterable, List, Optional
import warnings

import numpy as np
import pandas as pd


@dataclass
class LogisticModel:
    mean_: np.ndarray
    scale_: np.ndarray
    coef_: np.ndarray
    intercept_: float
    feature_names: List[str]

    def predict_proba(self, frame: pd.DataFrame) -> pd.Series:
        x = frame[self.feature_names].astype(float).values
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        x = (x - self.mean_) / self.scale_
        logits = x @ self.coef_ + self.intercept_
        probs = sigmoid(logits)
        return pd.Series(probs, index=frame.index)


def sigmoid(x: np.ndarray) -> np.ndarray:
    clipped = np.clip(x, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def fit_logistic_regression(
    frame: pd.DataFrame,
    feature_names: Iterable[str],
    target_name: str,
    l2: float = 2.0,
    epochs: int = 300,
    learning_rate: float = 0.04,
) -> Optional[LogisticModel]:
    """Fit a stable L2-regularized linear probability model with logistic scoring.

    The closed-form ridge step is intentionally used instead of iterative gradient
    descent so research runs remain stable on noisy free market data.
    """
    names = list(feature_names)
    data = frame[names + [target_name]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 200 or data[target_name].nunique() < 2:
        return None

    x = data[names].astype(float).values
    y = data[target_name].astype(float).values
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(x, axis=0)
        scale = np.nanstd(x, axis=0)
    scale[scale < 1e-8] = 1.0
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        return None
    x = np.nan_to_num((x - mean) / scale, nan=0.0, posinf=0.0, neginf=0.0)
    x = np.clip(x, -8.0, 8.0)

    centered_target = y - y.mean()
    penalty = np.eye(x.shape[1]) * max(l2, 1e-8)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with np.errstate(all="ignore"):
            xtx = (x.T @ x) / float(len(y))
            xty = (x.T @ centered_target) / float(len(y))
    if not np.isfinite(xtx).all() or not np.isfinite(xty).all():
        return None
    try:
        coef = np.linalg.solve(xtx + penalty, xty)
    except np.linalg.LinAlgError:
        coef = np.linalg.lstsq(xtx + penalty, xty, rcond=None)[0]
    coef = np.nan_to_num(coef, nan=0.0, posinf=0.0, neginf=0.0) * 10.0
    coef = np.clip(coef, -2.0, 2.0)
    prior = np.clip(y.mean(), 1e-4, 1.0 - 1e-4)
    intercept = float(np.log(prior / (1.0 - prior)))

    return LogisticModel(mean, scale, coef, intercept, names)


def walk_forward_predict(
    panel: pd.DataFrame,
    feature_names: Iterable[str],
    target_name: str,
    min_train_days: int,
    train_window_days: int,
    retrain_every_days: int,
    l2: float,
    epochs: int,
    learning_rate: float,
) -> pd.Series:
    """Generate strictly walk-forward probabilities at each date/symbol row."""
    dates = pd.Index(sorted(panel.index.get_level_values("Date").unique()))
    predictions = pd.Series(np.nan, index=panel.index, dtype=float)
    model: Optional[LogisticModel] = None
    last_retrain_index = -10**9

    for idx, date in enumerate(dates):
        if idx < min_train_days:
            continue
        if model is None or idx - last_retrain_index >= retrain_every_days:
            start_idx = max(0, idx - train_window_days)
            train_dates = dates[start_idx:idx]
            train_frame = panel.loc[(train_dates, slice(None)), :]
            model = fit_logistic_regression(
                train_frame,
                feature_names=feature_names,
                target_name=target_name,
                l2=l2,
                epochs=epochs,
                learning_rate=learning_rate,
            )
            last_retrain_index = idx
        if model is None:
            continue
        predict_frame = panel.loc[(date, slice(None)), :]
        predictions.loc[(date, slice(None))] = model.predict_proba(predict_frame)
    return predictions.clip(0.01, 0.99)
