#!/usr/bin/env python3
"""Poll submitted Alpaca paper orders and write fill CSVs for the local ledger."""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.alpaca import request_json, trading_base_url  # noqa: E402


def symbol_from_contract_id(contract_id):
    return str(contract_id).split("_", 1)[0].upper()


def parse_args():
    parser = argparse.ArgumentParser(description="Sync Alpaca paper order statuses from a submitted-order CSV.")
    parser.add_argument("--orders", required=True)
    parser.add_argument("--ticket", default="")
    parser.add_argument("--output", default="data/paper_trading/latest_alpaca_fills.csv")
    parser.add_argument("--allow-live", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    base_url = trading_base_url()
    if "paper-api.alpaca.markets" not in base_url and not args.allow_live:
        raise SystemExit(f"Refusing to poll non-paper Alpaca URL: {base_url}")

    submitted = pd.read_csv(args.orders)
    ticket = pd.read_csv(args.ticket) if args.ticket else pd.DataFrame()
    ticket_by_contract = {}
    if not ticket.empty:
        ticket_by_contract = {str(row["contract_id"]): row for _, row in ticket.iterrows()}

    rows = []
    for _, order in submitted.iterrows():
        order_id = str(order["alpaca_order_id"])
        if not order_id or order_id == "nan":
            continue
        detail = request_json("GET", f"{base_url}/v2/orders/{order_id}")
        contract_id = str(order["contract_id"])
        ticket_row = ticket_by_contract.get(contract_id, {})
        filled_qty = int(float(detail.get("filled_qty") or 0))
        filled_avg_price = detail.get("filled_avg_price")
        symbol = str(
            ticket_row.get("symbol")
            or order.get("symbol")
            or symbol_from_contract_id(contract_id)
            or detail.get("symbol", "")
        ).upper()
        reason = str(ticket_row.get("reason") or order.get("reason", ""))
        rows.append(
            {
                "date": str(order.get("date", "")),
                "action": str(order["action"]).upper(),
                "symbol": symbol,
                "contract_id": contract_id,
                "broker_symbol": detail.get("symbol", order.get("alpaca_symbol", "")),
                "quantity": int(float(order["quantity"])),
                "filled_quantity": filled_qty,
                "limit_price": float(order["limit_price"]),
                "fill_price": float(filled_avg_price) if filled_avg_price else "",
                "reason": reason,
                "status": detail.get("status", ""),
                "alpaca_order_id": order_id,
                "submitted_at": detail.get("submitted_at", ""),
                "filled_at": detail.get("filled_at", ""),
            }
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output, index=False)
    print(f"Wrote: {output}")
    for row in rows:
        print(
            f"{row['action']} {row['broker_symbol']} qty={row['quantity']} "
            f"filled={row['filled_quantity']} status={row['status']} fill={row['fill_price']}"
        )


if __name__ == "__main__":
    main()
