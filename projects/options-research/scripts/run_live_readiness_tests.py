#!/usr/bin/env python3
"""Run robustness gates before using an options profile for paper/live observation."""
import argparse
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.option_chain import (  # noqa: E402
    OptionBacktestConfig,
    _build_option_indexes,
    _build_option_type_groups,
    load_option_chains,
    run_long_call_backtest,
)
from scripts.sweep_gap_push import Dataset, max_drawdown, monthly_breakdown, transformed_weights  # noqa: E402


@dataclass(frozen=True)
class Profile:
    name: str
    config: OptionBacktestConfig
    excludes: tuple[str, ...]
    note: str


@dataclass
class DatasetState:
    dataset: Dataset
    chain: pd.DataFrame
    prepared_indexes: tuple
    weights: pd.DataFrame


def parse_args():
    parser = argparse.ArgumentParser(description="Run live-readiness robustness tests on cached OPRA chains.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/live_readiness_otm")
    parser.add_argument("--candidate-profile", default="otm_clean_live_candidate")
    parser.add_argument("--skip-stress", action="store_true")
    parser.add_argument("--skip-symbol-ablation", action="store_true")
    parser.add_argument("--skip-parameter-sensitivity", action="store_true")
    return parser.parse_args()


def profile_catalog() -> Dict[str, Profile]:
    common = {
        "monthly_profit_lock": 0.50,
        "max_contracts_per_trade": 12,
        "min_entry_weight": 0.75,
        "close_on_monthly_loss_stop": True,
        "allow_put_entries": True,
    }
    return {
        "otm_clean_live_candidate": Profile(
            name="otm_clean_live_candidate",
            excludes=("META", "XLV"),
            note="Cleaner OTM candidate with lower drawdown/worst-month profile than the raw $10k+ variant.",
            config=OptionBacktestConfig(
                **common,
                monthly_loss_stop=0.04,
                max_premium_fraction=0.18,
                max_total_premium_fraction=0.75,
                min_contract_price=0.75,
                min_otm_pct=0.03,
                max_otm_pct=0.10,
                stop_loss=0.35,
                take_profit=2.25,
                max_hold_days=5,
            ),
        ),
        "otm_meta_only_reference": Profile(
            name="otm_meta_only_reference",
            excludes=("META",),
            note="Simple current OTM profile with META removed.",
            config=OptionBacktestConfig(
                **common,
                monthly_loss_stop=0.03,
                max_premium_fraction=0.20,
                max_total_premium_fraction=0.85,
                min_contract_price=1.00,
                min_otm_pct=0.04,
                max_otm_pct=0.08,
                stop_loss=0.30,
                take_profit=1.75,
                max_hold_days=5,
            ),
        ),
        "otm_raw_research_candidate": Profile(
            name="otm_raw_research_candidate",
            excludes=("META",),
            note="Highest balanced min-final OTM result, kept as research-only because drawdown was severe.",
            config=OptionBacktestConfig(
                **common,
                monthly_loss_stop=0.05,
                max_premium_fraction=0.22,
                max_total_premium_fraction=0.75,
                min_contract_price=0.75,
                min_otm_pct=0.03,
                max_otm_pct=0.12,
                stop_loss=0.35,
                take_profit=1.50,
                max_hold_days=5,
            ),
        ),
    }


def apply_exclusions(weights: pd.DataFrame, excludes: Iterable[str]) -> pd.DataFrame:
    out = weights.copy()
    for symbol in excludes:
        symbol = symbol.upper()
        if symbol in out.columns:
            out[symbol] = 0.0
    return out


def load_dataset_state(args, raw_weights: pd.DataFrame) -> Dict[str, DatasetState]:
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]
    state = {}
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        prepared = (*_build_option_indexes(chain), _build_option_type_groups(chain))
        weights = transformed_weights(raw_weights, dataset, args.cache_dir)
        state[dataset.name] = DatasetState(dataset, chain, prepared, weights)
    return state


def stressed_chain(chain: pd.DataFrame, buy_worse: float, sell_worse: float) -> pd.DataFrame:
    out = chain.copy()
    out["ask"] = out["ask"] * (1.0 + buy_worse)
    out["bid"] = (out["bid"] * (1.0 - sell_worse)).clip(lower=0.0)
    out["mid"] = (out["bid"] + out["ask"]) / 2.0
    out["spread_pct"] = (out["ask"] - out["bid"]) / out["mid"].replace(0.0, pd.NA)
    return out


def run_case(
    state: DatasetState,
    profile: Profile,
    initial_cash: float,
    scenario: str,
    test_group: str,
    config: Optional[OptionBacktestConfig] = None,
    excludes: Optional[Iterable[str]] = None,
    chain_modifier: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None,
) -> tuple[dict, dict[str, pd.DataFrame], pd.DataFrame]:
    config = config or profile.config
    excludes = tuple(excludes if excludes is not None else profile.excludes)
    weights = apply_exclusions(state.weights, excludes)
    chain = state.chain
    prepared = state.prepared_indexes
    if chain_modifier is not None:
        chain = chain_modifier(state.chain)
        prepared = (*_build_option_indexes(chain), _build_option_type_groups(chain))
    result = run_long_call_backtest(chain, weights, initial_cash, config, prepared_indexes=prepared)
    monthly = monthly_breakdown(result["equity"], state.dataset.start, initial_cash)
    final = float(result["equity"]["equity"].iloc[-1])
    row = {
        "test_group": test_group,
        "scenario": scenario,
        "dataset": state.dataset.name,
        "profile": profile.name,
        "excludes": ",".join(excludes),
        "final_equity": final,
        "total_return": final / initial_cash - 1.0,
        "max_drawdown": max_drawdown(result["equity"]),
        "orders": len(result["orders"]),
        "losing_months": int((monthly["monthly_profit"] < 0).sum()),
        "worst_month": float(monthly["monthly_profit"].min()),
        "worst_month_return": float(monthly["monthly_return"].min()),
        "best_month": float(monthly["monthly_profit"].max()),
        "best_month_return": float(monthly["monthly_return"].max()),
    }
    return row, result, monthly


def combined_summary(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    keys = ["test_group", "scenario", "profile", "excludes"]
    for values, part in rows.groupby(keys, dropna=False):
        by_dataset = part.set_index("dataset")
        if {"2024_holdout", "2025_winner"} - set(by_dataset.index):
            continue
        final_2024 = float(by_dataset.loc["2024_holdout", "final_equity"])
        final_2025 = float(by_dataset.loc["2025_winner", "final_equity"])
        out.append(
            {
                **dict(zip(keys, values)),
                "final_2024": final_2024,
                "final_2025": final_2025,
                "min_final": min(final_2024, final_2025),
                "geo_final": math.sqrt(max(final_2024, 0.0) * max(final_2025, 0.0)),
                "gap_ratio": max(final_2024, final_2025) / max(1.0, min(final_2024, final_2025)),
                "worst_drawdown": min(
                    float(by_dataset.loc["2024_holdout", "max_drawdown"]),
                    float(by_dataset.loc["2025_winner", "max_drawdown"]),
                ),
                "total_losing_months": int(part["losing_months"].sum()),
                "worst_month_any": float(part["worst_month"].min()),
                "worst_month_return_any": float(part["worst_month_return"].min()),
                "orders_2024": int(by_dataset.loc["2024_holdout", "orders"]),
                "orders_2025": int(by_dataset.loc["2025_winner", "orders"]),
            }
        )
    return pd.DataFrame(out).sort_values(["test_group", "min_final"], ascending=[True, False])


def traded_symbols(results: Dict[str, dict[str, pd.DataFrame]], excludes: Iterable[str]) -> list[str]:
    excluded = {symbol.upper() for symbol in excludes}
    symbols = set()
    for result in results.values():
        orders = result["orders"]
        if not orders.empty:
            buys = orders[orders["action"] == "BUY"]
            symbols.update(str(symbol).upper() for symbol in buys["symbol"].unique())
    return sorted(symbol for symbol in symbols if symbol not in excluded)


def parameter_variants(config: OptionBacktestConfig) -> list[tuple[str, OptionBacktestConfig]]:
    variants = [
        ("premium_minus_02", replace(config, max_premium_fraction=max(0.01, config.max_premium_fraction - 0.02))),
        ("premium_plus_02", replace(config, max_premium_fraction=config.max_premium_fraction + 0.02)),
        ("total_minus_10", replace(config, max_total_premium_fraction=max(0.01, config.max_total_premium_fraction - 0.10))),
        ("total_plus_10", replace(config, max_total_premium_fraction=min(1.0, config.max_total_premium_fraction + 0.10))),
        ("monthly_loss_minus_01", replace(config, monthly_loss_stop=max(0.0, config.monthly_loss_stop - 0.01))),
        ("monthly_loss_plus_01", replace(config, monthly_loss_stop=config.monthly_loss_stop + 0.01)),
        ("stop_minus_05", replace(config, stop_loss=max(0.05, config.stop_loss - 0.05))),
        ("stop_plus_05", replace(config, stop_loss=config.stop_loss + 0.05)),
        ("take_profit_minus_25", replace(config, take_profit=max(0.25, config.take_profit - 0.25))),
        ("take_profit_plus_25", replace(config, take_profit=config.take_profit + 0.25)),
        ("hold_minus_1", replace(config, max_hold_days=max(1, config.max_hold_days - 1))),
        ("hold_plus_1", replace(config, max_hold_days=config.max_hold_days + 1)),
        ("min_price_100", replace(config, min_contract_price=1.00)),
    ]
    if config.min_otm_pct is not None:
        variants.append(("min_otm_minus_01", replace(config, min_otm_pct=max(-0.05, config.min_otm_pct - 0.01))))
        if config.max_otm_pct is None or config.min_otm_pct + 0.01 < config.max_otm_pct:
            variants.append(("min_otm_plus_01", replace(config, min_otm_pct=config.min_otm_pct + 0.01)))
    if config.max_otm_pct is not None:
        if config.min_otm_pct is None or config.max_otm_pct - 0.02 > config.min_otm_pct:
            variants.append(("max_otm_minus_02", replace(config, max_otm_pct=config.max_otm_pct - 0.02)))
        variants.append(("max_otm_plus_02", replace(config, max_otm_pct=config.max_otm_pct + 0.02)))
    return variants


def format_money(value):
    return f"${value:,.0f}"


def format_pct(value):
    return f"{value * 100:,.1f}%"


def markdown_table(frame: pd.DataFrame, max_rows: int = 20) -> str:
    if frame.empty:
        return "_No rows._"
    frame = frame.head(max_rows).copy()
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


def build_gates(combined: pd.DataFrame, candidate_profile: str, initial_cash: float) -> pd.DataFrame:
    def find(test_group, scenario):
        part = combined[
            (combined["profile"] == candidate_profile)
            & (combined["test_group"] == test_group)
            & (combined["scenario"] == scenario)
        ]
        return None if part.empty else part.iloc[0]

    gates = []
    base = find("baseline", "base")
    if base is not None:
        gates.extend(
            [
                {
                    "gate": "baseline_positive_both_years",
                    "passed": bool(base["final_2024"] > initial_cash and base["final_2025"] > initial_cash),
                    "value": f"{format_money(base['final_2024'])} / {format_money(base['final_2025'])}",
                },
                {
                    "gate": "baseline_drawdown_not_worse_than_45pct",
                    "passed": bool(base["worst_drawdown"] >= -0.45),
                    "value": format_pct(base["worst_drawdown"]),
                },
                {
                    "gate": "baseline_monthly_loss_not_worse_than_35pct",
                    "passed": bool(base["worst_month_return_any"] >= -0.35),
                    "value": format_pct(base["worst_month_return_any"]),
                },
            ]
        )
    for scenario in ["fill_stress_5pct", "fill_stress_10pct", "spread_filter_10pct"]:
        row = find("execution_stress", scenario)
        if row is None:
            continue
        gates.append(
            {
                "gate": f"{scenario}_still_positive_both_years",
                "passed": bool(row["final_2024"] > initial_cash and row["final_2025"] > initial_cash),
                "value": f"{format_money(row['final_2024'])} / {format_money(row['final_2025'])}",
            }
        )
    ablations = combined[(combined["profile"] == candidate_profile) & (combined["test_group"] == "symbol_ablation")]
    if not ablations.empty and base is not None:
        worst = ablations.sort_values("min_final").iloc[0]
        gates.append(
            {
                "gate": "no_single_symbol_removal_drops_min_final_below_60pct",
                "passed": bool(worst["min_final"] >= base["min_final"] * 0.60),
                "value": f"worst {worst['scenario']}: {format_money(worst['min_final'])}",
            }
        )
    params = combined[(combined["profile"] == candidate_profile) & (combined["test_group"] == "parameter_sensitivity")]
    if not params.empty and base is not None:
        gates.extend(
            [
                {
                    "gate": "parameter_median_min_final_above_60pct",
                    "passed": bool(float(params["min_final"].median()) >= base["min_final"] * 0.60),
                    "value": format_money(float(params["min_final"].median())),
                },
                {
                    "gate": "no_parameter_variant_loses_money_in_weaker_year",
                    "passed": bool(float(params["min_final"].min()) > initial_cash),
                    "value": format_money(float(params["min_final"].min())),
                },
            ]
        )
    exclusion = combined[(combined["profile"] == candidate_profile) & (combined["test_group"] == "exclusion_policy")]
    if not exclusion.empty:
        none = exclusion[exclusion["scenario"] == "exclude_none"]
        meta_xlv = exclusion[exclusion["scenario"] == "exclude_META_XLV"]
        if not none.empty and not meta_xlv.empty:
            gates.append(
                {
                    "gate": "meta_xlv_exclusion_improves_min_final_vs_none",
                    "passed": bool(float(meta_xlv.iloc[0]["min_final"]) > float(none.iloc[0]["min_final"])),
                    "value": f"none {format_money(float(none.iloc[0]['min_final']))}, META+XLV {format_money(float(meta_xlv.iloc[0]['min_final']))}",
                }
            )
    return pd.DataFrame(gates)


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog = profile_catalog()
    if args.candidate_profile not in catalog:
        raise SystemExit(f"Unknown candidate profile {args.candidate_profile}. Choices: {', '.join(catalog)}")
    candidate = catalog[args.candidate_profile]

    raw_weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    states = load_dataset_state(args, raw_weights)

    rows = []
    baseline_results = {}
    baseline_monthly = []

    for profile in catalog.values():
        for state in states.values():
            row, result, monthly = run_case(state, profile, args.initial_cash, "base", "baseline")
            rows.append(row)
            if profile.name == candidate.name:
                baseline_results[state.dataset.name] = result
                monthly = monthly.reset_index().rename(columns={"index": "date"})
                monthly["dataset"] = state.dataset.name
                monthly["profile"] = profile.name
                baseline_monthly.append(monthly)
                case_dir = output_dir / "candidate_baseline" / state.dataset.name
                case_dir.mkdir(parents=True, exist_ok=True)
                for name, frame in result.items():
                    frame.to_csv(case_dir / f"{name}.csv", index=False)
                monthly.to_csv(case_dir / "monthly.csv", index=False)

    if not args.skip_stress:
        stress_cases = [
            ("fill_stress_5pct", candidate.config, lambda chain: stressed_chain(chain, 0.05, 0.05)),
            ("fill_stress_10pct", candidate.config, lambda chain: stressed_chain(chain, 0.10, 0.10)),
            ("spread_filter_10pct", replace(candidate.config, max_spread_pct=0.10), None),
            (
                "liquidity_oi100_vol5",
                replace(candidate.config, min_open_interest=100, min_volume=5),
                None,
            ),
        ]
        for scenario, config, modifier in stress_cases:
            for state in states.values():
                row, _, _ = run_case(
                    state,
                    candidate,
                    args.initial_cash,
                    scenario,
                    "execution_stress",
                    config=config,
                    chain_modifier=modifier,
                )
                rows.append(row)

    exclusion_sets = {
        "exclude_none": (),
        "exclude_META": ("META",),
        "exclude_XLV": ("XLV",),
        "exclude_META_XLV": ("META", "XLV"),
    }
    for scenario, excludes in exclusion_sets.items():
        for state in states.values():
            row, _, _ = run_case(
                state,
                candidate,
                args.initial_cash,
                scenario,
                "exclusion_policy",
                excludes=excludes,
            )
            rows.append(row)

    if not args.skip_symbol_ablation:
        for symbol in traded_symbols(baseline_results, candidate.excludes):
            for state in states.values():
                row, _, _ = run_case(
                    state,
                    candidate,
                    args.initial_cash,
                    f"remove_{symbol}",
                    "symbol_ablation",
                    excludes=(*candidate.excludes, symbol),
                )
                rows.append(row)

    if not args.skip_parameter_sensitivity:
        for scenario, config in parameter_variants(candidate.config):
            for state in states.values():
                row, _, _ = run_case(
                    state,
                    candidate,
                    args.initial_cash,
                    scenario,
                    "parameter_sensitivity",
                    config=config,
                )
                rows.append(row)

    per_dataset = pd.DataFrame(rows)
    combined = combined_summary(per_dataset)
    gates = build_gates(combined, candidate.name, args.initial_cash)

    per_dataset.to_csv(output_dir / "per_dataset_summary.csv", index=False)
    combined.to_csv(output_dir / "combined_summary.csv", index=False)
    gates.to_csv(output_dir / "readiness_gates.csv", index=False)
    if baseline_monthly:
        pd.concat(baseline_monthly, ignore_index=True).to_csv(output_dir / "candidate_monthly.csv", index=False)

    display = combined[
        (combined["profile"] == candidate.name)
        & (combined["test_group"].isin(["baseline", "execution_stress", "exclusion_policy"]))
    ].copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        display[col] = display[col].map(format_money)
    display["gap_ratio"] = display["gap_ratio"].map(lambda value: f"{value:,.2f}x")
    display["worst_drawdown"] = display["worst_drawdown"].map(format_pct)
    display["worst_month_return_any"] = display["worst_month_return_any"].map(format_pct)

    ablation_display = combined[
        (combined["profile"] == candidate.name) & (combined["test_group"] == "symbol_ablation")
    ].sort_values("min_final")
    ablation_display = ablation_display[
        ["scenario", "final_2024", "final_2025", "min_final", "gap_ratio", "worst_drawdown"]
    ].copy()
    parameter_display = combined[
        (combined["profile"] == candidate.name) & (combined["test_group"] == "parameter_sensitivity")
    ].sort_values("min_final")
    parameter_display = parameter_display[
        ["scenario", "final_2024", "final_2025", "min_final", "gap_ratio", "worst_drawdown"]
    ].copy()
    for frame in [ablation_display, parameter_display]:
        if frame.empty:
            continue
        for col in ["final_2024", "final_2025", "min_final"]:
            frame[col] = frame[col].map(format_money)
        frame["gap_ratio"] = frame["gap_ratio"].map(lambda value: f"{value:,.2f}x")
        frame["worst_drawdown"] = frame["worst_drawdown"].map(format_pct)

    gates_display = gates.copy()
    if not gates_display.empty:
        gates_display["passed"] = gates_display["passed"].map(lambda value: "PASS" if value else "FAIL")

    failed = 0 if gates.empty else int((~gates["passed"]).sum())
    status = "PAPER-OBSERVATION ONLY" if failed else "PAPER GATES PASSED; STILL NOT A GUARANTEE"
    report = f"""# Live Readiness Test Report

Candidate profile: `{candidate.name}`  
Status: **{status}**  
Failed gates: **{failed}**

This is a readiness report for paper/live observation. It is not evidence of guaranteed future returns and it does not model every live risk, especially intraday fills, broker rejections, assignment/exercise workflows, taxes, and account restrictions.

## Candidate Profile

- Excluded symbols: `{", ".join(candidate.excludes) if candidate.excludes else "none"}`
- Max premium per idea: {format_pct(candidate.config.max_premium_fraction)}
- Max total premium at risk: {format_pct(candidate.config.max_total_premium_fraction)}
- Monthly loss stop: {format_pct(candidate.config.monthly_loss_stop)}, close all positions
- Monthly profit lock: {format_pct(candidate.config.monthly_profit_lock)}
- Stop loss: {format_pct(candidate.config.stop_loss)}
- Take profit: {format_pct(candidate.config.take_profit)}
- Max hold: {candidate.config.max_hold_days} days
- Contract ask range: minimum ${candidate.config.min_contract_price:,.2f}, OTM {format_pct(candidate.config.min_otm_pct or 0.0)} to {format_pct(candidate.config.max_otm_pct or 0.0)}
- VIX-shock long-put overlay: enabled through transformed negative weights

## Gate Results

{markdown_table(gates_display, max_rows=30)}

## Main Scenario Results

{markdown_table(display, max_rows=30)}

## Worst Symbol-Ablation Results

{markdown_table(ablation_display, max_rows=12)}

## Worst Parameter-Sensitivity Results

{markdown_table(parameter_display, max_rows=12)}

## Files

- `per_dataset_summary.csv`
- `combined_summary.csv`
- `readiness_gates.csv`
- `candidate_monthly.csv`
- `candidate_baseline/`
"""
    (output_dir / "REPORT.md").write_text(report)

    print(f"Status: {status}")
    print(f"Failed gates: {failed}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
