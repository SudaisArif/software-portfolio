#!/usr/bin/env python3
import argparse
import itertools
import math
import random
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays.*")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.data import read_cached_prices
from algotrader.option_chain import (
    OptionBacktestConfig,
    _build_option_indexes,
    _build_option_type_groups,
    load_option_chains,
    run_long_call_backtest,
)


@dataclass(frozen=True)
class Dataset:
    name: str
    chains: str
    start: str
    end: str


def parse_args():
    parser = argparse.ArgumentParser(description="Push two-year real-options profiles toward a smaller 2024/2025 gap.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_gap_push")
    parser.add_argument("--max-grid-variants", type=int, default=240)
    parser.add_argument("--seed", type=int, default=11)
    return parser.parse_args()


def trend50_mask(weights, end, cache_dir):
    masks = {}
    for symbol in weights.columns:
        try:
            close = read_cached_prices(cache_dir, symbol, "2016-01-01", end)["Close"]
        except FileNotFoundError:
            masks[symbol] = pd.Series(False, index=weights.index)
            continue
        masks[symbol] = (close > close.rolling(50).mean()).reindex(weights.index).ffill().fillna(False).astype(bool)
    return pd.DataFrame(masks, index=weights.index)


def vix_jump_start_mask(dates, end, cache_dir):
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(None)
    vix = read_cached_prices(cache_dir, "^VIX", "2016-01-01", end)["Close"]
    jump = vix / vix.shift(5) - 1.0 >= 0.40
    start = jump & ~jump.shift(1).fillna(False)
    return start.reindex(dates).ffill().fillna(False).astype(bool)


def transformed_weights(raw_weights, dataset, cache_dir, put_strength=1.25):
    start = pd.Timestamp(dataset.start)
    end = pd.Timestamp(dataset.end)
    weights = raw_weights.loc[(raw_weights.index >= start) & (raw_weights.index <= end)].copy()
    if "TLT" in weights.columns:
        weights["TLT"] = 0.0
    weights = weights.where(trend50_mask(weights, dataset.end, cache_dir), 0.0)
    stress_start = vix_jump_start_mask(weights.index, dataset.end, cache_dir)
    for symbol in ["SPY", "QQQ", "IWM"]:
        if symbol in weights.columns:
            weights.loc[stress_start, symbol] = -put_strength
    return weights


def variant_grid(max_grid_variants, seed):
    fixed = {
        "monthly_profit_lock": 0.50,
        "max_contracts_per_trade": 12,
        "min_entry_weight": 0.75,
        "close_on_monthly_loss_stop": True,
        "allow_put_entries": True,
    }
    rows = []
    hybrid_otm_base = {
        **fixed,
        "max_premium_fraction": 0.20,
        "max_total_premium_fraction": 0.75,
        "monthly_loss_stop": 0.075,
        "stop_loss": 0.55,
        "take_profit": 1.25,
        "max_hold_days": 5,
        "min_contract_price": 1.00,
        "min_otm_pct": 0.04,
        "max_otm_pct": 0.08,
    }
    convex_2024_base = {
        **fixed,
        "max_premium_fraction": 0.20,
        "max_total_premium_fraction": 0.85,
        "monthly_loss_stop": 0.03,
        "stop_loss": 0.30,
        "take_profit": 2.25,
        "max_hold_days": 5,
        "min_contract_price": 1.00,
        "min_otm_pct": 0.02,
        "max_otm_pct": 0.08,
    }
    for (
        max_premium,
        max_total,
        monthly_loss,
        stop_loss,
        take_profit,
        max_hold,
        min_price,
        min_otm,
        max_otm,
    ) in itertools.product(
        [0.15, 0.20, 0.25, 0.30],
        [0.55, 0.65, 0.75, 0.85],
        [0.03, 0.05, 0.075, 0.10],
        [0.30, 0.35, 0.45, 0.55],
        [1.25, 1.75, 2.25],
        [5, 7, 10],
        [0.75, 1.00, 1.25],
        [None, 0.0, 0.02, 0.04],
        [0.04, 0.06, 0.08],
    ):
        if max_premium > max_total:
            continue
        if min_otm is not None and min_otm >= max_otm:
            continue
        min_otm_label = "none" if min_otm is None else f"{int(min_otm * 100):02d}"
        name = (
            f"prem{int(max_premium * 100):02d}_tot{int(max_total * 100):02d}_"
            f"ml{int(monthly_loss * 1000):03d}_sl{int(stop_loss * 100):02d}_"
            f"tp{int(take_profit * 100):03d}_h{max_hold}_p{int(min_price * 100):03d}_"
            f"minotm{min_otm_label}_maxotm{int(max_otm * 100):02d}"
        )
        rows.append(
            (
                name,
                OptionBacktestConfig(
                    **fixed,
                    max_premium_fraction=max_premium,
                    max_total_premium_fraction=max_total,
                    monthly_loss_stop=monthly_loss,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    max_hold_days=max_hold,
                    min_contract_price=min_price,
                    min_otm_pct=min_otm,
                    max_otm_pct=max_otm,
                ),
                [],
            )
        )
    extras = [
        (
            "reference_vixjump_start_stop35",
            OptionBacktestConfig(
                **fixed,
                max_premium_fraction=0.15,
                max_total_premium_fraction=0.55,
                monthly_loss_stop=0.05,
                stop_loss=0.35,
                take_profit=1.25,
                max_hold_days=7,
                min_contract_price=1.00,
                max_otm_pct=0.06,
            ),
            [],
        ),
        (
            "aggressive_no_monthly_close",
            OptionBacktestConfig(
                monthly_loss_stop=0.0,
                monthly_profit_lock=0.0,
                max_premium_fraction=0.30,
                max_total_premium_fraction=0.85,
                min_contract_price=0.75,
                max_contracts_per_trade=12,
                max_otm_pct=0.08,
                min_entry_weight=0.75,
                stop_loss=0.45,
                take_profit=2.25,
                max_hold_days=10,
                allow_put_entries=True,
            ),
            [],
        ),
        (
            "hybrid_otm_near_gld_xle",
            OptionBacktestConfig(
                **hybrid_otm_base,
                min_otm_pct_by_symbol={"GLD": None, "XLE": None},
                max_otm_pct_by_symbol={"GLD": 0.06, "XLE": 0.06},
            ),
            [],
        ),
        (
            "hybrid_otm_near_gld_xle_exclude_meta_xlv",
            OptionBacktestConfig(
                **hybrid_otm_base,
                min_otm_pct_by_symbol={"GLD": None, "XLE": None},
                max_otm_pct_by_symbol={"GLD": 0.06, "XLE": 0.06},
            ),
            ["META", "XLV"],
        ),
        (
            "hybrid_otm_near_gld_xle_xlf_excluded",
            OptionBacktestConfig(
                **hybrid_otm_base,
                min_otm_pct_by_symbol={"GLD": None, "XLE": None},
                max_otm_pct_by_symbol={"GLD": 0.06, "XLE": 0.06},
            ),
            ["META", "XLV", "XLF"],
        ),
        (
            "hybrid_otm_near_gld_only_exclude_meta_xlv",
            OptionBacktestConfig(
                **hybrid_otm_base,
                min_otm_pct_by_symbol={"GLD": None},
                max_otm_pct_by_symbol={"GLD": 0.06},
            ),
            ["META", "XLV"],
        ),
        (
            "convex2024_near_gld_xle_exclude_meta_xlv",
            OptionBacktestConfig(
                **convex_2024_base,
                min_otm_pct_by_symbol={"GLD": None, "XLE": None},
                max_otm_pct_by_symbol={"GLD": 0.06, "XLE": 0.06},
            ),
            ["META", "XLV"],
        ),
        (
            "convex2024_near_gld_xle",
            OptionBacktestConfig(
                **convex_2024_base,
                min_otm_pct_by_symbol={"GLD": None, "XLE": None},
                max_otm_pct_by_symbol={"GLD": 0.06, "XLE": 0.06},
            ),
            [],
        ),
        (
            "convex2024_near_gld_only_exclude_meta_xlv",
            OptionBacktestConfig(
                **convex_2024_base,
                min_otm_pct_by_symbol={"GLD": None},
                max_otm_pct_by_symbol={"GLD": 0.06},
            ),
            ["META", "XLV"],
        ),
    ]
    if max_grid_variants > 0 and len(rows) > max_grid_variants:
        rows = random.Random(seed).sample(rows, max_grid_variants)
    return extras + rows


def monthly_breakdown(equity, start, initial_cash):
    monthly = equity.assign(date=pd.to_datetime(equity["date"])).set_index("date")["equity"].resample("ME").last()
    monthly = pd.concat([pd.Series([initial_cash], index=[pd.Timestamp(start)]), monthly]).dropna()
    return pd.DataFrame({"equity": monthly, "monthly_profit": monthly.diff(), "monthly_return": monthly.pct_change()}).dropna()


def max_drawdown(equity):
    curve = equity["equity"]
    return float((curve / curve.cummax() - 1.0).min())


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


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]
    dataset_state = {}
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        prepared = (*_build_option_indexes(chain), _build_option_type_groups(chain))
        weights = transformed_weights(raw_weights, dataset, args.cache_dir)
        dataset_state[dataset.name] = (dataset, chain, prepared, weights)

    rows = []
    for variant_name, config, excluded_symbols in variant_grid(args.max_grid_variants, args.seed):
        for dataset_name, (dataset, chain, prepared, weights) in dataset_state.items():
            test_weights = weights.copy()
            for symbol in excluded_symbols:
                if symbol in test_weights.columns:
                    test_weights[symbol] = 0.0
            result = run_long_call_backtest(chain, test_weights, args.initial_cash, config, prepared_indexes=prepared)
            variant_dir = output_dir / dataset.name / variant_name
            variant_dir.mkdir(parents=True, exist_ok=True)
            for name, frame in result.items():
                frame.to_csv(variant_dir / f"{name}.csv", index=False)
            monthly = monthly_breakdown(result["equity"], dataset.start, args.initial_cash)
            monthly.to_csv(variant_dir / "monthly.csv", index_label="date")
            final = float(result["equity"]["equity"].iloc[-1])
            rows.append(
                {
                    "dataset": dataset.name,
                    "variant": variant_name,
                    "final_equity": final,
                    "total_return": final / args.initial_cash - 1.0,
                    "max_drawdown": max_drawdown(result["equity"]),
                    "orders": len(result["orders"]),
                    "losing_months": int((monthly["monthly_profit"] < 0).sum()),
                    "worst_month": float(monthly["monthly_profit"].min()),
                    "best_month": float(monthly["monthly_profit"].max()),
                }
            )
        if len(rows) % 200 == 0:
            latest = pd.DataFrame(rows)
            print(f"Completed {len(latest['variant'].unique())} variants")

    per_dataset = pd.DataFrame(rows)
    per_dataset.to_csv(output_dir / "per_dataset_summary.csv", index=False)
    combined_rows = []
    for variant in sorted(per_dataset["variant"].unique()):
        part = per_dataset[per_dataset["variant"] == variant].set_index("dataset")
        final_2024 = float(part.loc["2024_holdout", "final_equity"])
        final_2025 = float(part.loc["2025_winner", "final_equity"])
        combined_rows.append(
            {
                "variant": variant,
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
    combined = pd.DataFrame(combined_rows)
    combined = combined.sort_values(["min_final", "geo_final", "gap_ratio"], ascending=[False, False, True])
    combined.to_csv(output_dir / "combined_summary.csv", index=False)
    top = combined.head(30).copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        top[col] = top[col].map(lambda value: f"${value:,.0f}")
    top["gap_ratio"] = top["gap_ratio"].map(lambda value: f"{value:,.2f}x")
    top["worst_drawdown"] = top["worst_drawdown"].map(lambda value: f"{value * 100:,.1f}%")
    report = f"""# Gap Push Sweep

This sweep keeps the strict VIX-shock put overlay and tests more aggressive bounded sizing/exits. It ranks profiles by the weaker-year final equity first.

## Top Combined Profiles

{markdown_table(top)}
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
