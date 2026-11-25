#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.option_chain import OptionBacktestConfig, load_option_chains, run_long_call_backtest


def money(value):
    return f"${value:,.2f}"


def pct(value):
    return f"{value * 100:,.2f}%"


def markdown_table(frame, max_rows=None):
    if frame.empty:
        return "_No rows._"
    if max_rows:
        frame = frame.head(max_rows)
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in frame.iterrows():
        values = []
        for col in columns:
            value = row[col]
            if isinstance(value, pd.Timestamp):
                values.append(str(value.date()))
            elif isinstance(value, float):
                values.append(f"{value:,.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(description="Run a real historical options-chain long-call backtest.")
    parser.add_argument("--chains", required=True, help="CSV file or directory of historical option-chain CSVs")
    parser.add_argument("--weights", default="reports/latest_weights.csv")
    parser.add_argument("--exclude-symbols", default="", help="Comma-separated symbols to zero out in the weights file")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", default="artifacts/real_options_backtest")
    parser.add_argument("--monthly-loss-stop", type=float, default=0.20)
    parser.add_argument("--monthly-profit-lock", type=float, default=0.60)
    parser.add_argument("--min-dte", type=int, default=14)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--max-spread-pct", type=float, default=0.18)
    parser.add_argument("--max-premium-fraction", type=float, default=0.35)
    parser.add_argument("--max-total-premium-fraction", type=float, default=0.85)
    parser.add_argument("--min-contract-price", type=float, default=0.0)
    parser.add_argument("--max-contracts-per-trade", type=int, default=0)
    parser.add_argument("--min-otm-pct", type=float, default=None)
    parser.add_argument("--max-otm-pct", type=float, default=None)
    parser.add_argument("--min-entry-weight", type=float, default=0.0)
    parser.add_argument("--stop-loss", type=float, default=0.45)
    parser.add_argument("--take-profit", type=float, default=1.25)
    parser.add_argument("--profit-lock-activation", type=float, default=0.0)
    parser.add_argument("--profit-lock-floor", type=float, default=0.0)
    parser.add_argument("--profit-lock-trail", type=float, default=0.0)
    parser.add_argument("--max-hold-days", type=int, default=7)
    parser.add_argument("--exit-losing-on-signal-loss", action="store_true")
    parser.add_argument("--signal-loss-weight-threshold", type=float, default=0.0)
    parser.add_argument("--min-hold-days-for-signal-exit", type=int, default=1)
    parser.add_argument("--stop-loss-cooldown-days", type=int, default=0)
    parser.add_argument("--min-equity-for-new-entries", type=float, default=0.0)
    parser.add_argument("--low-equity-risk-scale-threshold", type=float, default=0.0)
    parser.add_argument("--low-equity-risk-scale", type=float, default=1.0)
    parser.add_argument("--max-equity-drawdown-for-new-entries", type=float, default=0.0)
    parser.add_argument("--drawdown-risk-scale-threshold", type=float, default=0.0)
    parser.add_argument("--drawdown-risk-scale", type=float, default=1.0)
    parser.add_argument("--close-on-monthly-loss-stop", action="store_true")
    parser.add_argument("--close-losers-on-monthly-loss-stop", action="store_true")
    parser.add_argument("--close-on-monthly-profit-lock", action="store_true")
    parser.add_argument("--close-before-month-end", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    chain = load_option_chains(args.chains)
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    excluded_symbols = [symbol.strip().upper() for symbol in args.exclude_symbols.split(",") if symbol.strip()]
    for symbol in excluded_symbols:
        if symbol in weights.columns:
            weights[symbol] = 0.0
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    weights = weights.loc[(weights.index >= start) & (weights.index <= end)]
    config = OptionBacktestConfig(
        monthly_loss_stop=args.monthly_loss_stop,
        monthly_profit_lock=args.monthly_profit_lock,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        max_spread_pct=args.max_spread_pct,
        max_premium_fraction=args.max_premium_fraction,
        max_total_premium_fraction=args.max_total_premium_fraction,
        min_contract_price=args.min_contract_price,
        max_contracts_per_trade=args.max_contracts_per_trade,
        min_otm_pct=args.min_otm_pct,
        max_otm_pct=args.max_otm_pct,
        min_entry_weight=args.min_entry_weight,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        profit_lock_activation=args.profit_lock_activation,
        profit_lock_floor=args.profit_lock_floor,
        profit_lock_trail=args.profit_lock_trail,
        max_hold_days=args.max_hold_days,
        exit_losing_on_signal_loss=args.exit_losing_on_signal_loss,
        signal_loss_weight_threshold=args.signal_loss_weight_threshold,
        min_hold_days_for_signal_exit=args.min_hold_days_for_signal_exit,
        stop_loss_cooldown_days=args.stop_loss_cooldown_days,
        min_equity_for_new_entries=args.min_equity_for_new_entries,
        low_equity_risk_scale_threshold=args.low_equity_risk_scale_threshold,
        low_equity_risk_scale=args.low_equity_risk_scale,
        max_equity_drawdown_for_new_entries=args.max_equity_drawdown_for_new_entries,
        drawdown_risk_scale_threshold=args.drawdown_risk_scale_threshold,
        drawdown_risk_scale=args.drawdown_risk_scale,
        close_on_monthly_loss_stop=args.close_on_monthly_loss_stop,
        close_losers_on_monthly_loss_stop=args.close_losers_on_monthly_loss_stop,
        close_on_monthly_profit_lock=args.close_on_monthly_profit_lock,
        close_before_month_end=args.close_before_month_end,
    )
    result = run_long_call_backtest(chain, weights, args.initial_cash, config)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in result.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False)
    equity = result["equity"]
    if equity.empty:
        raise SystemExit("No overlapping chain/signal dates produced a backtest.")
    final = float(equity["equity"].iloc[-1])
    total_return = final / args.initial_cash - 1.0
    orders = result["orders"]
    monthly = equity.assign(date=pd.to_datetime(equity["date"])).set_index("date")["equity"].resample("ME").last()
    monthly = pd.concat([pd.Series([args.initial_cash], index=[pd.Timestamp(args.start)]), monthly]).dropna()
    monthly_out = pd.DataFrame({"equity": monthly, "monthly_profit": monthly.diff(), "monthly_return": monthly.pct_change()}).dropna()
    monthly_out.to_csv(output_dir / "monthly.csv", index_label="date")

    orders_by_symbol = pd.DataFrame()
    if not orders.empty:
        orders_by_symbol = orders.groupby("symbol").agg(
            order_count=("symbol", "size"),
            buys=("action", lambda s: int((s == "BUY").sum())),
            sells=("action", lambda s: int((s == "SELL").sum())),
            avg_price=("price", "mean"),
            total_contracts=("quantity", "sum"),
        ).reset_index().sort_values("order_count", ascending=False)
        orders_by_symbol.to_csv(output_dir / "orders_by_symbol.csv", index=False)

    returns = equity.assign(date=pd.to_datetime(equity["date"])).set_index("date")["equity"].pct_change().fillna(0.0)
    drawdown = equity["equity"] / equity["equity"].cummax() - 1.0
    max_drawdown = float(drawdown.min())
    report = f"""# Real Options-Chain Backtest Report

Period: **{args.start} to {args.end}**  
Starting cash: **{money(args.initial_cash)}**  
Final equity: **{money(final)}**  
Total return: **{pct(total_return)}**  
Max drawdown: **{pct(max_drawdown)}**  
Orders: **{len(orders)}**

## Monthly Breakdown

{markdown_table(monthly_out.reset_index())}

## Orders By Symbol

{markdown_table(orders_by_symbol)}

## Risk Settings

- Monthly loss stop: {pct(args.monthly_loss_stop)}
- Monthly profit lock: {pct(args.monthly_profit_lock)}
- DTE range: {args.min_dte} to {args.max_dte}
- Max spread: {pct(args.max_spread_pct)}
- Max premium per contract idea: {pct(args.max_premium_fraction)}
- Max total premium at risk: {pct(args.max_total_premium_fraction)}
- Minimum contract ask: {money(args.min_contract_price)}
- Max contracts per trade: {args.max_contracts_per_trade if args.max_contracts_per_trade > 0 else "unlimited"}
- Min OTM at entry: {pct(args.min_otm_pct) if args.min_otm_pct is not None else "off"}
- Max OTM at entry: {pct(args.max_otm_pct) if args.max_otm_pct is not None else "off"}
- Minimum entry signal weight: {args.min_entry_weight}
- Option stop loss: {pct(args.stop_loss)}
- Option take profit: {pct(args.take_profit)}
- Profit-lock activation: {pct(args.profit_lock_activation) if args.profit_lock_activation > 0 else "off"}
- Profit-lock floor: {pct(args.profit_lock_floor) if args.profit_lock_floor > 0 else "off"}
- Profit-lock trail: {pct(args.profit_lock_trail) if args.profit_lock_trail > 0 else "off"}
- Max hold days: {args.max_hold_days}
- Exit losing position when signal drops out: {args.exit_losing_on_signal_loss}
- Signal-loss weight threshold: {args.signal_loss_weight_threshold}
- Stop-loss symbol cooldown days: {args.stop_loss_cooldown_days}
- Minimum equity for new entries: {money(args.min_equity_for_new_entries)}
- Low-equity risk-scale threshold: {money(args.low_equity_risk_scale_threshold)}
- Low-equity risk scale: {args.low_equity_risk_scale}
- Max equity drawdown for new entries: {pct(args.max_equity_drawdown_for_new_entries) if args.max_equity_drawdown_for_new_entries > 0 else "off"}
- Drawdown risk-scale threshold: {pct(args.drawdown_risk_scale_threshold) if args.drawdown_risk_scale_threshold > 0 else "off"}
- Drawdown risk scale: {args.drawdown_risk_scale}
- Close on monthly loss stop: {args.close_on_monthly_loss_stop}
- Close losers on monthly loss stop: {args.close_losers_on_monthly_loss_stop}
- Close on monthly profit lock: {args.close_on_monthly_profit_lock}
- Close before month end: {args.close_before_month_end}
- Excluded symbols: {", ".join(excluded_symbols) if excluded_symbols else "none"}

## Notes

This report uses historical option-chain bid/ask rows. Buys are filled at ask; sells are filled at bid. If the chain data is EOD-only, intraday stops cannot be modeled.
"""
    (output_dir / "REPORT.md").write_text(report)

    print(f"Final equity: ${final:,.2f}")
    print(f"Total return: {total_return * 100:,.2f}%")
    print(f"Orders: {len(orders)}")
    print(f"Monthly breakdown: {output_dir / 'monthly.csv'}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
