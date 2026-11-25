#!/usr/bin/env python3
"""Submit a generated option ticket to Alpaca paper trading.

Defaults to dry-run. Add --submit only after reviewing the generated payloads.
"""
import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.alpaca import (  # noqa: E402
    contract_id_to_option_symbol,
    request_json,
    trading_base_url,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Dry-run or submit option ticket orders to Alpaca paper.")
    parser.add_argument("--ticket", default="artifacts/live_ticket_today/ticket.csv")
    parser.add_argument("--output", default="artifacts/live_ticket_today/alpaca_orders.csv")
    parser.add_argument("--submit", action="store_true", help="Actually POST orders to Alpaca paper.")
    parser.add_argument("--allow-live", action="store_true", help="Permit non-paper Alpaca base URL.")
    parser.add_argument("--max-orders", type=int, default=0)
    return parser.parse_args()


def as_option_symbol(row):
    broker_symbol = str(row.get("broker_symbol", "")).strip()
    if broker_symbol and "_" not in broker_symbol:
        return broker_symbol.upper()
    return contract_id_to_option_symbol(str(row["contract_id"]))


def client_order_id(row, index):
    raw = f"{row.get('date','')}-{row['action']}-{row['contract_id']}-{row['quantity']}-{row['limit_price']}-{index}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"otm-paper-{digest}"


def build_payload(row, index):
    return {
        "symbol": as_option_symbol(row),
        "qty": str(int(row["quantity"])),
        "side": str(row["action"]).lower(),
        "type": "limit",
        "limit_price": str(round(float(row["limit_price"]), 2)),
        "time_in_force": "day",
        "client_order_id": client_order_id(row, index),
    }


def main():
    args = parse_args()
    base_url = trading_base_url()
    if "paper-api.alpaca.markets" not in base_url and not args.allow_live:
        raise SystemExit(f"Refusing to submit to non-paper Alpaca URL: {base_url}")

    ticket = pd.read_csv(args.ticket)
    if ticket.empty:
        print("Ticket is empty; nothing to submit.")
        return
    if args.max_orders > 0:
        ticket = ticket.head(args.max_orders)

    rows = []
    for idx, row in ticket.iterrows():
        payload = build_payload(row, idx)
        result = {
            "date": row.get("date", ""),
            "action": row["action"],
            "contract_id": row["contract_id"],
            "alpaca_symbol": payload["symbol"],
            "quantity": payload["qty"],
            "limit_price": payload["limit_price"],
            "client_order_id": payload["client_order_id"],
            "submitted": bool(args.submit),
            "alpaca_order_id": "",
            "status": "DRY_RUN",
            "error": "",
        }
        if args.submit:
            try:
                response = request_json("POST", f"{base_url}/v2/orders", body=payload)
                result["alpaca_order_id"] = response.get("id", "")
                result["status"] = response.get("status", "")
            except Exception as exc:
                result["status"] = "ERROR"
                result["error"] = str(exc)
        else:
            print(payload)
        rows.append(result)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output, index=False)
    print(f"Wrote: {output}")
    if args.submit:
        print("Submitted orders to Alpaca paper. Check your Alpaca dashboard before doing anything else.")
    else:
        print("Dry-run only. Re-run with --submit to place paper orders.")


if __name__ == "__main__":
    main()
