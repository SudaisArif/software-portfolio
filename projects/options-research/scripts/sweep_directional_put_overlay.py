#!/usr/bin/env python3
import argparse
import math
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
    parser = argparse.ArgumentParser(description="Test stress-regime put overlays against the long-call profile.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_directional_put_overlay")
    return parser.parse_args()


def base_config(allow_puts=False, stop_loss=0.45, max_total=0.55, put_max_premium=None):
    return OptionBacktestConfig(
        monthly_loss_stop=0.05,
        monthly_profit_lock=0.50,
        max_premium_fraction=0.15,
        max_total_premium_fraction=max_total,
        put_max_premium_fraction=put_max_premium,
        min_contract_price=1.0,
        max_contracts_per_trade=12,
        max_otm_pct=0.06,
        min_entry_weight=0.75,
        stop_loss=stop_loss,
        take_profit=1.25,
        max_hold_days=7,
        close_on_monthly_loss_stop=True,
        allow_put_entries=allow_puts,
    )


def variants():
    return [
        {"name": "calls_reference_trend50", "mode": "calls", "put_strength": 0.0, "zero_calls": False, "config": base_config()},
        {
            "name": "stress_index_puts_keep_calls",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "stress_index_puts_zero_calls",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": True,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "stress_index_puts_strong_zero_calls",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 2.0,
            "zero_calls": True,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "stress_worst_mom_puts_zero_calls",
            "mode": "worst_mom_puts",
            "stress_kind": "broad",
            "put_strength": 1.5,
            "zero_calls": True,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "stress_worst_mom_puts_keep_calls",
            "mode": "worst_mom_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "stress_index_puts_stop35_zero_calls",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": True,
            "config": base_config(allow_puts=True, stop_loss=0.35),
        },
        {
            "name": "stress_worst_mom_puts_stop35_zero_calls",
            "mode": "worst_mom_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": True,
            "config": base_config(allow_puts=True, stop_loss=0.35),
        },
        {
            "name": "stress_index_puts_total45_zero_calls",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": True,
            "config": base_config(allow_puts=True, max_total=0.45),
        },
        {
            "name": "stress_index_puts_keep_calls_put05",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True, put_max_premium=0.05),
        },
        {
            "name": "stress_index_puts_keep_calls_put08",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True, put_max_premium=0.08),
        },
        {
            "name": "stress_index_puts_stop35_keep_calls_put08",
            "mode": "index_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True, stop_loss=0.35, put_max_premium=0.08),
        },
        {
            "name": "stress_worst_mom_puts_keep_calls_put08",
            "mode": "worst_mom_puts",
            "stress_kind": "broad",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True, put_max_premium=0.08),
        },
        {
            "name": "vixjump40_index_puts_keep_calls",
            "mode": "index_puts",
            "stress_kind": "vix_jump40",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "vixjump40_index_puts_stop35_keep_calls",
            "mode": "index_puts",
            "stress_kind": "vix_jump40",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True, stop_loss=0.35),
        },
        {
            "name": "vixjump40_worst_mom_puts_keep_calls",
            "mode": "worst_mom_puts",
            "stress_kind": "vix_jump40",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "vixjump40_start_index_puts_keep_calls",
            "mode": "index_puts",
            "stress_kind": "vix_jump40_start",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "vixjump40_start_index_puts_stop35_keep_calls",
            "mode": "index_puts",
            "stress_kind": "vix_jump40_start",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True, stop_loss=0.35),
        },
        {
            "name": "broad_start_index_puts_keep_calls",
            "mode": "index_puts",
            "stress_kind": "broad_start",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True),
        },
        {
            "name": "broad_start_index_puts_stop35_keep_calls",
            "mode": "index_puts",
            "stress_kind": "broad_start",
            "put_strength": 1.25,
            "zero_calls": False,
            "config": base_config(allow_puts=True, stop_loss=0.35),
        },
    ]


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


def market_stress_mask(dates, end, cache_dir, kind="broad"):
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(None)
    spy = read_cached_prices(cache_dir, "SPY", "2016-01-01", end)["Close"]
    vix = read_cached_prices(cache_dir, "^VIX", "2016-01-01", end)["Close"]
    spy_below_100 = spy < spy.rolling(100).mean()
    spy_drop_10d = spy / spy.shift(10) - 1.0 < -0.04
    vix_high = vix >= 28.0
    vix_jump = vix / vix.shift(5) - 1.0 >= 0.25
    if kind == "broad":
        stress = spy_below_100 | spy_drop_10d | vix_high.reindex(spy.index).ffill() | vix_jump.reindex(spy.index).ffill()
    elif kind == "broad_start":
        broad = spy_below_100 | spy_drop_10d | vix_high.reindex(spy.index).ffill() | vix_jump.reindex(spy.index).ffill()
        stress = broad & ~broad.shift(1).fillna(False)
    elif kind == "vix_jump40":
        stress = vix / vix.shift(5) - 1.0 >= 0.40
    elif kind == "vix_jump40_start":
        jump = vix / vix.shift(5) - 1.0 >= 0.40
        stress = jump & ~jump.shift(1).fillna(False)
    else:
        raise ValueError(f"Unknown stress kind: {kind}")
    return stress.reindex(dates).ffill().fillna(False).astype(bool)


def momentum_frame(columns, dates, end, cache_dir):
    values = {}
    for symbol in columns:
        try:
            close = read_cached_prices(cache_dir, symbol, "2016-01-01", end)["Close"]
        except FileNotFoundError:
            values[symbol] = pd.Series(0.0, index=dates)
            continue
        mom = close / close.shift(21) - 1.0
        values[symbol] = mom.reindex(dates).ffill().fillna(0.0)
    return pd.DataFrame(values, index=dates)


def make_weights(raw_weights, dataset, variant, cache_dir):
    start = pd.Timestamp(dataset.start)
    end = pd.Timestamp(dataset.end)
    weights = raw_weights.loc[(raw_weights.index >= start) & (raw_weights.index <= end)].copy()
    if "TLT" in weights.columns:
        weights["TLT"] = 0.0
    weights = weights.where(trend50_mask(weights, dataset.end, cache_dir), 0.0)
    if variant["mode"] == "calls":
        return weights

    stress = market_stress_mask(weights.index, dataset.end, cache_dir, variant.get("stress_kind", "broad"))
    out = weights.copy()
    if variant["zero_calls"]:
        out.loc[stress, :] = 0.0

    if variant["mode"] == "index_puts":
        for symbol in ["SPY", "QQQ", "IWM"]:
            if symbol in out.columns:
                out.loc[stress, symbol] = -float(variant["put_strength"])
    elif variant["mode"] == "worst_mom_puts":
        momentum = momentum_frame(out.columns, out.index, dataset.end, cache_dir)
        for date in out.index[stress]:
            weakest = momentum.loc[date].sort_values().head(3)
            for symbol, value in weakest.items():
                if value < -0.02:
                    out.loc[date, symbol] = -float(variant["put_strength"])
    else:
        raise ValueError(f"Unknown variant mode: {variant['mode']}")
    return out


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
    rows = []
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        quote_lookup, call_groups = _build_option_indexes(chain)
        option_type_groups = _build_option_type_groups(chain)
        prepared = (quote_lookup, call_groups, option_type_groups)
        for variant in variants():
            weights = make_weights(raw_weights, dataset, variant, args.cache_dir)
            result = run_long_call_backtest(chain, weights, args.initial_cash, variant["config"], prepared_indexes=prepared)
            variant_dir = output_dir / dataset.name / variant["name"]
            variant_dir.mkdir(parents=True, exist_ok=True)
            for name, frame in result.items():
                frame.to_csv(variant_dir / f"{name}.csv", index=False)
            monthly = monthly_breakdown(result["equity"], dataset.start, args.initial_cash)
            monthly.to_csv(variant_dir / "monthly.csv", index_label="date")
            final = float(result["equity"]["equity"].iloc[-1])
            put_buys = 0
            orders = result["orders"]
            if not orders.empty:
                put_buys = int(((orders["action"] == "BUY") & (orders["contract_id"].astype(str).str.contains("_P_"))).sum())
            row = {
                "dataset": dataset.name,
                "variant": variant["name"],
                "final_equity": final,
                "total_return": final / args.initial_cash - 1.0,
                "max_drawdown": max_drawdown(result["equity"]),
                "orders": len(orders),
                "put_buys": put_buys,
                "losing_months": int((monthly["monthly_profit"] < 0).sum()),
                "worst_month": float(monthly["monthly_profit"].min()),
                "best_month": float(monthly["monthly_profit"].max()),
            }
            rows.append(row)
            print(
                f"{dataset.name}/{variant['name']}: final=${final:,.0f}, "
                f"dd={row['max_drawdown'] * 100:,.1f}%, puts={put_buys}"
            )

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
                "put_buys_2024": int(part.loc["2024_holdout", "put_buys"]),
                "put_buys_2025": int(part.loc["2025_winner", "put_buys"]),
                "orders_2024": int(part.loc["2024_holdout", "orders"]),
                "orders_2025": int(part.loc["2025_winner", "orders"]),
            }
        )
    combined = pd.DataFrame(combined_rows).sort_values(["min_final", "geo_final"], ascending=[False, False])
    combined.to_csv(output_dir / "combined_summary.csv", index=False)
    top = combined.head(12).copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        top[col] = top[col].map(lambda value: f"${value:,.0f}")
    top["gap_ratio"] = top["gap_ratio"].map(lambda value: f"{value:,.2f}x")
    top["worst_drawdown"] = top["worst_drawdown"].map(lambda value: f"{value * 100:,.1f}%")
    report = f"""# Directional Put Overlay Sweep

This sweep tests whether adding long puts in market-stress regimes closes the 2024/2025 stability gap.

## Top Combined Profiles

{markdown_table(top)}
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
