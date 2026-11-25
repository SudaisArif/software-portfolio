#!/usr/bin/env python3
"""Replay a planned option order schedule with intraday Databento quotes."""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.intraday_options import prepare_intraday_option_quotes  # noqa: E402
from algotrader.option_chain import OptionBacktestConfig, OptionPosition  # noqa: E402
from algotrader.risk import ProfitLockConfig, option_exit_reason, update_profit_lock_state  # noqa: E402


@dataclass
class ScheduledBuy:
    date: pd.Timestamp
    symbol: str
    contract_id: str
    quantity: int


def parse_args():
    parser = argparse.ArgumentParser(description="Replay scheduled option buys with intraday exits.")
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--orders", required=True, help="Daily backtest orders CSV; BUY rows become planned entries")
    parser.add_argument("--initial-cash", type=float, default=3000.0)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", default="artifacts/intraday_order_replay")
    parser.add_argument("--entry-time", default="09:45")
    parser.add_argument("--check-frequency-minutes", type=int, default=5)
    parser.add_argument("--max-quote-age-minutes", type=int, default=15)
    parser.add_argument("--stop-loss", type=float, default=0.35)
    parser.add_argument("--take-profit", type=float, default=2.25)
    parser.add_argument("--profit-lock-activation", type=float, default=2.00)
    parser.add_argument("--profit-lock-floor", type=float, default=2.00)
    parser.add_argument("--profit-lock-trail", type=float, default=0.15)
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--expiration-exit-days", type=int, default=5)
    parser.add_argument("--monthly-loss-stop", type=float, default=0.04)
    parser.add_argument("--close-on-monthly-loss-stop", action="store_true")
    return parser.parse_args()


def money(value):
    return f"${value:,.2f}"


def pct(value):
    return f"{value * 100:,.2f}%"


def markdown_table(frame):
    if frame.empty:
        return "_No rows._"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in columns) + " |")
    return "\n".join(lines)


def read_quotes(path):
    source = Path(path)
    if source.suffix.lower() == ".parquet":
        frame = pd.read_parquet(source)
    else:
        frame = pd.read_csv(source)
    return prepare_intraday_option_quotes(frame)


def load_schedule(path, start, end):
    orders = pd.read_csv(path, parse_dates=["date"])
    buys = orders[orders["action"] == "BUY"].copy()
    buys["date"] = pd.to_datetime(buys["date"]).dt.normalize()
    buys = buys[(buys["date"] >= start) & (buys["date"] <= end)]
    schedule = []
    for _, row in buys.iterrows():
        schedule.append(
            ScheduledBuy(
                date=pd.Timestamp(row["date"]),
                symbol=str(row["symbol"]).upper(),
                contract_id=str(row["contract_id"]),
                quantity=int(row["quantity"]),
            )
        )
    return schedule


def quote_book(quotes):
    return {
        str(contract_id): frame.sort_values("timestamp").set_index("timestamp", drop=False)
        for contract_id, frame in quotes.groupby("contract_id", sort=False)
    }


def latest_quote(book, contract_id, timestamp, max_age):
    frame = book.get(str(contract_id))
    if frame is None or frame.empty:
        return None
    loc = frame.index.searchsorted(pd.Timestamp(timestamp), side="right") - 1
    if loc < 0:
        return None
    quote = frame.iloc[loc]
    age = (pd.Timestamp(timestamp) - pd.Timestamp(quote["timestamp"])).total_seconds() / 60.0
    if max_age > 0 and age > max_age:
        return None
    return quote


def scheduled_timestamps(quotes, frequency):
    out = []
    last_by_date = {}
    for raw in quotes["timestamp"].drop_duplicates().sort_values():
        ts = pd.Timestamp(raw)
        date = ts.normalize()
        previous = last_by_date.get(date)
        if previous is None or (ts - previous).total_seconds() >= frequency * 60:
            out.append(ts)
            last_by_date[date] = ts
    return out


def mark_positions(book, positions, timestamp, config, max_age):
    value = 0.0
    for pos in positions.values():
        quote = latest_quote(book, pos.contract_id, timestamp, max_age)
        if quote is not None:
            value += float(quote["bid"]) * config.contract_multiplier * pos.quantity
    return value


def main():
    args = parse_args()
    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    quotes = read_quotes(args.quotes)
    quotes = quotes[(quotes["quote_date"] >= start) & (quotes["quote_date"] <= end)]
    if quotes.empty:
        raise SystemExit("No intraday quotes in requested window.")
    schedule = load_schedule(args.orders, start, end)
    schedule_by_date = {}
    for buy in schedule:
        schedule_by_date.setdefault(buy.date, []).append(buy)
    book = quote_book(quotes)
    timestamps = scheduled_timestamps(quotes, args.check_frequency_minutes)
    entry_time = pd.Timestamp(f"2000-01-01 {args.entry_time}").time()
    config = OptionBacktestConfig(
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        profit_lock_activation=args.profit_lock_activation,
        profit_lock_floor=args.profit_lock_floor,
        profit_lock_trail=args.profit_lock_trail,
        max_hold_days=args.max_hold_days,
    )

    cash = float(args.initial_cash)
    positions = {}
    profit_state = {}
    entered = set()
    equity_rows = []
    order_rows = []
    events = []
    current_month = start.to_period("M")
    month_start_equity = cash
    monthly_stopped = False

    for timestamp in timestamps:
        date = timestamp.normalize()
        if date.to_period("M") != current_month:
            current_month = date.to_period("M")
            month_start_equity = cash + mark_positions(book, positions, timestamp, config, args.max_quote_age_minutes)
            monthly_stopped = False

        for key, pos in list(positions.items()):
            quote = latest_quote(book, pos.contract_id, timestamp, args.max_quote_age_minutes)
            if quote is None:
                continue
            exit_price = float(quote["bid"])
            pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price else 0.0
            hold_days = (date - pd.Timestamp(pos.entry_date).normalize()).days
            dte = (pos.expiration - date).days
            pl_config = ProfitLockConfig(args.profit_lock_activation, args.profit_lock_floor, args.profit_lock_trail)
            state = profit_state.get(pos.contract_id, {})
            armed = bool(state.get("armed", False))
            max_pnl = state.get("max_pnl_pct")
            if args.profit_lock_activation > 0 and args.profit_lock_floor > 0:
                armed, max_pnl = update_profit_lock_state(pnl_pct, armed, max_pnl, pl_config)
                profit_state[pos.contract_id] = {"armed": armed, "max_pnl_pct": max_pnl}
            reason = option_exit_reason(
                pnl_pct,
                hold_days,
                dte,
                args.stop_loss,
                args.take_profit,
                args.max_hold_days,
                args.expiration_exit_days,
                profit_lock_armed=armed,
                max_pnl_pct=max_pnl,
                profit_lock_config=pl_config,
            )
            if reason:
                cash += exit_price * config.contract_multiplier * pos.quantity
                order_rows.append(
                    {
                        "timestamp": timestamp,
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
                profit_state.pop(pos.contract_id, None)

        option_value = mark_positions(book, positions, timestamp, config, args.max_quote_age_minutes)
        equity = cash + option_value
        month_return = equity / month_start_equity - 1.0 if month_start_equity else 0.0
        if not monthly_stopped and args.monthly_loss_stop > 0 and month_return <= -args.monthly_loss_stop:
            monthly_stopped = True
            events.append({"timestamp": timestamp, "date": date, "event": "monthly_loss_stop", "month_return": month_return})
            if args.close_on_monthly_loss_stop:
                for key, pos in list(positions.items()):
                    quote = latest_quote(book, pos.contract_id, timestamp, args.max_quote_age_minutes)
                    if quote is None:
                        continue
                    exit_price = float(quote["bid"])
                    pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price else 0.0
                    cash += exit_price * config.contract_multiplier * pos.quantity
                    order_rows.append(
                        {
                            "timestamp": timestamp,
                            "date": date,
                            "symbol": pos.underlying_symbol,
                            "contract_id": pos.contract_id,
                            "action": "SELL",
                            "quantity": pos.quantity,
                            "price": exit_price,
                            "cash_after": cash,
                            "pnl_pct": pnl_pct,
                            "reason": "monthly_loss_stop",
                        }
                    )
                    del positions[key]
                option_value = mark_positions(book, positions, timestamp, config, args.max_quote_age_minutes)
                equity = cash + option_value

        if not monthly_stopped and timestamp.time() >= entry_time:
            for buy in schedule_by_date.get(date, []):
                if buy.contract_id in entered or buy.symbol in {pos.underlying_symbol for pos in positions.values()}:
                    continue
                quote = latest_quote(book, buy.contract_id, timestamp, args.max_quote_age_minutes)
                if quote is None:
                    continue
                ask = float(quote["ask"])
                cost = ask * config.contract_multiplier * buy.quantity
                if cost > cash:
                    continue
                cash -= cost
                pos = OptionPosition(
                    contract_id=buy.contract_id,
                    underlying_symbol=buy.symbol,
                    expiration=pd.Timestamp(quote["expiration"]),
                    strike=float(quote["strike"]),
                    option_type=str(quote["option_type"]),
                    quantity=buy.quantity,
                    entry_date=timestamp,
                    entry_price=ask,
                    entry_cost=cost,
                )
                positions[pos.contract_id] = pos
                entered.add(pos.contract_id)
                order_rows.append(
                    {
                        "timestamp": timestamp,
                        "date": date,
                        "symbol": pos.underlying_symbol,
                        "contract_id": pos.contract_id,
                        "action": "BUY",
                        "quantity": pos.quantity,
                        "price": ask,
                        "cash_after": cash,
                        "pnl_pct": 0.0,
                        "reason": "scheduled_entry",
                    }
                )

        option_value = mark_positions(book, positions, timestamp, config, args.max_quote_age_minutes)
        equity = cash + option_value
        equity_rows.append(
            {
                "timestamp": timestamp,
                "date": date,
                "cash": cash,
                "option_value": option_value,
                "equity": equity,
                "open_positions": len(positions),
            }
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    equity = pd.DataFrame(equity_rows)
    orders = pd.DataFrame(order_rows)
    events = pd.DataFrame(events)
    equity.to_csv(output_dir / "equity.csv", index=False)
    orders.to_csv(output_dir / "orders.csv", index=False)
    events.to_csv(output_dir / "events.csv", index=False)
    final = float(equity["equity"].iloc[-1])
    total_return = final / args.initial_cash - 1.0
    monthly = equity.assign(timestamp=pd.to_datetime(equity["timestamp"])).set_index("timestamp")["equity"].resample("ME").last()
    monthly = pd.concat([pd.Series([args.initial_cash], index=[start]), monthly]).dropna()
    monthly_out = pd.DataFrame({"equity": monthly, "monthly_profit": monthly.diff(), "monthly_return": monthly.pct_change()}).dropna()
    monthly_out.to_csv(output_dir / "monthly.csv", index_label="timestamp")
    by_reason = pd.DataFrame()
    if not orders.empty:
        by_reason = orders.groupby(["action", "reason"]).agg(order_count=("reason", "size")).reset_index()
        by_reason.to_csv(output_dir / "orders_by_reason.csv", index=False)
    report = f"""# Intraday Scheduled-Order Replay

Period: **{args.start} to {args.end}**  
Starting cash: **{money(args.initial_cash)}**  
Final equity: **{money(final)}**  
Total return: **{pct(total_return)}**  
Orders: **{len(orders)}**

## Orders By Reason

{markdown_table(by_reason)}

## Notes

This replay uses the daily backtest's planned BUY contracts, then applies intraday exits using Databento minute bid/ask quotes. Buys fill at ask; sells and marks use bid.
"""
    (output_dir / "REPORT.md").write_text(report)
    print(f"Final equity: ${final:,.2f}")
    print(f"Total return: {total_return * 100:,.2f}%")
    print(f"Orders: {len(orders)}")
    print(f"Report: {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
