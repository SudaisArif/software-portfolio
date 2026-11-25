#!/usr/bin/env python3
import argparse
import itertools
import math
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.option_chain import (
    OptionBacktestConfig,
    _build_option_indexes,
    _build_option_type_groups,
    load_option_chains,
    run_long_call_backtest,
)
from scripts.sweep_gap_push import Dataset, max_drawdown, monthly_breakdown, transformed_weights


def parse_args():
    parser = argparse.ArgumentParser(description="Focused refinement around the balanced OTM options profile.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_otm_refine")
    parser.add_argument("--max-variants", type=int, default=600)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--save-top", type=int, default=25)
    return parser.parse_args()


def make_config(row):
    return OptionBacktestConfig(
        monthly_loss_stop=row["monthly_loss_stop"],
        monthly_profit_lock=row["monthly_profit_lock"],
        max_premium_fraction=row["max_premium_fraction"],
        max_total_premium_fraction=row["max_total_premium_fraction"],
        min_contract_price=row["min_contract_price"],
        max_contracts_per_trade=row["max_contracts_per_trade"],
        min_otm_pct=row["min_otm_pct"],
        max_otm_pct=row["max_otm_pct"],
        min_entry_weight=0.75,
        stop_loss=row["stop_loss"],
        take_profit=row["take_profit"],
        max_hold_days=row["max_hold_days"],
        close_on_monthly_loss_stop=True,
        allow_put_entries=True,
    )


def variant_name(row):
    exclude = row["exclude"] or "none"
    return (
        f"ex_{exclude}_prem{int(row['max_premium_fraction'] * 100):02d}_"
        f"tot{int(row['max_total_premium_fraction'] * 100):02d}_"
        f"ml{int(row['monthly_loss_stop'] * 1000):03d}_"
        f"sl{int(row['stop_loss'] * 100):02d}_tp{int(row['take_profit'] * 100):03d}_"
        f"h{row['max_hold_days']}_cap{row['max_contracts_per_trade']}_"
        f"p{int(row['min_contract_price'] * 100):03d}_"
        f"otm{int(row['min_otm_pct'] * 100):02d}_{int(row['max_otm_pct'] * 100):02d}"
    ).replace(",", "_")


def candidate_rows(max_variants, seed):
    base = {
        "exclude": "META",
        "max_premium_fraction": 0.20,
        "max_total_premium_fraction": 0.85,
        "monthly_loss_stop": 0.03,
        "monthly_profit_lock": 0.50,
        "stop_loss": 0.30,
        "take_profit": 1.75,
        "max_hold_days": 5,
        "max_contracts_per_trade": 12,
        "min_contract_price": 1.00,
        "min_otm_pct": 0.04,
        "max_otm_pct": 0.08,
    }
    fixed_rows = [
        {"variant": "current_otm", **base, "exclude": ""},
        {"variant": "current_otm_ex_meta", **base},
        {"variant": "current_otm_ex_xlv", **base, "exclude": "XLV"},
        {"variant": "current_otm_ex_meta_xlv", **base, "exclude": "META,XLV"},
    ]
    grid_rows = []
    for values in itertools.product(
        ["", "META", "XLV", "META,XLV", "META,XLV,XLE", "META,XLV,MSFT"],
        [0.16, 0.18, 0.20, 0.22, 0.25],
        [0.65, 0.75, 0.85, 0.95],
        [0.025, 0.03, 0.04, 0.05],
        [0.50, 0.75],
        [0.25, 0.30, 0.35, 0.45],
        [1.50, 1.75, 2.00, 2.25],
        [4, 5, 6, 7],
        [6, 8, 10, 12],
        [0.75, 1.00, 1.25],
        [0.03, 0.04, 0.05],
        [0.07, 0.08, 0.10, 0.12],
    ):
        (
            exclude,
            max_premium_fraction,
            max_total_premium_fraction,
            monthly_loss_stop,
            monthly_profit_lock,
            stop_loss,
            take_profit,
            max_hold_days,
            max_contracts_per_trade,
            min_contract_price,
            min_otm_pct,
            max_otm_pct,
        ) = values
        if max_premium_fraction > max_total_premium_fraction or min_otm_pct >= max_otm_pct:
            continue
        grid_rows.append(
            {
                "exclude": exclude,
                "max_premium_fraction": max_premium_fraction,
                "max_total_premium_fraction": max_total_premium_fraction,
                "monthly_loss_stop": monthly_loss_stop,
                "monthly_profit_lock": monthly_profit_lock,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "max_hold_days": max_hold_days,
                "max_contracts_per_trade": max_contracts_per_trade,
                "min_contract_price": min_contract_price,
                "min_otm_pct": min_otm_pct,
                "max_otm_pct": max_otm_pct,
            }
        )
    if max_variants > 0 and len(grid_rows) > max_variants:
        grid_rows = random.Random(seed).sample(grid_rows, max_variants)
    for row in grid_rows:
        row["variant"] = variant_name(row)
    return fixed_rows + grid_rows


def apply_exclusions(weights, exclude):
    out = weights.copy()
    for symbol in [item.strip().upper() for item in exclude.split(",") if item.strip()]:
        if symbol in out.columns:
            out[symbol] = 0.0
    return out


def summarize(dataset, variant, result, monthly, initial_cash):
    final = float(result["equity"]["equity"].iloc[-1])
    return {
        "dataset": dataset.name,
        "variant": variant["variant"],
        "exclude": variant["exclude"],
        "final_equity": final,
        "total_return": final / initial_cash - 1.0,
        "max_drawdown": max_drawdown(result["equity"]),
        "orders": len(result["orders"]),
        "losing_months": int((monthly["monthly_profit"] < 0).sum()),
        "worst_month": float(monthly["monthly_profit"].min()),
        "best_month": float(monthly["monthly_profit"].max()),
    }


def markdown_table(frame):
    if frame.empty:
        return "_No rows._"
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


def build_combined(per_dataset):
    rows = []
    for variant in sorted(per_dataset["variant"].unique()):
        part = per_dataset[per_dataset["variant"] == variant].set_index("dataset")
        if {"2024_holdout", "2025_winner"} - set(part.index):
            continue
        final_2024 = float(part.loc["2024_holdout", "final_equity"])
        final_2025 = float(part.loc["2025_winner", "final_equity"])
        rows.append(
            {
                "variant": variant,
                "exclude": str(part["exclude"].iloc[0]),
                "final_2024": final_2024,
                "final_2025": final_2025,
                "min_final": min(final_2024, final_2025),
                "geo_final": math.sqrt(max(final_2024, 0.0) * max(final_2025, 0.0)),
                "gap_ratio": max(final_2024, final_2025) / max(1.0, min(final_2024, final_2025)),
                "worst_drawdown": min(float(part.loc["2024_holdout", "max_drawdown"]), float(part.loc["2025_winner", "max_drawdown"])),
                "total_losing_months": int(part["losing_months"].sum()),
                "worst_month_any": float(part["worst_month"].min()),
                "orders_2024": int(part.loc["2024_holdout", "orders"]),
                "orders_2025": int(part.loc["2025_winner", "orders"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["min_final", "geo_final", "gap_ratio"], ascending=[False, False, True])


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]
    state = {}
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        prepared = (*_build_option_indexes(chain), _build_option_type_groups(chain))
        weights = transformed_weights(raw_weights, dataset, args.cache_dir)
        state[dataset.name] = (dataset, chain, prepared, weights)

    rows = []
    variants = candidate_rows(args.max_variants, args.seed)
    for idx, variant in enumerate(variants, start=1):
        config = make_config(variant)
        for _, (dataset, chain, prepared, weights) in state.items():
            test_weights = apply_exclusions(weights, variant["exclude"])
            result = run_long_call_backtest(chain, test_weights, args.initial_cash, config, prepared_indexes=prepared)
            monthly = monthly_breakdown(result["equity"], dataset.start, args.initial_cash)
            rows.append(summarize(dataset, variant, result, monthly, args.initial_cash))
        if idx % 100 == 0:
            print(f"Completed {idx} variants")

    per_dataset = pd.DataFrame(rows)
    per_dataset.to_csv(output_dir / "per_dataset_summary.csv", index=False)
    combined = build_combined(per_dataset)
    combined.to_csv(output_dir / "combined_summary.csv", index=False)

    top_variants = set(combined.head(args.save_top)["variant"])
    for variant in variants:
        if variant["variant"] not in top_variants:
            continue
        config = make_config(variant)
        for _, (dataset, chain, prepared, weights) in state.items():
            test_weights = apply_exclusions(weights, variant["exclude"])
            result = run_long_call_backtest(chain, test_weights, args.initial_cash, config, prepared_indexes=prepared)
            variant_dir = output_dir / dataset.name / variant["variant"]
            variant_dir.mkdir(parents=True, exist_ok=True)
            for name, frame in result.items():
                frame.to_csv(variant_dir / f"{name}.csv", index=False)
            monthly = monthly_breakdown(result["equity"], dataset.start, args.initial_cash)
            monthly.to_csv(variant_dir / "monthly.csv", index_label="date")

    top = combined.head(25).copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        top[col] = top[col].map(lambda value: f"${value:,.0f}")
    top["gap_ratio"] = top["gap_ratio"].map(lambda value: f"{value:,.2f}x")
    top["worst_drawdown"] = top["worst_drawdown"].map(lambda value: f"{value * 100:,.1f}%")
    report = f"""# OTM Profile Refinement Sweep

Focused sweep around the balanced farther-OTM profile. The starting point is:

- Max premium per idea 20%
- Max total premium 85%
- Monthly loss stop 3%, close all
- Stop loss 30%
- Take profit 175%
- Max hold 5 days
- Minimum ask $1.00
- Call moneyness 4% to 8% OTM
- Strict VIX-shock start put overlay

## Top Combined Profiles

{markdown_table(top)}
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
