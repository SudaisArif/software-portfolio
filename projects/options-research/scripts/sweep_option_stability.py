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
    parser = argparse.ArgumentParser(description="Test stability-first real-options variants across two windows.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_stability_sweep")
    return parser.parse_args()


def base_config():
    return {
        "monthly_loss_stop": 0.075,
        "monthly_profit_lock": 0.50,
        "max_premium_fraction": 0.15,
        "max_total_premium_fraction": 0.55,
        "min_contract_price": 1.0,
        "max_contracts_per_trade": 12,
        "max_otm_pct": 0.06,
        "min_entry_weight": 0.75,
        "stop_loss": 0.45,
        "take_profit": 1.25,
        "max_hold_days": 7,
        "close_losers_on_monthly_loss_stop": True,
    }


def variants():
    common_excludes = ["TLT"]
    rows = [
        ("safe_20k_baseline", {}, "none", "none"),
        ("total45", {"max_total_premium_fraction": 0.45}, "none", "none"),
        ("total40", {"max_total_premium_fraction": 0.40}, "none", "none"),
        ("min_price125", {"min_contract_price": 1.25}, "none", "none"),
        ("min_price150", {"min_contract_price": 1.50}, "none", "none"),
        ("max_otm04", {"max_otm_pct": 0.04}, "none", "none"),
        ("max_otm03", {"max_otm_pct": 0.03}, "none", "none"),
        ("spread08_liquid", {"max_spread_pct": 0.08, "min_open_interest": 250, "min_volume": 25}, "none", "none"),
        ("stop35", {"stop_loss": 0.35}, "none", "none"),
        ("monthly_loss05", {"monthly_loss_stop": 0.05}, "none", "none"),
        ("monthly_loss06", {"monthly_loss_stop": 0.06}, "none", "none"),
        ("monthly_loss04_close_all", {"monthly_loss_stop": 0.04, "close_on_monthly_loss_stop": True}, "none", "none"),
        ("monthly_loss05_close_all", {"monthly_loss_stop": 0.05, "close_on_monthly_loss_stop": True}, "none", "none"),
        ("monthly_loss06_close_all", {"monthly_loss_stop": 0.06, "close_on_monthly_loss_stop": True}, "none", "none"),
        ("monthly_loss075_close_all", {"monthly_loss_stop": 0.075, "close_on_monthly_loss_stop": True}, "none", "none"),
        (
            "monthly_loss05_close_all_trend50",
            {"monthly_loss_stop": 0.05, "close_on_monthly_loss_stop": True},
            "none",
            "trend50",
        ),
        (
            "monthly_loss05_close_all_total45",
            {
                "monthly_loss_stop": 0.05,
                "close_on_monthly_loss_stop": True,
                "max_total_premium_fraction": 0.45,
            },
            "none",
            "none",
        ),
        (
            "monthly_loss05_close_all_min_price125",
            {"monthly_loss_stop": 0.05, "close_on_monthly_loss_stop": True, "min_contract_price": 1.25},
            "none",
            "none",
        ),
        (
            "monthly_loss05_close_all_stop35",
            {"monthly_loss_stop": 0.05, "close_on_monthly_loss_stop": True, "stop_loss": 0.35},
            "none",
            "none",
        ),
        ("cooldown3", {"stop_loss_cooldown_days": 3}, "none", "none"),
        ("cooldown5", {"stop_loss_cooldown_days": 5}, "none", "none"),
        ("cooldown10", {"stop_loss_cooldown_days": 10}, "none", "none"),
        ("stop35_cooldown5", {"stop_loss": 0.35, "stop_loss_cooldown_days": 5}, "none", "none"),
        ("low_equity_scale1000_90", {"low_equity_risk_scale_threshold": 1000.0, "low_equity_risk_scale": 0.90}, "none", "none"),
        ("low_equity_scale1000_80", {"low_equity_risk_scale_threshold": 1000.0, "low_equity_risk_scale": 0.80}, "none", "none"),
        ("low_equity_scale1000_70", {"low_equity_risk_scale_threshold": 1000.0, "low_equity_risk_scale": 0.70}, "none", "none"),
        ("low_equity_scale1000_half", {"low_equity_risk_scale_threshold": 1000.0, "low_equity_risk_scale": 0.50}, "none", "none"),
        ("drawdown_scale15_half", {"drawdown_risk_scale_threshold": 0.15, "drawdown_risk_scale": 0.50}, "none", "none"),
        ("drawdown_scale20_half", {"drawdown_risk_scale_threshold": 0.20, "drawdown_risk_scale": 0.50}, "none", "none"),
        ("drawdown_pause25", {"max_equity_drawdown_for_new_entries": 0.25}, "none", "none"),
        ("drawdown_pause35", {"max_equity_drawdown_for_new_entries": 0.35}, "none", "none"),
        ("equity_floor900", {"min_equity_for_new_entries": 900.0}, "none", "none"),
        ("equity_floor850", {"min_equity_for_new_entries": 850.0}, "none", "none"),
        ("equity_floor800", {"min_equity_for_new_entries": 800.0}, "none", "none"),
        ("equity_floor750", {"min_equity_for_new_entries": 750.0}, "none", "none"),
        ("equity_floor1000", {"min_equity_for_new_entries": 1000.0}, "none", "none"),
        ("spy_sma100", {}, "spy_sma100", "none"),
        ("qqq_sma100", {}, "qqq_sma100", "none"),
        ("spy_qqq_sma100", {}, "spy_qqq_sma100", "none"),
        ("vix25", {}, "vix25", "none"),
        ("vix25_spy100", {}, "vix25_spy100", "none"),
        ("asset_trend50", {}, "none", "trend50"),
        ("asset_trend20_50", {}, "none", "trend20_50"),
        ("asset_mom21", {}, "none", "mom21"),
        ("asset_trend50_mom21", {}, "none", "trend50_mom21"),
        ("asset_trend50_min_price125", {"min_contract_price": 1.25}, "none", "trend50"),
        ("asset_trend50_total45", {"max_total_premium_fraction": 0.45}, "none", "trend50"),
        (
            "asset_trend50_low_equity70",
            {"low_equity_risk_scale_threshold": 1000.0, "low_equity_risk_scale": 0.70},
            "none",
            "trend50",
        ),
        (
            "balanced_guard",
            {
                "max_total_premium_fraction": 0.45,
                "min_contract_price": 1.25,
                "max_otm_pct": 0.04,
                "drawdown_risk_scale_threshold": 0.20,
                "drawdown_risk_scale": 0.60,
            },
            "none",
            "none",
        ),
        (
            "regime_guard",
            {
                "max_total_premium_fraction": 0.45,
                "min_contract_price": 1.25,
                "max_otm_pct": 0.04,
            },
            "vix25_spy100",
            "none",
        ),
        (
            "trend_guard",
            {
                "max_total_premium_fraction": 0.45,
                "min_contract_price": 1.25,
            },
            "spy_sma100",
            "trend50",
        ),
    ]
    return [
        {
            "name": name,
            "config": OptionBacktestConfig(**{**base_config(), **overrides}),
            "excluded_symbols": common_excludes,
            "market_filter": market_filter,
            "asset_filter": asset_filter,
        }
        for name, overrides, market_filter, asset_filter in rows
    ]


def monthly_breakdown(equity, start, initial_cash):
    monthly = equity.assign(date=pd.to_datetime(equity["date"])).set_index("date")["equity"].resample("ME").last()
    monthly = pd.concat([pd.Series([initial_cash], index=[pd.Timestamp(start)]), monthly]).dropna()
    return pd.DataFrame(
        {
            "equity": monthly,
            "monthly_profit": monthly.diff(),
            "monthly_return": monthly.pct_change(),
        }
    ).dropna()


def max_drawdown(equity):
    curve = equity["equity"]
    return float((curve / curve.cummax() - 1.0).min())


def load_chain_with_cache(path):
    source = Path(path)
    if source.is_dir():
        parquet = source / "chains.parquet"
        if parquet.exists():
            return load_option_chains(str(parquet)), str(parquet)
        chain = load_option_chains(str(source))
        try:
            chain.to_parquet(parquet, index=False)
            return chain, str(parquet)
        except Exception:
            return chain, str(source)
    return load_option_chains(str(source)), str(source)


def market_filter_mask(filter_name, dates, end, cache_dir):
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(None)
    if filter_name == "none":
        return pd.Series(True, index=dates)

    spy = read_cached_prices(cache_dir, "SPY", "2016-01-01", end)["Close"]
    qqq = read_cached_prices(cache_dir, "QQQ", "2016-01-01", end)["Close"]
    vix = read_cached_prices(cache_dir, "^VIX", "2016-01-01", end)["Close"]
    spy_sma100 = spy > spy.rolling(100).mean()
    qqq_sma100 = qqq > qqq.rolling(100).mean()
    vix_below25 = vix < 25.0

    pieces = {
        "spy_sma100": spy_sma100,
        "qqq_sma100": qqq_sma100,
        "spy_qqq_sma100": spy_sma100 & qqq_sma100.reindex(spy.index).ffill().fillna(False),
        "vix25": vix_below25,
        "vix25_spy100": spy_sma100 & vix_below25.reindex(spy.index).ffill().fillna(False),
    }
    if filter_name not in pieces:
        raise ValueError(f"Unknown market filter: {filter_name}")
    return pieces[filter_name].reindex(dates).ffill().fillna(False).astype(bool)


def asset_filter_frame(filter_name, weights, end, cache_dir):
    if filter_name == "none":
        return pd.DataFrame(True, index=weights.index, columns=weights.columns)
    masks = {}
    for symbol in weights.columns:
        try:
            close = read_cached_prices(cache_dir, symbol, "2016-01-01", end)["Close"]
        except FileNotFoundError:
            masks[symbol] = pd.Series(False, index=weights.index)
            continue
        trend20 = close > close.rolling(20).mean()
        trend50 = close > close.rolling(50).mean()
        mom21 = close / close.shift(21) - 1.0 > 0.0
        pieces = {
            "trend50": trend50,
            "trend20_50": trend20 & trend50,
            "mom21": mom21,
            "trend50_mom21": trend50 & mom21,
        }
        if filter_name not in pieces:
            raise ValueError(f"Unknown asset filter: {filter_name}")
        masks[symbol] = pieces[filter_name].reindex(weights.index).ffill().fillna(False).astype(bool)
    return pd.DataFrame(masks, index=weights.index)


def make_weights(weights, dataset, excluded_symbols, market_filter, asset_filter, cache_dir):
    start = pd.Timestamp(dataset.start)
    end = pd.Timestamp(dataset.end)
    out = weights.loc[(weights.index >= start) & (weights.index <= end)].copy()
    for symbol in excluded_symbols:
        if symbol in out.columns:
            out[symbol] = 0.0
    mask = market_filter_mask(market_filter, out.index, dataset.end, cache_dir)
    out.loc[~mask, :] = 0.0
    asset_mask = asset_filter_frame(asset_filter, out, dataset.end, cache_dir)
    out = out.where(asset_mask, 0.0)
    return out


def summarize(dataset, variant, result, monthly, initial_cash, active_days):
    final = float(result["equity"]["equity"].iloc[-1])
    return {
        "dataset": dataset.name,
        "variant": variant["name"],
        "market_filter": variant["market_filter"],
        "asset_filter": variant["asset_filter"],
        "active_signal_days": int(active_days),
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
    lines = [
        "| " + " | ".join(frame.columns) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
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
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]

    all_rows = []
    for dataset in datasets:
        print(f"Loading {dataset.name}: {dataset.chains}")
        chain, loaded_from = load_chain_with_cache(dataset.chains)
        prepared = _build_option_indexes(chain)
        print(f"{dataset.name}: {len(chain):,} option rows from {loaded_from}")
        for variant in variants():
            variant_weights = make_weights(
                weights,
                dataset,
                variant["excluded_symbols"],
                variant["market_filter"],
                variant["asset_filter"],
                args.cache_dir,
            )
            active_days = (variant_weights.abs().sum(axis=1) > 0).sum()
            result = run_long_call_backtest(
                chain,
                variant_weights,
                args.initial_cash,
                variant["config"],
                prepared_indexes=prepared,
            )
            variant_dir = output_dir / dataset.name / variant["name"]
            variant_dir.mkdir(parents=True, exist_ok=True)
            for result_name, frame in result.items():
                frame.to_csv(variant_dir / f"{result_name}.csv", index=False)
            monthly = monthly_breakdown(result["equity"], dataset.start, args.initial_cash)
            monthly.to_csv(variant_dir / "monthly.csv", index_label="date")
            row = summarize(dataset, variant, result, monthly, args.initial_cash, active_days)
            all_rows.append(row)
            print(
                f"{dataset.name}/{variant['name']}: "
                f"final=${row['final_equity']:,.0f}, "
                f"dd={row['max_drawdown'] * 100:,.1f}%, "
                f"loss_months={row['losing_months']}, "
                f"worst=${row['worst_month']:,.0f}"
            )

    per_dataset = pd.DataFrame(all_rows)
    per_dataset.to_csv(output_dir / "per_dataset_summary.csv", index=False)
    pivot = per_dataset.pivot(index="variant", columns="dataset")
    combined_rows = []
    for variant in sorted(per_dataset["variant"].unique()):
        rows = per_dataset[per_dataset["variant"] == variant].set_index("dataset")
        if {"2024_holdout", "2025_winner"} - set(rows.index):
            continue
        final_2024 = float(rows.loc["2024_holdout", "final_equity"])
        final_2025 = float(rows.loc["2025_winner", "final_equity"])
        combined_rows.append(
            {
                "variant": variant,
                "final_2024": final_2024,
                "final_2025": final_2025,
                "min_final": min(final_2024, final_2025),
                "geo_final": math.sqrt(max(final_2024, 0.0) * max(final_2025, 0.0)),
                "worst_drawdown": min(
                    float(rows.loc["2024_holdout", "max_drawdown"]),
                    float(rows.loc["2025_winner", "max_drawdown"]),
                ),
                "total_losing_months": int(rows["losing_months"].sum()),
                "worst_month_any": float(rows["worst_month"].min()),
                "orders_2024": int(rows.loc["2024_holdout", "orders"]),
                "orders_2025": int(rows.loc["2025_winner", "orders"]),
            }
        )
    combined = pd.DataFrame(combined_rows)
    combined = combined.sort_values(
        ["min_final", "geo_final", "worst_drawdown"],
        ascending=[False, False, False],
    )
    combined.to_csv(output_dir / "combined_summary.csv", index=False)
    top = combined.head(12).copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        top[col] = top[col].map(lambda value: f"${value:,.0f}")
    top["worst_drawdown"] = top["worst_drawdown"].map(lambda value: f"{value * 100:,.1f}%")
    report = f"""# Stability Sweep

This sweep keeps the original signal model fixed and tests live-usable risk controls across two real OPRA windows:

- 2024 holdout: {args.start_2024} to {args.end_2024}
- 2025 winner: {args.start_2025} to {args.end_2025}

The ranking below prioritizes the higher minimum ending equity across both years, then the geometric average ending equity. That intentionally penalizes profiles that look spectacular in one regime and weak in the other.

## Top Combined Profiles

{markdown_table(top)}

Full per-window results are in `per_dataset_summary.csv`; combined results are in `combined_summary.csv`.
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
