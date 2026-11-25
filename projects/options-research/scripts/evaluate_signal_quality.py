#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from algotrader.config import ModelConfig, ResearchConfig, StrategyConfig
from algotrader.data import close_matrix, download_prices
from algotrader.features import build_feature_panel
from algotrader.strategy import add_factor_signal, add_model_signal


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate walk-forward signal ranking quality.")
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-04-24")
    parser.add_argument("--eval-start", default="2025-04-28")
    parser.add_argument("--eval-end", default="2026-04-24")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/signal_quality")
    parser.add_argument("--target-name", default="target_up")
    return parser.parse_args()


def rank_auc(scores, labels):
    frame = pd.DataFrame({"score": scores, "label": labels}).replace([np.inf, -np.inf], np.nan).dropna()
    pos = frame[frame["label"] > 0]
    neg = frame[frame["label"] <= 0]
    if pos.empty or neg.empty:
        return np.nan
    ranks = frame["score"].rank(method="average")
    pos_rank_sum = ranks.loc[pos.index].sum()
    n_pos = len(pos)
    n_neg = len(neg)
    return float((pos_rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def spearman_corr(left, right):
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return np.nan
    return frame["left"].rank().corr(frame["right"].rank())


def decile_table(frame, score_col):
    rows = []
    data = frame[[score_col, "next_ret_1d", "forward_ret_5d", "target_up"]].dropna().copy()
    data["decile"] = pd.qcut(data[score_col].rank(method="first"), 10, labels=False) + 1
    for decile, group in data.groupby("decile"):
        rows.append(
            {
                "score": score_col,
                "decile": int(decile),
                "rows": len(group),
                "avg_next_1d": group["next_ret_1d"].mean(),
                "hit_rate_1d": group["target_up"].mean(),
                "avg_forward_5d": group["forward_ret_5d"].mean(),
            }
        )
    return pd.DataFrame(rows)


def daily_top_stats(frame, score_col, top_n=3):
    rows = []
    for date, group in frame.groupby(level="Date"):
        clean = group.dropna(subset=[score_col, "next_ret_1d", "forward_ret_5d"])
        if clean.empty:
            continue
        top = clean.sort_values(score_col, ascending=False).head(top_n)
        bottom = clean.sort_values(score_col, ascending=True).head(top_n)
        rows.append(
            {
                "date": date,
                "score": score_col,
                "top_next_1d": top["next_ret_1d"].mean(),
                "bottom_next_1d": bottom["next_ret_1d"].mean(),
                "spread_next_1d": top["next_ret_1d"].mean() - bottom["next_ret_1d"].mean(),
                "top_forward_5d": top["forward_ret_5d"].mean(),
                "bottom_forward_5d": bottom["forward_ret_5d"].mean(),
                "spread_forward_5d": top["forward_ret_5d"].mean() - bottom["forward_ret_5d"].mean(),
                "top_hit_rate": (top["next_ret_1d"] > 0).mean(),
            }
        )
    return pd.DataFrame(rows)


def summarize_score(frame, score_col):
    clean = frame.dropna(subset=[score_col, "next_ret_1d", "forward_ret_5d", "target_up"]).copy()
    daily_ic_1d = clean.groupby(level="Date").apply(lambda g: spearman_corr(g[score_col], g["next_ret_1d"]))
    daily_ic_5d = clean.groupby(level="Date").apply(lambda g: spearman_corr(g[score_col], g["forward_ret_5d"]))
    top = daily_top_stats(clean, score_col)
    return {
        "score": score_col,
        "rows": len(clean),
        "auc_up_1d": rank_auc(clean[score_col], clean["target_up"]),
        "brier": float(((clean["ml_probability"].clip(0.01, 0.99) - clean["target_up"]) ** 2).mean())
        if score_col == "ml_probability"
        else np.nan,
        "mean_daily_spearman_1d": float(daily_ic_1d.mean()),
        "median_daily_spearman_1d": float(daily_ic_1d.median()),
        "mean_daily_spearman_5d": float(daily_ic_5d.mean()),
        "top3_avg_next_1d": float(top["top_next_1d"].mean()),
        "top3_minus_bottom3_1d": float(top["spread_next_1d"].mean()),
        "top3_avg_forward_5d": float(top["top_forward_5d"].mean()),
        "top3_minus_bottom3_5d": float(top["spread_forward_5d"].mean()),
        "top3_hit_rate": float(top["top_hit_rate"].mean()),
    }


def markdown_table(frame):
    cols = list(frame.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in frame.iterrows():
        vals = []
        for col in cols:
            value = row[col]
            if isinstance(value, float):
                vals.append(f"{value:.6f}")
            else:
                vals.append(str(value))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main():
    args = parse_args()
    research = ResearchConfig(start=args.start, end=args.end, cache_dir=args.cache_dir)
    symbols = list(dict.fromkeys(research.tickers + [research.market_ticker, research.vix_ticker]))
    prices = download_prices(symbols, research.start, research.end, research.cache_dir, refresh=False)
    closes = close_matrix({symbol: prices[symbol] for symbol in symbols if symbol in prices})
    panel = build_feature_panel(prices, research.tickers, research.market_ticker, research.vix_ticker)
    scored = add_model_signal(panel, ModelConfig(target_name=args.target_name))
    scored = add_factor_signal(scored)
    scored["combined_signal"] = 0.65 * scored["ml_edge"].fillna(0.0) * 10.0 + 0.35 * scored["factor_score"].fillna(0.0)
    scored = scored.loc[(slice(pd.Timestamp(args.eval_start), pd.Timestamp(args.eval_end)), slice(None)), :]

    score_cols = ["ml_probability", "factor_score", "combined_signal"]
    summary = pd.DataFrame([summarize_score(scored, col) for col in score_cols])
    deciles = pd.concat([decile_table(scored, col) for col in score_cols], ignore_index=True)
    top_daily = pd.concat([daily_top_stats(scored, col) for col in score_cols], ignore_index=True)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "summary.csv", index=False)
    deciles.to_csv(output / "deciles.csv", index=False)
    top_daily.to_csv(output / "daily_top_stats.csv", index=False)
    report = f"""# Signal Quality Report

Period: **{args.eval_start} to {args.eval_end}**

## Summary

{markdown_table(summary)}

## Notes

- AUC above 0.50 means the score ranks up days above down days better than random.
- Daily Spearman IC measures same-day cross-sectional rank correlation between score and future returns.
- `top3_minus_bottom3` is the average daily spread between the three highest-scored names and the three lowest-scored names.
"""
    (output / "REPORT.md").write_text(report)
    print(summary.to_string(index=False))
    print(f"Report: {output / 'REPORT.md'}")


if __name__ == "__main__":
    main()
