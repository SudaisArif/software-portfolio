#!/usr/bin/env python3
"""Create a broker-neutral option order ticket for manual review.

This script intentionally does not connect to a broker or place orders. It takes
the latest model weights, a current options chain export, and optional open
positions, then applies the same risk controls used in the current OTM paper
observation profile.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.option_chain import (
    OptionBacktestConfig,
    OptionPosition,
    load_option_chains,
    quote_for_position,
    select_option_contract,
)
from algotrader.risk import ProfitLockConfig, option_exit_reason, update_profit_lock_state


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a dry-run live option ticket.")
    parser.add_argument("--chains", required=True, help="Current option-chain CSV/parquet in canonical format")
    parser.add_argument("--weights", default="reports_live/latest_otm_weights.csv")
    parser.add_argument("--date", default="", help="Trading date. Defaults to latest quote_date in --chains")
    parser.add_argument("--cash", type=float, required=True, help="Current cash available in the account")
    parser.add_argument("--positions", default="", help="Optional open positions CSV")
    parser.add_argument("--month-start-equity", type=float, default=0.0)
    parser.add_argument("--output-dir", default="artifacts/live_option_ticket")
    parser.add_argument("--exclude-symbols", default="META,XLV")
    parser.add_argument("--monthly-stopped", action="store_true")
    parser.add_argument("--allow-put-entries", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--close-on-monthly-loss-stop", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--monthly-loss-stop", type=float, default=0.04)
    parser.add_argument("--monthly-profit-lock", type=float, default=0.50)
    parser.add_argument("--min-dte", type=int, default=14)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--max-spread-pct", type=float, default=0.18)
    parser.add_argument("--max-premium-fraction", type=float, default=0.18)
    parser.add_argument("--max-total-premium-fraction", type=float, default=0.75)
    parser.add_argument("--min-contract-price", type=float, default=0.75)
    parser.add_argument("--max-contracts-per-trade", type=int, default=12)
    parser.add_argument("--min-otm-pct", type=float, default=0.03)
    parser.add_argument("--max-otm-pct", type=float, default=0.10)
    parser.add_argument("--min-entry-weight", type=float, default=0.75)
    parser.add_argument("--stop-loss", type=float, default=0.35)
    parser.add_argument("--take-profit", type=float, default=2.25)
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--expiration-exit-days", type=int, default=5)
    parser.add_argument("--profit-lock-state", default="data/paper_trading/profit_locks.csv")
    parser.add_argument("--profit-lock-activation", type=float, default=2.00)
    parser.add_argument("--profit-lock-floor", type=float, default=2.00)
    parser.add_argument("--profit-lock-trail", type=float, default=0.15)
    parser.add_argument("--disable-profit-lock", action="store_true")
    return parser.parse_args()


def load_weights(path, date, excluded_symbols, sort_by_abs=False):
    weights = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
    usable = weights.loc[weights.index <= date]
    if usable.empty:
        raise ValueError(f"No model weights available on or before {date.date()}")
    row = usable.iloc[-1].copy()
    for symbol in excluded_symbols:
        if symbol in row.index:
            row.loc[symbol] = 0.0
    if sort_by_abs:
        row = row.reindex(row.abs().sort_values(ascending=False).index)
    else:
        row = row.sort_values(ascending=False)
    return row, usable.index[-1]


def load_positions(path):
    if not path:
        return {}
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return {}
    frame = pd.read_csv(source, parse_dates=["expiration", "entry_date"])
    positions = {}
    for _, row in frame.iterrows():
        pos = OptionPosition(
            contract_id=str(row["contract_id"]),
            underlying_symbol=str(row["underlying_symbol"]).upper(),
            expiration=pd.Timestamp(row["expiration"]),
            strike=float(row["strike"]),
            option_type=str(row.get("option_type", "C")).upper()[0],
            quantity=int(row["quantity"]),
            entry_date=pd.Timestamp(row["entry_date"]),
            entry_price=float(row["entry_price"]),
            entry_cost=float(row["entry_cost"]),
        )
        positions[pos.contract_id] = pos
    return positions


def mark_positions(chain, positions, date, multiplier):
    value = 0.0
    marks = {}
    for pos in positions.values():
        quote = quote_for_position(chain, pos, date)
        if quote is None:
            marks[pos.contract_id] = None
            continue
        mark = float(quote["bid"])
        marks[pos.contract_id] = mark
        value += mark * multiplier * pos.quantity
    return value, marks


def load_profit_lock_state(path):
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return {}
    try:
        frame = pd.read_csv(source)
    except pd.errors.EmptyDataError:
        return {}
    state = {}
    for _, row in frame.iterrows():
        contract_id = str(row.get("contract_id", ""))
        if not contract_id or contract_id == "nan":
            continue
        state[contract_id] = {
            "armed": str(row.get("armed", "")).lower() in {"true", "1", "yes"},
            "max_pnl_pct": pd.to_numeric(row.get("max_pnl_pct"), errors="coerce"),
        }
    return state


def sell_ticket(date, pos, price, reason, multiplier):
    return {
        "date": date.date(),
        "action": "SELL",
        "symbol": pos.underlying_symbol,
        "contract_id": pos.contract_id,
        "broker_symbol": pos.contract_id,
        "quantity": pos.quantity,
        "limit_price": round(price, 4),
        "estimated_value": round(price * multiplier * pos.quantity, 2),
        "reason": reason,
    }


def main():
    args = parse_args()
    excluded_symbols = [item.strip().upper() for item in args.exclude_symbols.split(",") if item.strip()]
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
        max_hold_days=args.max_hold_days,
        close_on_monthly_loss_stop=args.close_on_monthly_loss_stop,
        close_losers_on_monthly_loss_stop=not args.close_on_monthly_loss_stop,
        allow_put_entries=args.allow_put_entries,
    )

    chain = load_option_chains(args.chains)
    date = pd.Timestamp(args.date) if args.date else pd.Timestamp(chain["quote_date"].max())
    positions = load_positions(args.positions)
    weights, weight_date = load_weights(args.weights, date, excluded_symbols, args.allow_put_entries)
    profit_state = load_profit_lock_state(args.profit_lock_state)
    profit_lock_config = ProfitLockConfig(
        activation=args.profit_lock_activation,
        floor=args.profit_lock_floor,
        trail=args.profit_lock_trail,
    )

    marked_value, marks = mark_positions(chain, positions, date, config.contract_multiplier)
    equity = float(args.cash) + marked_value
    month_start_equity = args.month_start_equity or equity
    month_return = equity / month_start_equity - 1.0 if month_start_equity > 0 else 0.0

    tickets = []
    blocked_reasons = []

    for pos in positions.values():
        quote = quote_for_position(chain, pos, date)
        if quote is None:
            blocked_reasons.append(f"Missing live quote for open position {pos.contract_id}")
            continue
        exit_price = float(quote["bid"])
        pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
        hold_days = (date - pos.entry_date).days
        dte = (pos.expiration - date).days
        current_profit_state = profit_state.get(pos.contract_id, {})
        profit_lock_armed = bool(current_profit_state.get("armed", False))
        max_pnl_pct = current_profit_state.get("max_pnl_pct")
        if not args.disable_profit_lock:
            profit_lock_armed, max_pnl_pct = update_profit_lock_state(
                pnl_pct,
                profit_lock_armed,
                max_pnl_pct,
                profit_lock_config,
            )
        reason = option_exit_reason(
            pnl_pct,
            hold_days,
            dte,
            config.stop_loss,
            config.take_profit,
            config.max_hold_days,
            args.expiration_exit_days,
            profit_lock_armed=profit_lock_armed,
            max_pnl_pct=max_pnl_pct,
            profit_lock_config=profit_lock_config,
        )
        if reason:
            tickets.append(sell_ticket(date, pos, exit_price, reason, config.contract_multiplier))

    risk_blocked = bool(args.monthly_stopped)
    if args.monthly_stopped:
        blocked_reasons.append("Monthly guard already marked stopped by operator")
    if config.monthly_loss_stop > 0 and month_return <= -config.monthly_loss_stop:
        risk_blocked = True
        blocked_reasons.append(f"Monthly loss stop triggered at {month_return:.2%}")
        for pos in positions.values():
            mark = marks.get(pos.contract_id)
            if mark is None:
                continue
            should_close = config.close_on_monthly_loss_stop or mark / pos.entry_price - 1.0 < 0
            if should_close:
                tickets.append(sell_ticket(date, pos, mark, "monthly_loss_stop_loser", config.contract_multiplier))
    if config.monthly_profit_lock > 0 and month_return >= config.monthly_profit_lock:
        risk_blocked = True
        blocked_reasons.append(f"Monthly profit lock reached at {month_return:.2%}")

    if not risk_blocked:
        gross_premium = sum(pos.entry_cost for pos in positions.values())
        open_symbols = {pos.underlying_symbol for pos in positions.values()}
        for symbol, weight in weights.items():
            symbol = str(symbol).upper()
            signal_strength = abs(float(weight)) if config.allow_put_entries else float(weight)
            if signal_strength <= 0 or signal_strength < config.min_entry_weight or symbol in open_symbols:
                continue
            option_type = "P" if config.allow_put_entries and float(weight) < 0 else "C"
            if gross_premium >= equity * config.max_total_premium_fraction:
                break
            pick = select_option_contract(chain, symbol, date, equity, config, option_type)
            if pick is None:
                continue
            contract_cost = float(pick["ask"]) * config.contract_multiplier
            max_by_cash = int(args.cash // contract_cost)
            remaining_total = equity * config.max_total_premium_fraction - gross_premium
            max_by_total = int(remaining_total // contract_cost)
            desired_premium = min(equity * signal_strength, equity * config.max_premium_fraction)
            qty = min(
                max_by_cash,
                max_by_total,
                config.max_contracts_per_trade if config.max_contracts_per_trade > 0 else max_by_cash,
                int(desired_premium // contract_cost),
            )
            if qty <= 0:
                continue
            tickets.append(
                {
                    "date": date.date(),
                    "action": "BUY",
                    "symbol": symbol,
                    "contract_id": str(pick["contract_id"]),
                    "broker_symbol": str(pick.get("broker_symbol", pick["contract_id"])),
                    "quantity": qty,
                    "limit_price": round(float(pick["ask"]), 4),
                    "estimated_value": round(contract_cost * qty, 2),
                    "reason": "entry",
                }
            )
            gross_premium += contract_cost * qty

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ticket_frame = pd.DataFrame(tickets)
    ticket_frame.to_csv(output_dir / "ticket.csv", index=False)
    status = pd.DataFrame(
        [
            {
                "date": date.date(),
                "weight_date": weight_date.date(),
                "cash": args.cash,
                "marked_option_value": round(marked_value, 2),
                "equity": round(equity, 2),
                "month_start_equity": round(month_start_equity, 2),
                "month_return": month_return,
                "excluded_symbols": ",".join(excluded_symbols),
                "blocked_reasons": "; ".join(blocked_reasons),
            }
        ]
    )
    status.to_csv(output_dir / "status.csv", index=False)

    print(f"Ticket rows: {len(ticket_frame)}")
    print(f"Equity: ${equity:,.2f}")
    print(f"Month return: {month_return * 100:,.2f}%")
    print(f"Ticket: {output_dir / 'ticket.csv'}")
    if blocked_reasons:
        print("Blocks: " + "; ".join(blocked_reasons))


if __name__ == "__main__":
    main()
