#!/usr/bin/env python3
"""Apply simulated broker fills to the local paper-trading ledger.

Use this after placing the generated ticket in a paper broker account. Export or
enter the filled orders into a CSV, then this script updates cash, open
positions, and a journal that can be used by tomorrow's ticket generation.
"""
import argparse
import re
from pathlib import Path

import pandas as pd


POSITION_COLUMNS = [
    "contract_id",
    "underlying_symbol",
    "expiration",
    "strike",
    "option_type",
    "quantity",
    "entry_date",
    "entry_price",
    "entry_cost",
]

ACCOUNT_COLUMNS = ["date", "cash", "realized_pnl", "starting_cash"]


def parse_args():
    parser = argparse.ArgumentParser(description="Update local paper account state from option fills.")
    parser.add_argument("--fills", required=True, help="CSV with filled paper orders")
    parser.add_argument("--state-dir", default="data/paper_trading")
    parser.add_argument("--starting-cash", type=float, default=1000.0)
    parser.add_argument("--multiplier", type=int, default=100)
    return parser.parse_args()


def parse_contract_id(contract_id):
    match = re.match(r"^(.+)_([0-9]{8})_([CP])_([0-9.]+)$", str(contract_id))
    if not match:
        raise ValueError(f"Cannot parse contract_id: {contract_id}")
    symbol, expiry, option_type, strike = match.groups()
    return symbol.upper(), pd.Timestamp(expiry), option_type.upper(), float(strike)


def load_account(path, starting_cash):
    if path.exists() and path.stat().st_size > 0:
        frame = pd.read_csv(path, parse_dates=["date"])
        if not frame.empty:
            row = frame.iloc[-1]
            return float(row["cash"]), float(row.get("realized_pnl", 0.0)), float(row.get("starting_cash", starting_cash))
    return float(starting_cash), 0.0, float(starting_cash)


def load_positions(path):
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path, parse_dates=["expiration", "entry_date"])
    return pd.DataFrame(columns=POSITION_COLUMNS)


def load_journal(path):
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path, parse_dates=["date"])
    return pd.DataFrame()


def normalize_fills(path):
    fills = pd.read_csv(path, parse_dates=["date"])
    if fills.empty:
        return fills
    fills.columns = [str(col).strip().lower() for col in fills.columns]
    if "filled_quantity" not in fills.columns:
        fills["filled_quantity"] = fills["quantity"]
    if "fill_price" not in fills.columns:
        fills["fill_price"] = fills.get("limit_price", fills.get("price"))
    if "status" in fills.columns:
        fills = fills[fills["status"].astype(str).str.upper().isin(["FILLED", "PARTIAL", "PARTIALLY_FILLED"])]
    required = ["date", "action", "symbol", "contract_id", "filled_quantity", "fill_price"]
    missing = [col for col in required if col not in fills.columns]
    if missing:
        raise ValueError(f"Missing required fill columns: {missing}")
    fills["action"] = fills["action"].astype(str).str.upper()
    fills["symbol"] = fills["symbol"].astype(str).str.upper()
    fills["filled_quantity"] = pd.to_numeric(fills["filled_quantity"], errors="coerce").fillna(0).astype(int)
    fills["fill_price"] = pd.to_numeric(fills["fill_price"], errors="coerce")
    fills = fills[(fills["filled_quantity"] > 0) & fills["fill_price"].notna()]
    return fills


def prune_profit_locks(state_dir, positions):
    profit_locks_path = state_dir / "profit_locks.csv"
    if not profit_locks_path.exists() or profit_locks_path.stat().st_size == 0:
        return
    try:
        locks = pd.read_csv(profit_locks_path)
    except pd.errors.EmptyDataError:
        return
    if locks.empty or "contract_id" not in locks.columns:
        return
    active_contracts = set(positions["contract_id"].astype(str)) if not positions.empty else set()
    locks = locks[locks["contract_id"].astype(str).isin(active_contracts)]
    locks.to_csv(profit_locks_path, index=False)


def append_position(positions, row, quantity, price, multiplier):
    symbol, expiration, option_type, strike = parse_contract_id(row["contract_id"])
    cost = float(price) * multiplier * int(quantity)
    new_row = {
        "contract_id": str(row["contract_id"]),
        "underlying_symbol": symbol,
        "expiration": expiration,
        "strike": strike,
        "option_type": option_type,
        "quantity": int(quantity),
        "entry_date": pd.Timestamp(row["date"]),
        "entry_price": float(price),
        "entry_cost": cost,
    }
    return pd.concat([positions, pd.DataFrame([new_row])], ignore_index=True)


def close_position(positions, row, quantity, price, multiplier):
    contract_id = str(row["contract_id"])
    remaining_to_close = int(quantity)
    realized = 0.0
    closed_rows = []
    keep_rows = []
    for _, pos in positions.iterrows():
        if str(pos["contract_id"]) != contract_id or remaining_to_close <= 0:
            keep_rows.append(pos.to_dict())
            continue
        open_qty = int(pos["quantity"])
        close_qty = min(open_qty, remaining_to_close)
        entry_price = float(pos["entry_price"])
        pnl = (float(price) - entry_price) * multiplier * close_qty
        realized += pnl
        closed_rows.append(
            {
                "closed_quantity": close_qty,
                "entry_price": entry_price,
                "exit_price": float(price),
                "trade_pnl": pnl,
                "trade_pnl_pct": float(price) / entry_price - 1.0 if entry_price > 0 else 0.0,
            }
        )
        remaining_to_close -= close_qty
        leftover = open_qty - close_qty
        if leftover > 0:
            updated = pos.to_dict()
            updated["quantity"] = leftover
            updated["entry_cost"] = entry_price * multiplier * leftover
            keep_rows.append(updated)
    if remaining_to_close > 0:
        raise ValueError(f"Tried to close {quantity} {contract_id}, but only found {quantity - remaining_to_close}")
    return pd.DataFrame(keep_rows, columns=POSITION_COLUMNS), realized, closed_rows


def main():
    args = parse_args()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    account_path = state_dir / "account.csv"
    positions_path = state_dir / "open_positions.csv"
    journal_path = state_dir / "journal.csv"

    cash, realized_pnl, starting_cash = load_account(account_path, args.starting_cash)
    positions = load_positions(positions_path)
    journal = load_journal(journal_path)
    fills = normalize_fills(args.fills)
    applied_order_ids = set()
    if "alpaca_order_id" in journal.columns:
        applied_order_ids = set(journal["alpaca_order_id"].dropna().astype(str))

    journal_rows = []
    for _, fill in fills.iterrows():
        alpaca_order_id = str(fill.get("alpaca_order_id", "") or "")
        if alpaca_order_id and alpaca_order_id in applied_order_ids:
            continue
        action = str(fill["action"]).upper()
        qty = int(fill["filled_quantity"])
        price = float(fill["fill_price"])
        value = price * args.multiplier * qty
        reason = str(fill.get("reason", ""))
        if action == "BUY":
            cash -= value
            positions = append_position(positions, fill, qty, price, args.multiplier)
            journal_rows.append(
                {
                    "date": fill["date"],
                    "action": action,
                    "symbol": fill["symbol"],
                    "contract_id": fill["contract_id"],
                    "quantity": qty,
                    "fill_price": price,
                    "cash_after": cash,
                    "realized_pnl": 0.0,
                    "reason": reason,
                    "alpaca_order_id": alpaca_order_id,
                }
            )
        elif action == "SELL":
            cash += value
            positions, trade_realized, closed_rows = close_position(positions, fill, qty, price, args.multiplier)
            realized_pnl += trade_realized
            if not closed_rows:
                closed_rows = [{"trade_pnl": 0.0, "trade_pnl_pct": 0.0}]
            for closed in closed_rows:
                journal_rows.append(
                    {
                        "date": fill["date"],
                        "action": action,
                        "symbol": fill["symbol"],
                        "contract_id": fill["contract_id"],
                        "quantity": closed.get("closed_quantity", qty),
                        "fill_price": price,
                        "cash_after": cash,
                        "realized_pnl": closed["trade_pnl"],
                        "pnl_pct": closed["trade_pnl_pct"],
                        "reason": reason,
                        "alpaca_order_id": alpaca_order_id,
                    }
                )
        else:
            raise ValueError(f"Unsupported action: {action}")

    if journal_rows:
        journal = pd.concat([journal, pd.DataFrame(journal_rows)], ignore_index=True)

    last_date = fills["date"].max() if not fills.empty else pd.Timestamp.today().normalize()
    account = pd.DataFrame(
        [
            {
                "date": last_date,
                "cash": cash,
                "realized_pnl": realized_pnl,
                "starting_cash": starting_cash,
            }
        ],
        columns=ACCOUNT_COLUMNS,
    )
    positions = positions.reindex(columns=POSITION_COLUMNS)
    positions.to_csv(positions_path, index=False)
    account.to_csv(account_path, index=False)
    journal.to_csv(journal_path, index=False)
    prune_profit_locks(state_dir, positions)

    print(f"Applied fills: {len(fills)}")
    print(f"Cash: ${cash:,.2f}")
    print(f"Open positions: {len(positions)}")
    print(f"Realized P/L: ${realized_pnl:,.2f}")
    print(f"Positions: {positions_path}")
    print(f"Journal: {journal_path}")


if __name__ == "__main__":
    main()
