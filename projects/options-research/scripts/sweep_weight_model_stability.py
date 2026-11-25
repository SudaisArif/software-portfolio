#!/usr/bin/env python3
import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.data import read_cached_prices
from algotrader.option_chain import OptionBacktestConfig, _build_option_indexes, load_option_chains, run_long_call_backtest


@dataclass(frozen=True)
class Dataset:
    name: str
    chains: str
    start: str
    end: str


def parse_args():
    parser = argparse.ArgumentParser(description="Compare available weight models on both OPRA years.")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_weight_model_stability")
    return parser.parse_args()


def stable_config(stop_loss=0.45):
    return OptionBacktestConfig(
        monthly_loss_stop=0.05,
        monthly_profit_lock=0.50,
        max_premium_fraction=0.15,
        max_total_premium_fraction=0.55,
        min_contract_price=1.0,
        max_contracts_per_trade=12,
        max_otm_pct=0.06,
        min_entry_weight=0.75,
        stop_loss=stop_loss,
        take_profit=1.25,
        max_hold_days=7,
        close_losers_on_monthly_loss_stop=True,
        close_on_monthly_loss_stop=True,
    )


def weight_files():
    paths = sorted(Path("artifacts").glob("*/latest_weights.csv"))
    paths += [Path("reports/latest_weights.csv")]
    return [path for path in paths if path.exists()]


def normalize_row_max(weights, target=2.0):
    values = weights.copy()
    numeric = values.drop(columns=["Date"], errors="ignore") if "Date" in values.columns else values
    max_abs = numeric.abs().max(axis=1).replace(0.0, pd.NA)
    scaled = numeric.div(max_abs, axis=0).fillna(0.0) * target
    return scaled


def trend50_filter(weights, end, cache_dir):
    masks = {}
    for symbol in weights.columns:
        try:
            close = read_cached_prices(cache_dir, symbol, "2016-01-01", end)["Close"]
        except FileNotFoundError:
            masks[symbol] = pd.Series(False, index=weights.index)
            continue
        masks[symbol] = (close > close.rolling(50).mean()).reindex(weights.index).ffill().fillna(False).astype(bool)
    return pd.DataFrame(masks, index=weights.index)


def prepare_weights(path, dataset, cache_dir, use_trend50):
    raw = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
    weights = normalize_row_max(raw, target=2.0)
    weights = weights.loc[(weights.index >= pd.Timestamp(dataset.start)) & (weights.index <= pd.Timestamp(dataset.end))]
    if "TLT" in weights.columns:
        weights["TLT"] = 0.0
    if use_trend50:
        weights = weights.where(trend50_filter(weights, dataset.end, cache_dir), 0.0)
    return weights


def monthly_breakdown(equity, start, initial_cash):
    monthly = equity.assign(date=pd.to_datetime(equity["date"])).set_index("date")["equity"].resample("ME").last()
    monthly = pd.concat([pd.Series([initial_cash], index=[pd.Timestamp(start)]), monthly]).dropna()
    return pd.DataFrame({"equity": monthly, "monthly_profit": monthly.diff(), "monthly_return": monthly.pct_change()}).dropna()


def max_drawdown(equity):
    curve = equity["equity"]
    return float((curve / curve.cummax() - 1.0).min())


def markdown_table(frame):
    lines = ["| " + " | ".join(frame.columns) + " |", "| " + " | ".join(["---"] * len(frame.columns)) + " |"]
    for _, row in frame.iterrows():
        values = []
        for value in row:
            if isinstance(value, float):
                values.append(f"{value:,.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]
    profile_rows = [
        ("stable", stable_config(0.45), False),
        ("trend50", stable_config(0.45), True),
        ("stop35", stable_config(0.35), False),
        ("trend50_stop35", stable_config(0.35), True),
    ]
    rows = []
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        prepared = _build_option_indexes(chain)
        for weights_path in weight_files():
            model_name = weights_path.parent.name if weights_path.parent.name != "reports" else "reports_latest"
            for profile_name, config, use_trend50 in profile_rows:
                weights = prepare_weights(weights_path, dataset, args.cache_dir, use_trend50)
                result = run_long_call_backtest(chain, weights, args.initial_cash, config, prepared_indexes=prepared)
                variant = f"{model_name}__{profile_name}"
                variant_dir = output_dir / dataset.name / variant
                variant_dir.mkdir(parents=True, exist_ok=True)
                for name, frame in result.items():
                    frame.to_csv(variant_dir / f"{name}.csv", index=False)
                monthly = monthly_breakdown(result["equity"], dataset.start, args.initial_cash)
                monthly.to_csv(variant_dir / "monthly.csv", index_label="date")
                final = float(result["equity"]["equity"].iloc[-1])
                rows.append(
                    {
                        "dataset": dataset.name,
                        "variant": variant,
                        "model": model_name,
                        "profile": profile_name,
                        "final_equity": final,
                        "total_return": final / args.initial_cash - 1.0,
                        "max_drawdown": max_drawdown(result["equity"]),
                        "orders": len(result["orders"]),
                        "losing_months": int((monthly["monthly_profit"] < 0).sum()),
                        "worst_month": float(monthly["monthly_profit"].min()),
                        "best_month": float(monthly["monthly_profit"].max()),
                    }
                )
                print(f"{dataset.name}/{variant}: final=${final:,.0f}, dd={max_drawdown(result['equity']) * 100:,.1f}%")

    per_dataset = pd.DataFrame(rows)
    per_dataset.to_csv(output_dir / "per_dataset_summary.csv", index=False)
    combined_rows = []
    for variant in sorted(per_dataset["variant"].unique()):
        part = per_dataset[per_dataset["variant"] == variant].set_index("dataset")
        if {"2024_holdout", "2025_winner"} - set(part.index):
            continue
        final_2024 = float(part.loc["2024_holdout", "final_equity"])
        final_2025 = float(part.loc["2025_winner", "final_equity"])
        combined_rows.append(
            {
                "variant": variant,
                "model": str(part["model"].iloc[0]),
                "profile": str(part["profile"].iloc[0]),
                "final_2024": final_2024,
                "final_2025": final_2025,
                "min_final": min(final_2024, final_2025),
                "geo_final": math.sqrt(max(0.0, final_2024) * max(0.0, final_2025)),
                "gap_ratio": max(final_2024, final_2025) / max(1.0, min(final_2024, final_2025)),
                "worst_drawdown": min(float(part.loc["2024_holdout", "max_drawdown"]), float(part.loc["2025_winner", "max_drawdown"])),
                "total_losing_months": int(part["losing_months"].sum()),
                "worst_month_any": float(part["worst_month"].min()),
                "orders_2024": int(part.loc["2024_holdout", "orders"]),
                "orders_2025": int(part.loc["2025_winner", "orders"]),
            }
        )
    combined = pd.DataFrame(combined_rows).sort_values(["min_final", "gap_ratio", "geo_final"], ascending=[False, True, False])
    combined.to_csv(output_dir / "combined_summary.csv", index=False)
    top = combined.head(20).copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        top[col] = top[col].map(lambda value: f"${value:,.0f}")
    top["gap_ratio"] = top["gap_ratio"].map(lambda value: f"{value:,.2f}x")
    top["worst_drawdown"] = top["worst_drawdown"].map(lambda value: f"{value * 100:,.1f}%")
    report = f"""# Weight Model Stability Sweep

Weights are row-normalized to the same maximum signal strength before entering the options engine. This tests signal/ranking differences rather than gross exposure differences.

## Top Profiles

{markdown_table(top)}
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
