#!/usr/bin/env python3
"""Intraday risk manager for supervised Alpaca paper option positions.

This does not create new entries. It marks existing local paper positions using
current Alpaca option quotes and creates/submits SELL tickets only when risk
rules fire.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.alpaca import (  # noqa: E402
    contract_id_to_option_symbol,
    data_base_url,
    parse_option_symbol,
    request_json,
    trading_base_url,
)
from algotrader.risk import ProfitLockConfig, option_exit_reason, update_profit_lock_state  # noqa: E402


OPEN_ORDER_STATUSES = {
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
    "pending_replace",
    "accepted_for_bidding",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Run an intraday risk check for Alpaca paper option positions.")
    parser.add_argument("--positions", default="data/paper_trading/open_positions.csv")
    parser.add_argument("--account", default="data/paper_trading/account.csv")
    parser.add_argument("--orders", default="", help="Optional submitted Alpaca order CSV to poll/cancel stale orders")
    parser.add_argument("--output-dir", default="artifacts/intraday_risk_check")
    parser.add_argument("--option-feed", default="indicative", choices=["indicative", "opra"])
    parser.add_argument("--stop-loss", type=float, default=0.35)
    parser.add_argument("--take-profit", type=float, default=2.25)
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--expiration-exit-days", type=int, default=5)
    parser.add_argument("--monthly-loss-stop", type=float, default=0.04)
    parser.add_argument("--month-start-equity", type=float, default=0.0)
    parser.add_argument("--profit-lock-state", default="data/paper_trading/profit_locks.csv")
    parser.add_argument("--profit-lock-activation", type=float, default=2.00)
    parser.add_argument("--profit-lock-floor", type=float, default=2.00)
    parser.add_argument("--profit-lock-trail", type=float, default=0.15)
    parser.add_argument("--disable-profit-lock", action="store_true")
    parser.add_argument("--cancel-stale-minutes", type=float, default=0.0)
    parser.add_argument("--submit-exits", action="store_true")
    parser.add_argument("--cancel-stale-orders", action="store_true")
    parser.add_argument(
        "--cancel-conflicting-open-exits",
        action="store_true",
        help="Cancel existing open sell orders for a contract before submitting a fresh exit.",
    )
    parser.add_argument("--allow-live", action="store_true")
    return parser.parse_args()


def ensure_paper(base_url, allow_live):
    if "paper-api.alpaca.markets" not in base_url and not allow_live:
        raise SystemExit(f"Refusing to use non-paper Alpaca URL: {base_url}")


def load_positions(path):
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(source, parse_dates=["expiration", "entry_date"])


def load_account(path):
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return {"cash": 0.0, "starting_cash": 0.0, "realized_pnl": 0.0}
    frame = pd.read_csv(source, parse_dates=["date"])
    if frame.empty:
        return {"cash": 0.0, "starting_cash": 0.0, "realized_pnl": 0.0}
    row = frame.iloc[-1]
    return {
        "cash": float(row.get("cash", 0.0)),
        "starting_cash": float(row.get("starting_cash", 0.0)),
        "realized_pnl": float(row.get("realized_pnl", 0.0)),
    }


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


def write_profit_lock_state(path, state, active_contract_ids):
    rows = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for contract_id in sorted(active_contract_ids):
        item = state.get(contract_id, {})
        max_pnl_pct = item.get("max_pnl_pct")
        rows.append(
            {
                "contract_id": contract_id,
                "armed": bool(item.get("armed", False)),
                "max_pnl_pct": max_pnl_pct if pd.notna(max_pnl_pct) else "",
                "updated_at": now,
            }
        )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output, index=False)


def snapshot_quote(snapshot):
    quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or snapshot.get("quote") or {}
    bid = quote.get("bp", quote.get("bid_price", quote.get("bidPrice")))
    ask = quote.get("ap", quote.get("ask_price", quote.get("askPrice")))
    return float(bid or 0.0), float(ask or 0.0)


def fetch_position_quote(contract_id, option_feed):
    broker_symbol = contract_id_to_option_symbol(contract_id)
    root, expiration, option_type, strike = parse_option_symbol(broker_symbol)
    params = {
        "feed": option_feed,
        "type": "call" if option_type == "C" else "put",
        "expiration_date_gte": expiration.date().isoformat(),
        "expiration_date_lte": expiration.date().isoformat(),
        "strike_price_gte": strike,
        "strike_price_lte": strike,
        "limit": 100,
    }
    payload = request_json("GET", f"{data_base_url()}/v1beta1/options/snapshots/{root}", params)
    snapshots = payload.get("snapshots") or {}
    snapshot = snapshots.get(broker_symbol)
    if snapshot is None:
        for symbol, candidate in snapshots.items():
            if str(symbol).upper() == broker_symbol:
                snapshot = candidate
                break
    if snapshot is None:
        return {"broker_symbol": broker_symbol, "bid": 0.0, "ask": 0.0}
    bid, ask = snapshot_quote(snapshot)
    return {"broker_symbol": broker_symbol, "bid": bid, "ask": ask}


def sell_ticket(today, pos, bid, reason, multiplier=100):
    return {
        "date": today.date().isoformat(),
        "action": "SELL",
        "symbol": str(pos["underlying_symbol"]).upper(),
        "contract_id": str(pos["contract_id"]),
        "broker_symbol": contract_id_to_option_symbol(str(pos["contract_id"])),
        "quantity": int(pos["quantity"]),
        "limit_price": round(float(bid), 2),
        "estimated_value": round(float(bid) * multiplier * int(pos["quantity"]), 2),
        "reason": reason,
    }


def client_order_id(contract_id, reason):
    cleaned = str(contract_id).replace("_", "-").replace(".", "-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"risk-{reason[:10]}-{cleaned[:20]}-{stamp}"[:48]


def submit_exit(ticket_row, base_url):
    payload = {
        "symbol": str(ticket_row["broker_symbol"]),
        "qty": str(int(ticket_row["quantity"])),
        "side": "sell",
        "type": "limit",
        "limit_price": str(round(float(ticket_row["limit_price"]), 2)),
        "time_in_force": "day",
        "client_order_id": client_order_id(ticket_row["contract_id"], ticket_row["reason"]),
    }
    return request_json("POST", f"{base_url}/v2/orders", body=payload)


def cancel_conflicting_open_exits(order_status, ticket_row, base_url):
    if order_status.empty:
        return []
    contract_id = str(ticket_row["contract_id"])
    broker_symbol = str(ticket_row["broker_symbol"]).upper()
    rows = []
    for _, existing in order_status.iterrows():
        status = str(existing.get("status", "")).lower()
        side = str(existing.get("side", "")).lower()
        if side != "sell" or status not in OPEN_ORDER_STATUSES:
            continue
        same_contract = str(existing.get("contract_id", "")) == contract_id
        same_symbol = str(existing.get("alpaca_symbol", "")).upper() == broker_symbol
        if not same_contract and not same_symbol:
            continue
        order_id = str(existing.get("alpaca_order_id", ""))
        if not order_id or order_id == "nan":
            continue
        request_json("DELETE", f"{base_url}/v2/orders/{order_id}")
        rows.append(
            {
                "alpaca_order_id": order_id,
                "contract_id": contract_id,
                "alpaca_symbol": broker_symbol,
                "reason": ticket_row["reason"],
                "status": "cancel_requested",
            }
        )
    return rows


def poll_orders(orders_path, base_url, cancel_stale_minutes=0.0, cancel=False):
    source = Path(orders_path)
    if not source.exists() or source.stat().st_size == 0:
        return pd.DataFrame()
    orders = pd.read_csv(source)
    rows = []
    now = datetime.now(timezone.utc)
    for _, row in orders.iterrows():
        order_id = str(row.get("alpaca_order_id", ""))
        if not order_id or order_id == "nan":
            continue
        detail = request_json("GET", f"{base_url}/v2/orders/{order_id}")
        status = str(detail.get("status", ""))
        submitted_at = detail.get("submitted_at", "")
        age_minutes = 0.0
        if submitted_at:
            submitted_ts = pd.Timestamp(submitted_at).to_pydatetime()
            if submitted_ts.tzinfo is None:
                submitted_ts = submitted_ts.replace(tzinfo=timezone.utc)
            age_minutes = max(0.0, (now - submitted_ts).total_seconds() / 60.0)
        cancelled = False
        if cancel and cancel_stale_minutes > 0 and status in OPEN_ORDER_STATUSES and age_minutes >= cancel_stale_minutes:
            request_json("DELETE", f"{base_url}/v2/orders/{order_id}")
            cancelled = True
            status = "cancel_requested"
        rows.append(
            {
                "alpaca_order_id": order_id,
                "contract_id": row.get("contract_id", ""),
                "alpaca_symbol": detail.get("symbol", row.get("alpaca_symbol", "")),
                "side": detail.get("side", ""),
                "quantity": detail.get("qty", ""),
                "filled_quantity": detail.get("filled_qty", ""),
                "status": status,
                "submitted_at": submitted_at,
                "age_minutes": round(age_minutes, 2),
                "cancel_requested": cancelled,
            }
        )
    return pd.DataFrame(rows)


def main():
    args = parse_args()
    base_url = trading_base_url()
    ensure_paper(base_url, args.allow_live)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    positions = load_positions(args.positions)
    account = load_account(args.account)
    profit_state = load_profit_lock_state(args.profit_lock_state)
    profit_lock_config = ProfitLockConfig(
        activation=args.profit_lock_activation,
        floor=args.profit_lock_floor,
        trail=args.profit_lock_trail,
    )
    today = pd.Timestamp.utcnow().tz_localize(None)

    order_status = pd.DataFrame()
    if args.orders:
        order_status = poll_orders(
            args.orders,
            base_url,
            cancel_stale_minutes=args.cancel_stale_minutes,
            cancel=args.cancel_stale_orders,
        )
        order_status.to_csv(output_dir / "order_status.csv", index=False)

    mark_rows = []
    tickets = []
    option_value = 0.0
    if not positions.empty:
        for _, pos in positions.iterrows():
            quote = fetch_position_quote(str(pos["contract_id"]), args.option_feed)
            bid = float(quote["bid"])
            ask = float(quote["ask"])
            qty = int(pos["quantity"])
            entry_price = float(pos["entry_price"])
            mark_value = bid * 100 * qty
            option_value += mark_value
            pnl_pct = bid / entry_price - 1.0 if entry_price > 0 and bid > 0 else None
            hold_days = (today.normalize() - pd.Timestamp(pos["entry_date"]).normalize()).days
            dte = (pd.Timestamp(pos["expiration"]).normalize() - today.normalize()).days
            reason = ""
            if bid <= 0:
                reason = "missing_quote"
            contract_id = str(pos["contract_id"])
            current_profit_state = profit_state.get(contract_id, {})
            profit_lock_armed = bool(current_profit_state.get("armed", False))
            max_pnl_pct = current_profit_state.get("max_pnl_pct")
            if not args.disable_profit_lock and pnl_pct is not None:
                profit_lock_armed, max_pnl_pct = update_profit_lock_state(
                    pnl_pct,
                    profit_lock_armed,
                    max_pnl_pct,
                    profit_lock_config,
                )
                profit_state[contract_id] = {
                    "armed": profit_lock_armed,
                    "max_pnl_pct": max_pnl_pct,
                }
            if not reason:
                reason = option_exit_reason(
                    pnl_pct,
                    hold_days,
                    dte,
                    args.stop_loss,
                    args.take_profit,
                    args.max_hold_days,
                    args.expiration_exit_days,
                    profit_lock_armed=profit_lock_armed,
                    max_pnl_pct=max_pnl_pct,
                    profit_lock_config=profit_lock_config,
                )
            mark_rows.append(
                {
                    "contract_id": pos["contract_id"],
                    "broker_symbol": quote["broker_symbol"],
                    "symbol": pos["underlying_symbol"],
                    "quantity": qty,
                    "entry_price": entry_price,
                    "bid": bid,
                    "ask": ask,
                    "mark_value": round(mark_value, 2),
                    "pnl_pct": pnl_pct,
                    "profit_lock_armed": profit_lock_armed,
                    "max_pnl_pct": max_pnl_pct,
                    "profit_lock_floor": args.profit_lock_floor,
                    "hold_days": hold_days,
                    "dte": dte,
                    "exit_reason": reason,
                }
            )
            if reason and reason != "missing_quote":
                tickets.append(sell_ticket(today, pos, bid, reason))

    cash = float(account["cash"])
    month_start_equity = args.month_start_equity or float(account["starting_cash"]) or cash + option_value
    equity = cash + option_value
    month_return = equity / month_start_equity - 1.0 if month_start_equity > 0 else 0.0
    if args.monthly_loss_stop > 0 and month_return <= -args.monthly_loss_stop and not positions.empty:
        existing = {row["contract_id"] for row in tickets}
        for _, pos in positions.iterrows():
            if str(pos["contract_id"]) in existing:
                continue
            quote_row = next((row for row in mark_rows if str(row["contract_id"]) == str(pos["contract_id"])), None)
            if quote_row and float(quote_row["bid"]) > 0:
                tickets.append(sell_ticket(today, pos, float(quote_row["bid"]), "monthly_loss_stop"))

    marks = pd.DataFrame(mark_rows)
    ticket_frame = pd.DataFrame(tickets)
    status = pd.DataFrame(
        [
            {
                "date": today.isoformat(),
                "cash": cash,
                "option_value": round(option_value, 2),
                "equity": round(equity, 2),
                "month_start_equity": round(month_start_equity, 2),
                "month_return": month_return,
                "open_positions": len(positions),
                "exit_tickets": len(ticket_frame),
            }
        ]
    )
    marks.to_csv(output_dir / "position_marks.csv", index=False)
    ticket_frame.to_csv(output_dir / "exit_ticket.csv", index=False)
    status.to_csv(output_dir / "status.csv", index=False)
    active_contract_ids = {str(row["contract_id"]) for _, row in positions.iterrows()} if not positions.empty else set()
    if not args.disable_profit_lock:
        write_profit_lock_state(args.profit_lock_state, profit_state, active_contract_ids)

    submitted_rows = []
    canceled_conflicts = []
    if args.submit_exits and not ticket_frame.empty:
        for _, row in ticket_frame.iterrows():
            if args.cancel_conflicting_open_exits:
                canceled_conflicts.extend(cancel_conflicting_open_exits(order_status, row, base_url))
            result = {
                "date": row["date"],
                "action": "SELL",
                "contract_id": row["contract_id"],
                "broker_symbol": row["broker_symbol"],
                "alpaca_symbol": row["broker_symbol"],
                "quantity": row["quantity"],
                "limit_price": row["limit_price"],
                "reason": row["reason"],
                "submitted": True,
                "alpaca_order_id": "",
                "status": "",
                "error": "",
            }
            try:
                response = submit_exit(row, base_url)
                result["alpaca_order_id"] = response.get("id", "")
                result["status"] = response.get("status", "")
            except Exception as exc:
                result["status"] = "ERROR"
                result["error"] = str(exc)
            submitted_rows.append(result)
    if canceled_conflicts:
        pd.DataFrame(canceled_conflicts).to_csv(output_dir / "canceled_conflicts.csv", index=False)
    if submitted_rows:
        pd.DataFrame(submitted_rows).to_csv(output_dir / "submitted_exits.csv", index=False)

    print(f"Equity: ${equity:,.2f}")
    print(f"Open positions: {len(positions)}")
    print(f"Exit tickets: {len(ticket_frame)}")
    print(f"Status: {output_dir / 'status.csv'}")
    print(f"Marks: {output_dir / 'position_marks.csv'}")
    print(f"Exit ticket: {output_dir / 'exit_ticket.csv'}")
    if not order_status.empty:
        print(f"Order status: {output_dir / 'order_status.csv'}")
    if submitted_rows:
        print(f"Submitted exits: {output_dir / 'submitted_exits.csv'}")
    if canceled_conflicts:
        print(f"Canceled conflicting exits: {output_dir / 'canceled_conflicts.csv'}")


if __name__ == "__main__":
    main()
