#!/usr/bin/env python3
import argparse
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.data import close_matrix, read_cached_prices
from algotrader.option_chain import (
    OptionBacktestConfig,
    OptionPosition,
    _build_option_indexes,
    _mark_positions,
    _quote_for_position_lookup,
    _select_call_from_subset,
    load_option_chains,
)


@dataclass(frozen=True)
class Dataset:
    name: str
    chains: str
    start: str
    end: str


def parse_args():
    parser = argparse.ArgumentParser(description="Sweep equity-core plus options-overlay stability profiles.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--chains-2024", default="data/options/databento_year_2024_04_29_2025_04_25/chains.parquet")
    parser.add_argument("--start-2024", default="2024-04-29")
    parser.add_argument("--end-2024", default="2025-04-25")
    parser.add_argument("--chains-2025", default="data/options/databento_year_2025_04_28_2026_04_24/chains.parquet")
    parser.add_argument("--start-2025", default="2025-04-28")
    parser.add_argument("--end-2025", default="2026-04-24")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="artifacts/databento_hybrid_stability_sweep")
    return parser.parse_args()


def option_base_config():
    return OptionBacktestConfig(
        monthly_loss_stop=0.05,
        monthly_profit_lock=0.50,
        max_premium_fraction=0.15,
        max_total_premium_fraction=0.55,
        min_contract_price=1.0,
        max_contracts_per_trade=12,
        max_otm_pct=0.06,
        min_entry_weight=0.75,
        stop_loss=0.45,
        take_profit=1.25,
        max_hold_days=7,
        close_on_monthly_loss_stop=True,
    )


def variants():
    base = option_base_config()
    return [
        {"name": "pure_options_reference", "core_mode": "cash", "core_gross": 0.0, "option_config": base},
        {"name": "spy_core_40", "core_mode": "spy", "core_gross": 0.40, "option_config": base},
        {"name": "spy_core_60", "core_mode": "spy", "core_gross": 0.60, "option_config": base},
        {"name": "spy_core_75", "core_mode": "spy", "core_gross": 0.75, "option_config": base},
        {"name": "spy_core_60_option35", "core_mode": "spy", "core_gross": 0.60, "option_config": replace(base, max_total_premium_fraction=0.35)},
        {"name": "spy_core_60_option25", "core_mode": "spy", "core_gross": 0.60, "option_config": replace(base, max_total_premium_fraction=0.25)},
        {"name": "spy_qqq_core_60", "core_mode": "spy_qqq", "core_gross": 0.60, "option_config": base},
        {"name": "spy_qqq_core_75", "core_mode": "spy_qqq", "core_gross": 0.75, "option_config": base},
        {"name": "signal_core_40", "core_mode": "signal", "core_gross": 0.40, "option_config": base},
        {"name": "signal_core_60", "core_mode": "signal", "core_gross": 0.60, "option_config": base},
        {"name": "signal_or_spy_core_60", "core_mode": "signal_or_spy", "core_gross": 0.60, "option_config": base},
        {"name": "signal_or_spy_core_75", "core_mode": "signal_or_spy", "core_gross": 0.75, "option_config": base},
    ]


def load_prices(symbols, start, end, cache_dir):
    prices = {}
    for symbol in symbols:
        prices[symbol] = read_cached_prices(cache_dir, symbol, "2016-01-01", end)
    return close_matrix(prices)


def normalize_signal_weights(row, gross):
    positive = row.clip(lower=0.0)
    total = positive.sum()
    if total <= 0.0 or gross <= 0.0:
        return positive * 0.0
    return positive / total * gross


def core_target_weights(signal_weights, mode, gross):
    out = pd.DataFrame(0.0, index=signal_weights.index, columns=signal_weights.columns)
    if gross <= 0.0 or mode == "cash":
        return out
    if mode == "spy":
        out["SPY"] = gross
        return out
    if mode == "spy_qqq":
        out["SPY"] = gross * 0.50
        out["QQQ"] = gross * 0.50
        return out
    if mode in {"signal", "signal_or_spy"}:
        for date, row in signal_weights.iterrows():
            target = normalize_signal_weights(row, gross)
            if mode == "signal_or_spy" and target.sum() <= 0.0:
                target["SPY"] = gross
            out.loc[date, target.index] = target
        return out
    raise ValueError(f"Unknown core mode: {mode}")


def asset_trend_mask(close_prices, dates):
    trend = close_prices > close_prices.rolling(50).mean()
    return trend.reindex(dates).ffill().fillna(False)


def rebalance_stocks(cash, shares, target_weights, prices, equity, non_stock_value, cost_bps):
    if equity <= 0.0:
        return cash, shares, 0.0
    desired_dollars = target_weights.reindex(prices.index).fillna(0.0) * equity
    max_stock_value = max(0.0, equity - non_stock_value)
    if desired_dollars.sum() > max_stock_value:
        desired_dollars = desired_dollars / desired_dollars.sum() * max_stock_value
    current_dollars = shares.reindex(prices.index).fillna(0.0) * prices
    trades = desired_dollars - current_dollars
    traded_value = float(trades.abs().sum())
    cost = traded_value * cost_bps / 10000.0
    cash -= float(trades.sum()) + cost
    new_shares = shares.reindex(prices.index).fillna(0.0) + trades / prices.replace(0.0, pd.NA)
    return cash, new_shares.fillna(0.0), cost


def liquidate_options(quote_lookup, positions, date, config, order_rows, reason, cash):
    for key, pos in list(positions.items()):
        quote = _quote_for_position_lookup(quote_lookup, pos, date)
        if quote is None:
            continue
        exit_price = float(quote["bid"])
        pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
        cash += exit_price * config.contract_multiplier * pos.quantity
        order_rows.append(
            {
                "date": date,
                "symbol": pos.underlying_symbol,
                "contract_id": pos.contract_id,
                "action": "SELL",
                "quantity": pos.quantity,
                "price": exit_price,
                "cash_after": cash,
                "pnl_pct": pnl_pct,
                "reason": reason,
            }
        )
        del positions[key]
    return cash


def run_hybrid_backtest(chain, prepared, close_prices, signal_weights, initial_cash, variant):
    config = variant["option_config"]
    dates = sorted(set(signal_weights.index).intersection(set(chain["quote_date"].unique())).intersection(set(close_prices.index)))
    if not dates:
        raise ValueError("No overlapping dates")
    quote_lookup, call_groups = prepared
    trend_mask = asset_trend_mask(close_prices, dates)
    core_weights = core_target_weights(signal_weights.loc[dates], variant["core_mode"], variant["core_gross"])

    cash = float(initial_cash)
    shares = pd.Series(0.0, index=close_prices.columns)
    positions = {}
    stopped_symbol_dates = {}
    equity_rows = []
    order_rows = []
    events = []
    current_month = pd.Timestamp(dates[0]).to_period("M")
    month_start_equity = cash
    monthly_stopped = False

    for idx, raw_date in enumerate(dates):
        date = pd.Timestamp(raw_date)
        prices = close_prices.loc[date].ffill()
        stock_value = float((shares.reindex(prices.index).fillna(0.0) * prices).sum())
        option_value = _mark_positions(quote_lookup, positions, date, config)
        equity = cash + stock_value + option_value

        if date.to_period("M") != current_month:
            current_month = date.to_period("M")
            month_start_equity = equity
            monthly_stopped = False

        for key, pos in list(positions.items()):
            quote = _quote_for_position_lookup(quote_lookup, pos, date)
            if quote is None:
                continue
            exit_price = float(quote["bid"])
            pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
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
                cash += exit_price * config.contract_multiplier * pos.quantity
                if reason == "stop_loss":
                    stopped_symbol_dates[pos.underlying_symbol] = date
                order_rows.append(
                    {
                        "date": date,
                        "symbol": pos.underlying_symbol,
                        "contract_id": pos.contract_id,
                        "action": "SELL",
                        "quantity": pos.quantity,
                        "price": exit_price,
                        "cash_after": cash,
                        "pnl_pct": pnl_pct,
                        "reason": reason,
                    }
                )
                del positions[key]

        stock_value = float((shares.reindex(prices.index).fillna(0.0) * prices).sum())
        option_value = _mark_positions(quote_lookup, positions, date, config)
        equity = cash + stock_value + option_value
        month_return = equity / month_start_equity - 1.0 if month_start_equity > 0.0 else 0.0
        if not monthly_stopped and config.monthly_loss_stop > 0 and month_return <= -config.monthly_loss_stop:
            monthly_stopped = True
            events.append({"date": date, "event": "monthly_loss_stop", "month_return": month_return})
            if config.close_on_monthly_loss_stop:
                cash = liquidate_options(quote_lookup, positions, date, config, order_rows, "monthly_loss_stop", cash)
        if not monthly_stopped and config.monthly_profit_lock > 0 and month_return >= config.monthly_profit_lock:
            monthly_stopped = True
            events.append({"date": date, "event": "monthly_profit_lock", "month_return": month_return})

        stock_value = float((shares.reindex(prices.index).fillna(0.0) * prices).sum())
        option_value = _mark_positions(quote_lookup, positions, date, config)
        equity = cash + stock_value + option_value
        cash, shares, stock_cost = rebalance_stocks(
            cash,
            shares,
            core_weights.loc[date],
            prices,
            equity,
            option_value,
            cost_bps=8.0,
        )

        if not monthly_stopped:
            stock_value = float((shares.reindex(prices.index).fillna(0.0) * prices).sum())
            option_value = _mark_positions(quote_lookup, positions, date, config)
            equity = cash + stock_value + option_value
            gross_premium = sum(pos.entry_cost for pos in positions.values())
            weights = signal_weights.loc[date].sort_values(ascending=False)
            for symbol, weight in weights.items():
                symbol = str(symbol).upper()
                if symbol == "TLT" or weight <= 0 or weight < config.min_entry_weight:
                    continue
                if symbol in [p.underlying_symbol for p in positions.values()]:
                    continue
                if symbol in trend_mask.columns and not bool(trend_mask.loc[date, symbol]):
                    continue
                last_stop_date = stopped_symbol_dates.get(symbol)
                if config.stop_loss_cooldown_days > 0 and last_stop_date is not None:
                    if (date - last_stop_date).days <= config.stop_loss_cooldown_days:
                        continue
                if gross_premium >= equity * config.max_total_premium_fraction:
                    break
                subset = call_groups.get((date, symbol))
                if subset is None:
                    continue
                pick = _select_call_from_subset(subset.copy(), date, equity, config)
                if pick is None:
                    continue
                contract_cost = float(pick["ask"]) * config.contract_multiplier
                max_contracts_by_cash = int(cash // contract_cost)
                if max_contracts_by_cash <= 0:
                    continue
                desired_premium = min(equity * abs(float(weight)), equity * config.max_premium_fraction)
                remaining_total_budget = equity * config.max_total_premium_fraction - gross_premium
                max_contracts_by_total = int(remaining_total_budget // contract_cost)
                if max_contracts_by_total <= 0:
                    continue
                max_contracts_by_config = config.max_contracts_per_trade if config.max_contracts_per_trade > 0 else max_contracts_by_cash
                qty = max(1, min(max_contracts_by_cash, max_contracts_by_total, max_contracts_by_config, int(desired_premium // contract_cost)))
                total_cost = contract_cost * qty
                if total_cost > cash or gross_premium + total_cost > equity * config.max_total_premium_fraction:
                    continue
                cash -= total_cost
                gross_premium += total_cost
                pos = OptionPosition(
                    contract_id=str(pick["contract_id"]),
                    underlying_symbol=symbol,
                    expiration=pd.Timestamp(pick["expiration"]),
                    strike=float(pick["strike"]),
                    option_type="C",
                    quantity=qty,
                    entry_date=date,
                    entry_price=float(pick["ask"]),
                    entry_cost=total_cost,
                )
                positions[pos.contract_id] = pos
                order_rows.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "contract_id": pos.contract_id,
                        "action": "BUY",
                        "quantity": qty,
                        "price": pos.entry_price,
                        "cash_after": cash,
                        "pnl_pct": 0.0,
                        "reason": "entry",
                    }
                )

        stock_value = float((shares.reindex(prices.index).fillna(0.0) * prices).sum())
        option_value = _mark_positions(quote_lookup, positions, date, config)
        equity = cash + stock_value + option_value
        equity_rows.append(
            {
                "date": date,
                "cash": cash,
                "stock_value": stock_value,
                "option_value": option_value,
                "equity": equity,
                "open_options": len(positions),
                "stock_cost": stock_cost,
            }
        )
    return {
        "equity": pd.DataFrame(equity_rows),
        "orders": pd.DataFrame(order_rows),
        "events": pd.DataFrame(events),
    }


def monthly_breakdown(equity, start, initial_cash):
    monthly = equity.assign(date=pd.to_datetime(equity["date"])).set_index("date")["equity"].resample("ME").last()
    monthly = pd.concat([pd.Series([initial_cash], index=[pd.Timestamp(start)]), monthly]).dropna()
    return pd.DataFrame({"equity": monthly, "monthly_profit": monthly.diff(), "monthly_return": monthly.pct_change()}).dropna()


def max_drawdown(equity):
    curve = equity["equity"]
    return float((curve / curve.cummax() - 1.0).min())


def markdown_table(frame):
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
    weights["TLT"] = 0.0
    datasets = [
        Dataset("2024_holdout", args.chains_2024, args.start_2024, args.end_2024),
        Dataset("2025_winner", args.chains_2025, args.start_2025, args.end_2025),
    ]
    symbols = list(weights.columns)
    rows = []
    for dataset in datasets:
        chain = load_option_chains(dataset.chains)
        prepared = _build_option_indexes(chain)
        close_prices = load_prices(symbols, dataset.start, dataset.end, args.cache_dir)
        dataset_closes = close_prices.loc[pd.Timestamp(dataset.start) : pd.Timestamp(dataset.end)]
        signal_weights = weights.loc[pd.Timestamp(dataset.start) : pd.Timestamp(dataset.end)].reindex(dataset_closes.index).fillna(0.0)
        for variant in variants():
            result = run_hybrid_backtest(chain, prepared, close_prices, signal_weights, args.initial_cash, variant)
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
                    "core_mode": variant["core_mode"],
                    "core_gross": variant["core_gross"],
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
                "geo_final": math.sqrt(final_2024 * final_2025),
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
    report = f"""# Hybrid Stability Sweep

This tests fractional-equity cores plus the stabilized real-options overlay across both OPRA years.

## Top Combined Profiles

{markdown_table(top)}

Full results:

- `per_dataset_summary.csv`
- `combined_summary.csv`
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Summary: {output_dir / 'combined_summary.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
