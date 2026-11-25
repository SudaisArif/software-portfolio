from typing import Dict, Iterable, List

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "ret_1d",
    "mom_5d",
    "mom_21d",
    "mom_63d",
    "trend_20d",
    "trend_50d",
    "rsi_14",
    "realized_vol_21d",
    "realized_vol_63d",
    "atr_pct_14d",
    "volume_z_20d",
    "market_mom_21d",
    "market_trend_200d",
    "vix_level",
    "vix_change_5d",
]


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    value = 100.0 - (100.0 / (1.0 + rs))
    return value.fillna(50.0)


def true_range(frame: pd.DataFrame) -> pd.Series:
    high = frame["High"]
    low = frame["Low"]
    prev_close = frame["Close"].shift(1)
    ranges = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def _asset_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["Close"]
    ret = close.pct_change()
    out = pd.DataFrame(index=frame.index)
    out["ret_1d"] = ret
    out["next_ret_1d"] = close.shift(-1) / close - 1.0
    out["forward_ret_5d"] = close.shift(-5) / close - 1.0
    out["mom_5d"] = close / close.shift(5) - 1.0
    out["mom_21d"] = close / close.shift(21) - 1.0
    out["mom_63d"] = close / close.shift(63) - 1.0
    out["trend_20d"] = close / close.rolling(20).mean() - 1.0
    out["trend_50d"] = close / close.rolling(50).mean() - 1.0
    out["rsi_14"] = (rsi(close, 14) - 50.0) / 50.0
    out["realized_vol_21d"] = ret.rolling(21).std() * np.sqrt(252.0)
    out["realized_vol_63d"] = ret.rolling(63).std() * np.sqrt(252.0)
    out["atr_pct_14d"] = true_range(frame).rolling(14).mean() / close
    vol_mean = frame["Volume"].rolling(20).mean()
    vol_std = frame["Volume"].rolling(20).std()
    out["volume_z_20d"] = (frame["Volume"] - vol_mean) / vol_std.replace(0.0, np.nan)
    return out


def _market_features(market: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    market_close = market["Close"]
    vix_close = vix["Close"] if vix is not None and not vix.empty else pd.Series(index=market.index, dtype=float)
    out = pd.DataFrame(index=market.index)
    out["market_mom_21d"] = market_close / market_close.shift(21) - 1.0
    out["market_trend_200d"] = market_close / market_close.rolling(200).mean() - 1.0
    out["vix_level"] = vix_close.reindex(market.index).ffill()
    out["vix_change_5d"] = out["vix_level"] / out["vix_level"].shift(5) - 1.0
    return out


def build_feature_panel(
    prices: Dict[str, pd.DataFrame],
    tradable_symbols: Iterable[str],
    market_symbol: str,
    vix_symbol: str,
) -> pd.DataFrame:
    market = prices[market_symbol]
    vix = prices.get(vix_symbol)
    market_feature_frame = _market_features(market, vix)

    frames: List[pd.DataFrame] = []
    for symbol in tradable_symbols:
        frame = prices[symbol]
        asset = _asset_features(frame)
        asset = asset.join(market_feature_frame, how="left").ffill()
        asset["Symbol"] = symbol
        frames.append(asset.reset_index().rename(columns={"index": "Date"}))

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.rename(columns={panel.columns[0]: "Date"})
    panel["Date"] = pd.to_datetime(panel["Date"]).dt.tz_localize(None)
    panel = panel.set_index(["Date", "Symbol"]).sort_index()
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel["target_up"] = (panel["next_ret_1d"] > 0.0).astype(float)
    panel["target_up_5d"] = (panel["forward_ret_5d"] > 0.0).astype(float)
    return panel


def cross_sectional_zscore(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = frame.copy()
    for col in columns:
        grouped = out[col].groupby(level="Date")
        mean = grouped.transform("mean")
        std = grouped.transform("std").replace(0.0, np.nan)
        out[f"{col}_xsz"] = ((out[col] - mean) / std).clip(-3.0, 3.0)
    return out
