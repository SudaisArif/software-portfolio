#!/usr/bin/env python3
import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.data import close_matrix, read_cached_prices
from algotrader.option_chain import OptionBacktestConfig, _build_option_indexes, load_option_chains


@dataclass
class SpreadPosition:
    spread_id: str
    underlying_symbol: str
    expiration: pd.Timestamp
    long_contract_id: str
    short_contract_id: str
    long_strike: float
    short_strike: float
    quantity: int
    entry_date: pd.Timestamp
    entry_debit: float
    entry_cost: float


@dataclass(frozen=True)
class Dataset:
    name: str
    chains: str
    start: str
    end: str


def parse_args():
    parser = argparse.ArgumentParser(description="Sweep real-options vertical call debit spreads across OPRA years.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_vertical_spread_sweep")
    return parser.parse_args()


def base_config():
    return OptionBacktestConfig(
        monthly_loss_stop=0.05,
        monthly_profit_lock=0.50,
        max_premium_fraction=0.15,
        max_total_premium_fraction=0.55,
        min_contract_price=1.0,
        max_contracts_per_trade=12,
        max_otm_pct=0.06,
        min_entry_weight=0.75,
        stop_loss=0.50,
        take_profit=0.80,
        max_hold_days=7,
        close_on_monthly_loss_stop=True,
    )


def variants():
    out = []
    for width in [0.03, 0.05, 0.08, 0.10]:
        out.append({"name": f"width{int(width*100):02d}", "width_pct": width, "config": base_config()})
    for premium in [0.10, 0.20, 0.25]:
        cfg = base_config()
        cfg = OptionBacktestConfig(**{**cfg.__dict__, "max_premium_fraction": premium})
        out.append({"name": f"width05_prem{int(premium*100):02d}", "width_pct": 0.05, "config": cfg})
    for stop, take in [(0.35, 0.65), (0.45, 0.75), (0.60, 1.00)]:
        cfg = base_config()
        cfg = OptionBacktestConfig(**{**cfg.__dict__, "stop_loss": stop, "take_profit": take})
        out.append({"name": f"width05_stop{int(stop*100):02d}_take{int(take*100):02d}", "width_pct": 0.05, "config": cfg})
    cfg = base_config()
    cfg = OptionBacktestConfig(**{**cfg.__dict__, "min_dte": 21, "max_dte": 60})
    out.append({"name": "width05_dte21_60", "width_pct": 0.05, "config": cfg})
    return out


def load_prices(symbols, end, cache_dir):
    prices = {symbol: read_cached_prices(cache_dir, symbol, "2016-01-01", end) for symbol in symbols}
    return close_matrix(prices)


def trend_mask(close_prices, dates):
    return (close_prices > close_prices.rolling(50).mean()).reindex(dates).ffill().fillna(False)


def quote_lookup_get(quote_lookup, date, contract_id):
    try:
        quote = quote_lookup.loc[(date, contract_id)]
    except KeyError:
        return None
    if isinstance(quote, pd.DataFrame):
        return quote.iloc[0] if not quote.empty else None
    return quote


def candidate_longs(subset, date, equity, config):
    subset = subset.copy()
    subset["dte"] = (subset["expiration"] - date).dt.days
    subset = subset[(subset["dte"] >= config.min_dte) & (subset["dte"] <= config.max_dte)]
    subset = subset[(subset["bid"] > 0.0) & (subset["ask"] > 0.0)]
    if config.min_contract_price > 0:
        subset = subset[subset["ask"] >= config.min_contract_price]
    subset = subset[subset["spread_pct"].fillna(999.0) <= config.max_spread_pct]
    if "open_interest" in subset.columns and subset["open_interest"].notna().any():
        subset = subset[subset["open_interest"].fillna(0) >= config.min_open_interest]
    if "volume" in subset.columns and subset["volume"].notna().any():
        subset = subset[subset["volume"].fillna(0) >= config.min_volume]
    if "delta" in subset.columns and subset["delta"].notna().any():
        subset["abs_delta"] = subset["delta"].abs()
        subset = subset[(subset["abs_delta"] >= config.min_delta) & (subset["abs_delta"] <= config.max_delta)]
        subset["score"] = (subset["abs_delta"] - config.target_delta).abs() + subset["spread_pct"].fillna(1.0)
    else:
        subset["moneyness"] = (subset["strike"] / subset["underlying_price"] - 1.0).abs()
        subset["score"] = subset["moneyness"] + subset["spread_pct"].fillna(1.0)
    if config.max_otm_pct is not None:
        subset["otm_pct"] = subset["strike"] / subset["underlying_price"] - 1.0
        subset = subset[subset["otm_pct"] <= config.max_otm_pct]
    if config.min_otm_pct is not None:
        subset["otm_pct"] = subset["strike"] / subset["underlying_price"] - 1.0
        subset = subset[subset["otm_pct"] >= config.min_otm_pct]
    if subset.empty:
        return subset
    subset["long_cost"] = subset["ask"] * config.contract_multiplier
    subset = subset[subset["long_cost"] <= equity]
    return subset.sort_values(["score", "dte"]).head(30)


def select_call_spread(call_groups, date, symbol, equity, config, width_pct):
    subset = call_groups.get((date, symbol))
    if subset is None or subset.empty:
        return None
    calls = subset.copy()
    longs = candidate_longs(calls, date, equity, config)
    if longs.empty:
        return None
    for _, long in longs.iterrows():
        target_strike = float(long["strike"]) * (1.0 + width_pct)
        shorts = calls[
            (calls["expiration"] == long["expiration"])
            & (calls["strike"] >= target_strike)
            & (calls["bid"] > 0.0)
            & (calls["ask"] > 0.0)
            & (calls["spread_pct"].fillna(999.0) <= config.max_spread_pct)
        ].copy()
        if shorts.empty:
            continue
        short = shorts.sort_values("strike").iloc[0]
        debit = float(long["ask"]) - float(short["bid"])
        if debit <= 0.10:
            continue
        spread_width = float(short["strike"]) - float(long["strike"])
        if spread_width <= 0.0:
            continue
        if debit * config.contract_multiplier > equity * config.max_premium_fraction:
            continue
        return {
            "long": long,
            "short": short,
            "debit": debit,
            "width": spread_width,
            "spread_id": f"{long['contract_id']}__SHORT__{short['contract_id']}",
        }
    return None


def mark_spread(quote_lookup, pos, date, config):
    long_quote = quote_lookup_get(quote_lookup, date, pos.long_contract_id)
    short_quote = quote_lookup_get(quote_lookup, date, pos.short_contract_id)
    if long_quote is None or short_quote is None:
        return None
    value = max(0.0, float(long_quote["bid"]) - float(short_quote["ask"]))
    return value * config.contract_multiplier * pos.quantity


def liquidate_spreads(quote_lookup, positions, date, config, order_rows, reason, cash):
    for key, pos in list(positions.items()):
        value = mark_spread(quote_lookup, pos, date, config)
        if value is None:
            continue
        exit_debit = value / (config.contract_multiplier * pos.quantity)
        pnl_pct = exit_debit / pos.entry_debit - 1.0 if pos.entry_debit > 0 else 0.0
        cash += value
        order_rows.append(
            {
                "date": date,
                "symbol": pos.underlying_symbol,
                "spread_id": pos.spread_id,
                "action": "SELL_SPREAD",
                "quantity": pos.quantity,
                "price": exit_debit,
                "cash_after": cash,
                "pnl_pct": pnl_pct,
                "reason": reason,
            }
        )
        del positions[key]
    return cash


def run_spread_backtest(chain, weights, close_prices, initial_cash, config, width_pct):
    dates = sorted(set(weights.index).intersection(set(chain["quote_date"].unique())).intersection(set(close_prices.index)))
    quote_lookup, call_groups = _build_option_indexes(chain)
    trend = trend_mask(close_prices, dates)
    cash = float(initial_cash)
    positions = {}
    equity_rows = []
    order_rows = []
    events = []
    current_month = pd.Timestamp(dates[0]).to_period("M")
    month_start_equity = cash
    monthly_stopped = False

    for raw_date in dates:
        date = pd.Timestamp(raw_date)
        if date.to_period("M") != current_month:
            current_month = date.to_period("M")
            month_start_equity = cash + sum(mark_spread(quote_lookup, pos, date, config) or 0.0 for pos in positions.values())
            monthly_stopped = False

        for key, pos in list(positions.items()):
            value = mark_spread(quote_lookup, pos, date, config)
            if value is None:
                continue
            exit_debit = value / (config.contract_multiplier * pos.quantity)
            pnl_pct = exit_debit / pos.entry_debit - 1.0 if pos.entry_debit > 0 else 0.0
            hold_days = (date - pos.entry_date).days
            reason = ""
            if pnl_pct <= -config.stop_loss:
                reason = "stop_loss"
            elif pnl_pct >= config.take_profit:
                reason = "take_profit"
            elif hold_days >= config.max_hold_days:
                reason = "max_hold"
            elif (pos.expiration - date).days <= 5:
                reason = "expiration"
            if reason:
                cash += value
                order_rows.append(
                    {
                        "date": date,
                        "symbol": pos.underlying_symbol,
                        "spread_id": pos.spread_id,
                        "action": "SELL_SPREAD",
                        "quantity": pos.quantity,
                        "price": exit_debit,
                        "cash_after": cash,
                        "pnl_pct": pnl_pct,
                        "reason": reason,
                    }
                )
                del positions[key]

        option_value = sum(mark_spread(quote_lookup, pos, date, config) or 0.0 for pos in positions.values())
        equity = cash + option_value
        month_return = equity / month_start_equity - 1.0 if month_start_equity > 0 else 0.0
        if not monthly_stopped and config.monthly_loss_stop > 0 and month_return <= -config.monthly_loss_stop:
            monthly_stopped = True
            events.append({"date": date, "event": "monthly_loss_stop", "month_return": month_return})
            if config.close_on_monthly_loss_stop:
                cash = liquidate_spreads(quote_lookup, positions, date, config, order_rows, "monthly_loss_stop", cash)
                option_value = sum(mark_spread(quote_lookup, pos, date, config) or 0.0 for pos in positions.values())
                equity = cash + option_value
        if not monthly_stopped and config.monthly_profit_lock > 0 and month_return >= config.monthly_profit_lock:
            monthly_stopped = True
            events.append({"date": date, "event": "monthly_profit_lock", "month_return": month_return})

        if not monthly_stopped:
            gross_premium = sum(pos.entry_cost for pos in positions.values())
            for symbol, weight in weights.loc[date].sort_values(ascending=False).items():
                symbol = str(symbol).upper()
                if symbol == "TLT" or weight <= 0 or weight < config.min_entry_weight:
                    continue
                if symbol in [p.underlying_symbol for p in positions.values()]:
                    continue
                if symbol in trend.columns and not bool(trend.loc[date, symbol]):
                    continue
                equity = cash + sum(mark_spread(quote_lookup, pos, date, config) or 0.0 for pos in positions.values())
                if gross_premium >= equity * config.max_total_premium_fraction:
                    break
                pick = select_call_spread(call_groups, date, symbol, equity, config, width_pct)
                if pick is None:
                    continue
                contract_cost = pick["debit"] * config.contract_multiplier
                max_contracts_by_cash = int(cash // contract_cost)
                remaining_total_budget = equity * config.max_total_premium_fraction - gross_premium
                max_contracts_by_total = int(remaining_total_budget // contract_cost)
                desired_premium = min(equity * abs(float(weight)), equity * config.max_premium_fraction)
                max_contracts_by_config = config.max_contracts_per_trade if config.max_contracts_per_trade > 0 else max_contracts_by_cash
                qty = max(1, min(max_contracts_by_cash, max_contracts_by_total, max_contracts_by_config, int(desired_premium // contract_cost)))
                if qty <= 0:
                    continue
                total_cost = contract_cost * qty
                if total_cost > cash or gross_premium + total_cost > equity * config.max_total_premium_fraction:
                    continue
                long = pick["long"]
                short = pick["short"]
                cash -= total_cost
                gross_premium += total_cost
                pos = SpreadPosition(
                    spread_id=pick["spread_id"],
                    underlying_symbol=symbol,
                    expiration=pd.Timestamp(long["expiration"]),
                    long_contract_id=str(long["contract_id"]),
                    short_contract_id=str(short["contract_id"]),
                    long_strike=float(long["strike"]),
                    short_strike=float(short["strike"]),
                    quantity=qty,
                    entry_date=date,
                    entry_debit=float(pick["debit"]),
                    entry_cost=total_cost,
                )
                positions[pos.spread_id] = pos
                order_rows.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "spread_id": pos.spread_id,
                        "action": "BUY_SPREAD",
                        "quantity": qty,
                        "price": pos.entry_debit,
                        "cash_after": cash,
                        "pnl_pct": 0.0,
                        "reason": "entry",
                    }
                )

        option_value = sum(mark_spread(quote_lookup, pos, date, config) or 0.0 for pos in positions.values())
        equity_rows.append({"date": date, "cash": cash, "spread_value": option_value, "equity": cash + option_value, "open_spreads": len(positions)})

    return {"equity": pd.DataFrame(equity_rows), "orders": pd.DataFrame(order_rows), "events": pd.DataFrame(events)}


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
    if "TLT" in weights.columns:
        weights["TLT"] = 0.0
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]
    rows = []
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        close_prices = load_prices(weights.columns, dataset.end, args.cache_dir)
        period_weights = weights.loc[pd.Timestamp(dataset.start) : pd.Timestamp(dataset.end)].reindex(
            close_prices.loc[pd.Timestamp(dataset.start) : pd.Timestamp(dataset.end)].index
        ).fillna(0.0)
        for variant in variants():
            result = run_spread_backtest(chain, period_weights, close_prices, args.initial_cash, variant["config"], variant["width_pct"])
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
                f"loss_months={(monthly['monthly_profit'] < 0).sum()}"
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
        combined_rows.append(
            {
                "variant": variant,
                "final_2024": final_2024,
                "final_2025": final_2025,
                "min_final": min(final_2024, final_2025),
                "geo_final": math.sqrt(max(0.0, final_2024) * max(0.0, final_2025)),
                "worst_drawdown": min(float(part.loc["2024_holdout", "max_drawdown"]), float(part.loc["2025_winner", "max_drawdown"])),
                "total_losing_months": int(part["losing_months"].sum()),
                "worst_month_any": float(part["worst_month"].min()),
                "orders_2024": int(part.loc["2024_holdout", "orders"]),
                "orders_2025": int(part.loc["2025_winner", "orders"]),
            }
        )
    combined = pd.DataFrame(combined_rows).sort_values(["min_final", "geo_final"], ascending=[False, False])
    combined.to_csv(output_dir / "combined_summary.csv", index=False)
    top = combined.head(12).copy()
    for col in ["final_2024", "final_2025", "min_final", "geo_final", "worst_month_any"]:
        top[col] = top[col].map(lambda value: f"${value:,.0f}")
    top["worst_drawdown"] = top["worst_drawdown"].map(lambda value: f"{value * 100:,.1f}%")
    report = f"""# Vertical Call Spread Stability Sweep

This tests bullish debit call spreads using real OPRA bid/ask data. Buys use long-call ask and short-call bid; exits use long-call bid and short-call ask.

## Top Combined Profiles

{markdown_table(top)}
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
