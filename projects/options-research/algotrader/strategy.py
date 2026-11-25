from typing import Dict

import numpy as np
import pandas as pd

from .config import ModelConfig, StrategyConfig
from .features import FEATURE_COLUMNS, cross_sectional_zscore
from .ml import walk_forward_predict


def add_model_signal(panel: pd.DataFrame, model_config: ModelConfig) -> pd.DataFrame:
    features = FEATURE_COLUMNS
    scored = panel.copy()
    scored["ml_probability"] = walk_forward_predict(
        scored,
        feature_names=features,
        target_name=model_config.target_name,
        min_train_days=model_config.min_train_days,
        train_window_days=model_config.train_window_days,
        retrain_every_days=model_config.retrain_every_days,
        l2=model_config.l2,
        epochs=model_config.epochs,
        learning_rate=model_config.learning_rate,
    )
    scored["ml_edge"] = scored["ml_probability"] - 0.5
    return scored


def add_factor_signal(panel: pd.DataFrame) -> pd.DataFrame:
    scored = cross_sectional_zscore(panel, ["mom_21d", "mom_63d", "trend_50d", "volume_z_20d"])
    scored["factor_score"] = (
        0.30 * scored["mom_21d_xsz"].fillna(0.0)
        + 0.25 * scored["mom_63d_xsz"].fillna(0.0)
        + 0.20 * scored["trend_50d_xsz"].fillna(0.0)
        + 0.10 * scored["volume_z_20d_xsz"].fillna(0.0)
        - 0.15 * scored["rsi_14"].fillna(0.0).clip(lower=0.0)
    )
    return scored


def _risk_on_scale(date_frame: pd.DataFrame, config: StrategyConfig) -> float:
    market_values = date_frame["market_trend_200d"].dropna()
    vix_values = date_frame["vix_level"].dropna()
    market_trend = float(market_values.median()) if not market_values.empty else -1.0
    vix = float(vix_values.median()) if not vix_values.empty else np.nan
    if market_trend < 0.0 or (np.isfinite(vix) and vix >= config.vix_risk_off_level):
        return config.risk_off_gross_exposure
    return config.max_gross_exposure


def construct_target_weights(
    scored_panel: pd.DataFrame,
    config: StrategyConfig,
) -> pd.DataFrame:
    dates = sorted(scored_panel.index.get_level_values("Date").unique())
    symbols = sorted(scored_panel.index.get_level_values("Symbol").unique())
    weights = pd.DataFrame(0.0, index=pd.Index(dates, name="Date"), columns=symbols)

    panel = scored_panel.copy()
    panel["combined_signal"] = (
        0.65 * panel["ml_edge"].fillna(0.0) * 10.0
        + 0.35 * panel["factor_score"].fillna(0.0)
    )
    panel["vol_for_size"] = panel["realized_vol_21d"].fillna(panel["realized_vol_63d"]).clip(lower=0.08, upper=1.25)

    for date in dates:
        date_frame = panel.loc[(date, slice(None)), :].copy()
        date_frame.index = date_frame.index.droplevel("Date")
        gross = _risk_on_scale(date_frame, config)
        candidates = date_frame[
            (date_frame["combined_signal"] > config.signal_threshold)
            & (date_frame["ml_probability"].fillna(0.0) >= 0.50)
        ].copy()
        if candidates.empty or gross <= 0.0:
            continue

        candidates = candidates.sort_values("combined_signal", ascending=False).head(config.max_positions)
        strength = candidates["combined_signal"].clip(lower=0.0)
        inv_vol = 1.0 / candidates["vol_for_size"]
        raw = strength * inv_vol
        if raw.sum() <= 0.0:
            continue
        target = raw / raw.sum() * gross
        target = target.clip(upper=config.max_position_weight)
        if target.sum() > gross:
            target = target / target.sum() * gross
        weights.loc[date, target.index] = target

    return weights.fillna(0.0)


def latest_allocation(weights: pd.DataFrame, prices: pd.DataFrame, initial_cash: float) -> pd.DataFrame:
    latest_date = weights.index.max()
    latest_weights = weights.loc[latest_date]
    latest_prices = prices.reindex(weights.index).ffill().loc[latest_date]
    rows = []
    for symbol, weight in latest_weights[latest_weights.abs() > 1e-6].sort_values(ascending=False).items():
        price = float(latest_prices[symbol])
        dollars = initial_cash * float(weight)
        rows.append(
            {
                "Date": latest_date,
                "Symbol": symbol,
                "TargetWeight": float(weight),
                "TargetDollarsPer1000": dollars,
                "ApproxSharesPer1000": dollars / price if price > 0.0 else 0.0,
                "Close": price,
            }
        )
    return pd.DataFrame(rows)


def build_strategy(
    panel: pd.DataFrame,
    model_config: ModelConfig,
    strategy_config: StrategyConfig,
) -> pd.DataFrame:
    scored = add_model_signal(panel, model_config)
    scored = add_factor_signal(scored)
    return scored
