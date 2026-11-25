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
    parser = argparse.ArgumentParser(description="Sweep entry/regime filters for the stabilized long-call strategy.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_entry_regime_sweep")
    return parser.parse_args()


def stable_config(**overrides):
    values = {
        "monthly_loss_stop": 0.05,
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
        "close_on_monthly_loss_stop": True,
    }
    values.update(overrides)
    return OptionBacktestConfig(**values)


def variants():
    base_excludes = ["TLT"]
    rows = [
        ("stable_reference", {}, "none", "none", base_excludes),
        ("stable_stop35", {"stop_loss": 0.35}, "none", "none", base_excludes),
        ("trend50", {}, "none", "trend50", base_excludes),
        ("trend50_stop35", {"stop_loss": 0.35}, "none", "trend50", base_excludes),
        ("exclude_xlf_xlv", {}, "none", "none", base_excludes + ["XLF", "XLV"]),
        ("trend50_exclude_xlf_xlv", {}, "none", "trend50", base_excludes + ["XLF", "XLV"]),
        ("stop35_exclude_xlf_xlv", {"stop_loss": 0.35}, "none", "none", base_excludes + ["XLF", "XLV"]),
        ("trend50_stop35_exclude_xlf_xlv", {"stop_loss": 0.35}, "none", "trend50", base_excludes + ["XLF", "XLV"]),
        ("exclude_xlf_xlv_xlk_xly", {}, "none", "none", base_excludes + ["XLF", "XLV", "XLK", "XLY"]),
        ("single_name_gld_xle", {}, "none", "none", base_excludes + ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLV", "XLY"]),
        ("asset_mom5", {}, "none", "mom5", base_excludes),
        ("asset_mom10", {}, "none", "mom10", base_excludes),
        ("asset_mom21", {}, "none", "mom21", base_excludes),
        ("asset_mom63", {}, "none", "mom63", base_excludes),
        ("trend50_mom5", {}, "none", "trend50_mom5", base_excludes),
        ("trend50_mom10", {}, "none", "trend50_mom10", base_excludes),
        ("trend50_mom21", {}, "none", "trend50_mom21", base_excludes),
        ("trend50_mom63", {}, "none", "trend50_mom63", base_excludes),
        ("near_high20_5", {}, "none", "near_high20_5", base_excludes),
        ("near_high20_3", {}, "none", "near_high20_3", base_excludes),
        ("trend50_near_high20_5", {}, "none", "trend50_near_high20_5", base_excludes),
        ("trend50_near_high20_3", {}, "none", "trend50_near_high20_3", base_excludes),
        ("spy_mom21", {}, "spy_mom21", "none", base_excludes),
        ("spy_sma50", {}, "spy_sma50", "none", base_excludes),
        ("spy_sma100", {}, "spy_sma100", "none", base_excludes),
        ("vix20", {}, "vix20", "none", base_excludes),
        ("vix22", {}, "vix22", "none", base_excludes),
        ("vix20_trend50", {}, "vix20", "trend50", base_excludes),
        ("vix22_trend50", {}, "vix22", "trend50", base_excludes),
        ("spy_mom21_trend50", {}, "spy_mom21", "trend50", base_excludes),
        ("spy_sma50_trend50", {}, "spy_sma50", "trend50", base_excludes),
        ("risk_on_vix22_spy50", {}, "risk_on_vix22_spy50", "none", base_excludes),
        ("risk_on_vix22_spy50_trend50", {}, "risk_on_vix22_spy50", "trend50", base_excludes),
        ("risk_on_vix22_spy50_exclude", {}, "risk_on_vix22_spy50", "none", base_excludes + ["XLF", "XLV"]),
        ("risk_on_vix22_spy50_trend50_exclude", {}, "risk_on_vix22_spy50", "trend50", base_excludes + ["XLF", "XLV"]),
        ("trend50_mom5_exclude", {}, "none", "trend50_mom5", base_excludes + ["XLF", "XLV"]),
        ("trend50_mom10_exclude", {}, "none", "trend50_mom10", base_excludes + ["XLF", "XLV"]),
        ("near_high20_5_exclude", {}, "none", "near_high20_5", base_excludes + ["XLF", "XLV"]),
    ]
    return [
        {
            "name": name,
            "config": stable_config(**config_overrides),
            "market_filter": market_filter,
            "asset_filter": asset_filter,
            "excludes": excludes,
        }
        for name, config_overrides, market_filter, asset_filter, excludes in rows
    ]


def market_filter_mask(name, dates, end, cache_dir):
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(None)
    if name == "none":
        return pd.Series(True, index=dates)
    spy = read_cached_prices(cache_dir, "SPY", "2016-01-01", end)["Close"]
    vix = read_cached_prices(cache_dir, "^VIX", "2016-01-01", end)["Close"]
    spy_mom21 = spy / spy.shift(21) - 1.0 > 0.0
    spy_sma50 = spy > spy.rolling(50).mean()
    spy_sma100 = spy > spy.rolling(100).mean()
    vix20 = vix < 20.0
    vix22 = vix < 22.0
    pieces = {
        "spy_mom21": spy_mom21,
        "spy_sma50": spy_sma50,
        "spy_sma100": spy_sma100,
        "vix20": vix20,
        "vix22": vix22,
        "risk_on_vix22_spy50": spy_sma50 & vix22.reindex(spy.index).ffill().fillna(False),
    }
    if name not in pieces:
        raise ValueError(f"Unknown market filter: {name}")
    return pieces[name].reindex(dates).ffill().fillna(False).astype(bool)


def asset_filter_frame(name, weights, end, cache_dir):
    if name == "none":
        return pd.DataFrame(True, index=weights.index, columns=weights.columns)
    masks = {}
    for symbol in weights.columns:
        try:
            close = read_cached_prices(cache_dir, symbol, "2016-01-01", end)["Close"]
        except FileNotFoundError:
            masks[symbol] = pd.Series(False, index=weights.index)
            continue
        trend50 = close > close.rolling(50).mean()
        mom5 = close / close.shift(5) - 1.0 > 0.0
        mom10 = close / close.shift(10) - 1.0 > 0.0
        mom21 = close / close.shift(21) - 1.0 > 0.0
        mom63 = close / close.shift(63) - 1.0 > 0.0
        near_high20_5 = close / close.rolling(20).max() - 1.0 >= -0.05
        near_high20_3 = close / close.rolling(20).max() - 1.0 >= -0.03
        pieces = {
            "trend50": trend50,
            "mom5": mom5,
            "mom10": mom10,
            "mom21": mom21,
            "mom63": mom63,
            "trend50_mom5": trend50 & mom5,
            "trend50_mom10": trend50 & mom10,
            "trend50_mom21": trend50 & mom21,
            "trend50_mom63": trend50 & mom63,
            "near_high20_5": near_high20_5,
            "near_high20_3": near_high20_3,
            "trend50_near_high20_5": trend50 & near_high20_5,
            "trend50_near_high20_3": trend50 & near_high20_3,
        }
        if name not in pieces:
            raise ValueError(f"Unknown asset filter: {name}")
        masks[symbol] = pieces[name].reindex(weights.index).ffill().fillna(False).astype(bool)
    return pd.DataFrame(masks, index=weights.index)


def filtered_weights(weights, dataset, variant, cache_dir):
    start = pd.Timestamp(dataset.start)
    end = pd.Timestamp(dataset.end)
    out = weights.loc[(weights.index >= start) & (weights.index <= end)].copy()
    for symbol in variant["excludes"]:
        if symbol in out.columns:
            out[symbol] = 0.0
    market_mask = market_filter_mask(variant["market_filter"], out.index, dataset.end, cache_dir)
    out.loc[~market_mask, :] = 0.0
    asset_mask = asset_filter_frame(variant["asset_filter"], out, dataset.end, cache_dir)
    return out.where(asset_mask, 0.0)


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
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]
    rows = []
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        prepared = _build_option_indexes(chain)
        for variant in variants():
            vweights = filtered_weights(weights, dataset, variant, args.cache_dir)
            active_days = int((vweights.abs().sum(axis=1) > 0.0).sum())
            result = run_long_call_backtest(chain, vweights, args.initial_cash, variant["config"], prepared_indexes=prepared)
            variant_dir = output_dir / dataset.name / variant["name"]
            variant_dir.mkdir(parents=True, exist_ok=True)
            for name, frame in result.items():
                frame.to_csv(variant_dir / f"{name}.csv", index=False)
            monthly = monthly_breakdown(result["equity"], dataset.start, args.initial_cash)
            monthly.to_csv(variant_dir / "monthly.csv", index_label="date")
            final = float(result["equity"]["equity"].iloc[-1])
            rows.append(
                {
                    "dataset": dataset.name,
                    "variant": variant["name"],
                    "market_filter": variant["market_filter"],
                    "asset_filter": variant["asset_filter"],
                    "excludes": ",".join(variant["excludes"]),
                    "active_days": active_days,
                    "final_equity": final,
                    "total_return": final / args.initial_cash - 1.0,
                    "max_drawdown": max_drawdown(result["equity"]),
                    "orders": len(result["orders"]),
                    "losing_months": int((monthly["monthly_profit"] < 0).sum()),
                    "worst_month": float(monthly["monthly_profit"].min()),
                    "best_month": float(monthly["monthly_profit"].max()),
                }
            )
            print(
                f"{dataset.name}/{variant['name']}: final=${final:,.0f}, "
                f"dd={max_drawdown(result['equity']) * 100:,.1f}%, "
                f"loss_months={(monthly['monthly_profit'] < 0).sum()}, active={active_days}"
            )

    per_dataset = pd.DataFrame(rows)
    per_dataset.to_csv(output_dir / "per_dataset_summary.csv", index=False)
    combined_rows = []
    for variant in sorted(per_dataset["variant"].unique()):
        part = per_dataset[per_dataset["variant"] == variant].set_index("dataset")
        if {"2024_holdout", "2025_winner"} - set(part.index):
            continue
        final_2024 = float(part.loc["2024_holdout", "final_equity"])
        final_2025 = float(part.loc["2025_winner", "final_equity"])
        gap_ratio = max(final_2024, final_2025) / max(1.0, min(final_2024, final_2025))
        combined_rows.append(
            {
                "variant": variant,
                "final_2024": final_2024,
                "final_2025": final_2025,
                "min_final": min(final_2024, final_2025),
                "geo_final": math.sqrt(max(0.0, final_2024) * max(0.0, final_2025)),
                "gap_ratio": gap_ratio,
                "worst_drawdown": min(float(part.loc["2024_holdout", "max_drawdown"]), float(part.loc["2025_winner", "max_drawdown"])),
                "total_losing_months": int(part["losing_months"].sum()),
                "worst_month_any": float(part["worst_month"].min()),
                "orders_2024": int(part.loc["2024_holdout", "orders"]),
                "orders_2025": int(part.loc["2025_winner", "orders"]),
            }
        )
    combined = pd.DataFrame(combined_rows)
    combined = combined.sort_values(["min_final", "gap_ratio", "geo_final"], ascending=[False, True, False])
    combined.to_csv(output_dir / "combined_summary.csv", index=False)
    top = combined.head(15).copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        top[col] = top[col].map(lambda value: f"${value:,.0f}")
    top["gap_ratio"] = top["gap_ratio"].map(lambda value: f"{value:,.2f}x")
    top["worst_drawdown"] = top["worst_drawdown"].map(lambda value: f"{value * 100:,.1f}%")
    report = f"""# Entry Regime Filter Sweep

This sweep ranks profiles by weaker-year ending equity first, then by smaller 2024/2025 gap ratio.

## Top Profiles

{markdown_table(top)}
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
