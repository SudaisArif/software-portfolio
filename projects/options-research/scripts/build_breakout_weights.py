#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.config import ResearchConfig
from algotrader.data import download_prices
from algotrader.features import build_feature_panel, cross_sectional_zscore


def parse_args():
    parser = argparse.ArgumentParser(description="Build simple breakout-style weights for options experiments.")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-04-24")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/breakout_weights")
    return parser.parse_args()


def build_weights(scored, symbols, score_col, max_positions=3, exclude=()):
    dates = sorted(scored.index.get_level_values("Date").unique())
    out = pd.DataFrame(0.0, index=pd.Index(dates, name="Date"), columns=symbols)
    exclude = {symbol.upper() for symbol in exclude}
    for date in dates:
        frame = scored.loc[(date, slice(None)), :].copy()
        frame.index = frame.index.droplevel("Date")
        frame = frame[~frame.index.isin(exclude)]
        candidates = frame[
            (frame[score_col] > 0.0)
            & (frame["mom_5d"] > 0.0)
            & (frame["mom_21d"] > 0.0)
            & (frame["trend_20d"] > 0.0)
            & (frame["trend_50d"] > 0.0)
            & (frame["realized_vol_21d"].fillna(9.0) < 1.25)
        ].copy()
        if candidates.empty:
            continue
        top = candidates.sort_values(score_col, ascending=False).head(max_positions)
        strengths = [1.50, 1.20, 0.90]
        for symbol, strength in zip(top.index, strengths):
            out.loc[date, symbol] = strength
    return out.fillna(0.0)


def main():
    args = parse_args()
    research = ResearchConfig(start=args.start, end=args.end, cache_dir=args.cache_dir)
    symbols = research.tickers
    prices = download_prices(
        list(dict.fromkeys(symbols + [research.market_ticker, research.vix_ticker])),
        args.start,
        args.end,
        args.cache_dir,
        refresh=False,
    )
    panel = build_feature_panel(prices, symbols, research.market_ticker, research.vix_ticker)
    scored = cross_sectional_zscore(panel, ["mom_5d", "mom_21d", "mom_63d", "trend_20d", "trend_50d", "volume_z_20d"])
    scored["breakout_score"] = (
        0.35 * scored["mom_5d_xsz"].fillna(0.0)
        + 0.30 * scored["mom_21d_xsz"].fillna(0.0)
        + 0.15 * scored["mom_63d_xsz"].fillna(0.0)
        + 0.25 * scored["trend_20d_xsz"].fillna(0.0)
        + 0.20 * scored["trend_50d_xsz"].fillna(0.0)
        + 0.10 * scored["volume_z_20d_xsz"].fillna(0.0)
        - 0.10 * scored["realized_vol_21d"].fillna(0.0)
    )
    scored["short_burst_score"] = (
        0.55 * scored["mom_5d_xsz"].fillna(0.0)
        + 0.20 * scored["mom_21d_xsz"].fillna(0.0)
        + 0.25 * scored["trend_20d_xsz"].fillna(0.0)
        + 0.15 * scored["volume_z_20d_xsz"].fillna(0.0)
        - 0.05 * scored["realized_vol_21d"].fillna(0.0)
    )
    scored["trend_quality_score"] = (
        0.20 * scored["mom_21d_xsz"].fillna(0.0)
        + 0.35 * scored["mom_63d_xsz"].fillna(0.0)
        + 0.20 * scored["trend_20d_xsz"].fillna(0.0)
        + 0.35 * scored["trend_50d_xsz"].fillna(0.0)
        - 0.15 * scored["atr_pct_14d"].fillna(0.0)
    )

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    variants = {
        "breakout": ("breakout_score", ()),
        "breakout_ex_meta_xlv": ("breakout_score", ("META", "XLV")),
        "short_burst": ("short_burst_score", ()),
        "trend_quality_ex_meta_xlv": ("trend_quality_score", ("META", "XLV")),
    }
    for name, (score_col, exclude) in variants.items():
        weights = build_weights(scored, symbols, score_col, exclude=exclude)
        path = output / f"{name}_weights.csv"
        weights.to_csv(path, index_label="Date")
        active = int((weights.abs().sum(axis=1) > 0).sum())
        print(f"{name}: {active} active days -> {path}")


if __name__ == "__main__":
    main()
