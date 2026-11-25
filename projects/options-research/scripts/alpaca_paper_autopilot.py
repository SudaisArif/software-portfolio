#!/usr/bin/env python3
"""Continuous Alpaca paper-trading loop for the option strategy.

The loop is intentionally paper-only by default. Each cycle:

1. Polls watched Alpaca orders and applies fills to the local paper ledger.
2. Fetches a fresh option chain for active model symbols and open positions.
3. Runs the intraday exit manager.
4. Generates/submits new entry orders, skipping symbols with pending buys.

This is automation for observation, not a claim of live-trading readiness.
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OPEN_ORDER_STATUSES = {
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
    "pending_replace",
    "accepted_for_bidding",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Run the full Alpaca paper strategy loop until stopped.")
    parser.add_argument("--state-dir", default="data/paper_trading")
    parser.add_argument("--weights", default="reports_live/latest_otm_weights.csv")
    parser.add_argument("--output-dir", default="artifacts/alpaca_paper_autopilot")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--cycles", type=int, default=1, help="Use 0 to run until interrupted.")
    parser.add_argument("--seed-order", action="append", default=[], help="Existing submitted-order CSV to watch.")
    parser.add_argument("--submit", action="store_true", help="Actually submit paper orders.")
    parser.add_argument("--option-feed", default="indicative", choices=["indicative", "opra"])
    parser.add_argument("--stock-feed", default="iex")
    parser.add_argument("--exclude-symbols", default="META,XLV")
    parser.add_argument("--starting-cash", type=float, default=3000.0)
    parser.add_argument("--min-entry-weight", type=float, default=0.30)
    parser.add_argument("--stop-loss", type=float, default=0.70)
    parser.add_argument("--take-profit", type=float, default=2.25)
    parser.add_argument("--monthly-loss-stop", type=float, default=0.00)
    parser.add_argument("--monthly-profit-lock", type=float, default=0.50)
    parser.add_argument("--profit-lock-activation", type=float, default=2.00)
    parser.add_argument("--profit-lock-floor", type=float, default=2.00)
    parser.add_argument("--profit-lock-trail", type=float, default=0.15)
    parser.add_argument("--max-hold-days", type=int, default=5)
    parser.add_argument("--min-dte", type=int, default=14)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--strike-window-pct", type=float, default=0.18)
    return parser.parse_args()


def run_command(parts):
    result = subprocess.run(parts, cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(parts)}")


def read_csv(path):
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(source)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def normalize_order_frame(frame):
    if frame.empty:
        return frame
    out = frame.copy()
    if "alpaca_symbol" not in out.columns and "broker_symbol" in out.columns:
        out["alpaca_symbol"] = out["broker_symbol"]
    for col in [
        "date",
        "action",
        "contract_id",
        "alpaca_symbol",
        "quantity",
        "limit_price",
        "client_order_id",
        "submitted",
        "alpaca_order_id",
        "status",
        "error",
        "reason",
    ]:
        if col not in out.columns:
            out[col] = ""
    return out


def combine_seed_orders(seed_paths, watch_file):
    frames = [normalize_order_frame(read_csv(path)) for path in seed_paths]
    if watch_file.exists():
        frames.append(normalize_order_frame(read_csv(watch_file)))
    frames = [frame for frame in frames if not frame.empty]
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined = combined[combined["alpaca_order_id"].astype(str).str.len() > 0]
        combined = combined.drop_duplicates(subset=["alpaca_order_id"], keep="last")
    else:
        combined = pd.DataFrame(
            columns=[
                "date",
                "action",
                "contract_id",
                "alpaca_symbol",
                "quantity",
                "limit_price",
                "client_order_id",
                "submitted",
                "alpaca_order_id",
                "status",
                "error",
                "reason",
            ]
        )
    watch_file.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(watch_file, index=False)


def append_orders(watch_file, submitted_file):
    submitted = normalize_order_frame(read_csv(submitted_file))
    if submitted.empty:
        return
    current = normalize_order_frame(read_csv(watch_file))
    combined = pd.concat([current, submitted], ignore_index=True)
    combined = combined[combined["alpaca_order_id"].astype(str).str.len() > 0]
    combined = combined.drop_duplicates(subset=["alpaca_order_id"], keep="last")
    combined.to_csv(watch_file, index=False)


def active_symbols(weights_path, positions_path, excluded_symbols):
    symbols = set()
    weights = pd.read_csv(weights_path, parse_dates=["Date"]).set_index("Date").sort_index()
    latest = weights.iloc[-1]
    for symbol in latest[latest.abs() > 1e-9].abs().sort_values(ascending=False).index:
        symbol = str(symbol).upper()
        if symbol not in excluded_symbols:
            symbols.add(symbol)
    positions = read_csv(positions_path)
    if not positions.empty and "underlying_symbol" in positions.columns:
        symbols.update(positions["underlying_symbol"].dropna().astype(str).str.upper())
    return sorted(symbols)


def latest_account_cash(account_path, starting_cash):
    account = read_csv(account_path)
    if account.empty:
        return float(starting_cash)
    return float(account.iloc[-1].get("cash", starting_cash))


def pending_buy_symbols(order_status):
    if order_status.empty:
        return set()
    out = set()
    for _, row in order_status.iterrows():
        action = str(row.get("action", "")).upper()
        status = str(row.get("status", "")).lower()
        filled = float(row.get("filled_quantity", 0) or 0)
        qty = float(row.get("quantity", 0) or 0)
        if action == "BUY" and status in OPEN_ORDER_STATUSES and filled < qty:
            contract_id = str(row.get("contract_id", ""))
            if contract_id:
                out.add(contract_id.split("_", 1)[0].upper())
    return out


def filter_entry_ticket(ticket_file, order_status, output_file):
    ticket = read_csv(ticket_file)
    if ticket.empty:
        pd.DataFrame(
            columns=[
                "date",
                "action",
                "symbol",
                "contract_id",
                "option_symbol",
                "quantity",
                "limit_price",
                "reason",
            ]
        ).to_csv(output_file, index=False)
        return 0
    pending_symbols = pending_buy_symbols(order_status)
    entries = ticket[ticket["action"].astype(str).str.upper() == "BUY"].copy()
    if pending_symbols and not entries.empty:
        entries = entries[~entries["symbol"].astype(str).str.upper().isin(pending_symbols)]
    entries.to_csv(output_file, index=False)
    return len(entries)


def main():
    args = parse_args()
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir = ROOT / args.state_dir
    positions_path = state_dir / "open_positions.csv"
    account_path = state_dir / "account.csv"
    watch_file = output_dir / "watched_orders.csv"
    excluded_symbols = {item.strip().upper() for item in args.exclude_symbols.split(",") if item.strip()}
    combine_seed_orders(args.seed_order, watch_file)

    cycle = 0
    while args.cycles == 0 or cycle < args.cycles:
        cycle += 1
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cycle_dir = output_dir / f"cycle_{cycle:04d}_{stamp}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Paper autopilot cycle {cycle} at {stamp} ===")

        fills_file = cycle_dir / "fills.csv"
        if not read_csv(watch_file).empty:
            run_command(
                [
                    "python3",
                    "scripts/alpaca_sync_orders.py",
                    "--orders",
                    str(watch_file),
                    "--output",
                    str(fills_file),
                ]
            )
            run_command(
                [
                    "python3",
                    "scripts/apply_paper_fills.py",
                    "--fills",
                    str(fills_file),
                    "--state-dir",
                    args.state_dir,
                    "--starting-cash",
                    str(args.starting_cash),
                ]
            )
        else:
            pd.DataFrame().to_csv(fills_file, index=False)
            print("No watched orders yet.")

        symbols = active_symbols(args.weights, positions_path, excluded_symbols)
        if not symbols:
            print("No active symbols or positions to check.")
        else:
            chain_file = cycle_dir / "current_options_chain.csv"
            run_command(
                [
                    "python3",
                    "scripts/fetch_alpaca_option_chain.py",
                    "--symbols",
                    ",".join(symbols),
                    "--weights",
                    args.weights,
                    "--output",
                    str(chain_file),
                    "--option-feed",
                    args.option_feed,
                    "--stock-feed",
                    args.stock_feed,
                    "--min-dte",
                    str(args.min_dte),
                    "--max-dte",
                    str(args.max_dte),
                    "--strike-window-pct",
                    str(args.strike_window_pct),
                ]
            )

            risk_dir = cycle_dir / "risk"
            risk_cmd = [
                "python3",
                "scripts/alpaca_intraday_risk_manager.py",
                "--positions",
                str(positions_path),
                "--account",
                str(account_path),
                "--orders",
                str(watch_file),
                "--output-dir",
                str(risk_dir),
                "--option-feed",
                args.option_feed,
                "--stop-loss",
                str(args.stop_loss),
                "--take-profit",
                str(args.take_profit),
                "--monthly-loss-stop",
                str(args.monthly_loss_stop),
                "--profit-lock-activation",
                str(args.profit_lock_activation),
                "--profit-lock-floor",
                str(args.profit_lock_floor),
                "--profit-lock-trail",
                str(args.profit_lock_trail),
                "--max-hold-days",
                str(args.max_hold_days),
                "--cancel-conflicting-open-exits",
            ]
            if args.submit:
                risk_cmd.append("--submit-exits")
            run_command(risk_cmd)
            append_orders(watch_file, risk_dir / "submitted_exits.csv")

            cash = latest_account_cash(account_path, args.starting_cash)
            ticket_dir = cycle_dir / "entry_ticket"
            run_command(
                [
                    "python3",
                    "scripts/generate_live_option_ticket.py",
                    "--chains",
                    str(chain_file),
                    "--weights",
                    args.weights,
                    "--cash",
                    str(cash),
                    "--positions",
                    str(positions_path),
                    "--output-dir",
                    str(ticket_dir),
                    "--exclude-symbols",
                    args.exclude_symbols,
                    "--monthly-loss-stop",
                    str(args.monthly_loss_stop),
                    "--monthly-profit-lock",
                    str(args.monthly_profit_lock),
                    "--min-entry-weight",
                    str(args.min_entry_weight),
                    "--stop-loss",
                    str(args.stop_loss),
                    "--take-profit",
                    str(args.take_profit),
                    "--profit-lock-activation",
                    str(args.profit_lock_activation),
                    "--profit-lock-floor",
                    str(args.profit_lock_floor),
                    "--profit-lock-trail",
                    str(args.profit_lock_trail),
                    "--max-hold-days",
                    str(args.max_hold_days),
                ]
            )
            order_status = read_csv(fills_file)
            entry_only_ticket = cycle_dir / "entry_only_ticket.csv"
            entry_rows = filter_entry_ticket(ticket_dir / "ticket.csv", order_status, entry_only_ticket)
            print(f"Entry orders after pending-order filter: {entry_rows}")
            if entry_rows > 0:
                submitted_file = cycle_dir / "submitted_entries.csv"
                submit_cmd = [
                    "python3",
                    "scripts/alpaca_submit_ticket.py",
                    "--ticket",
                    str(entry_only_ticket),
                    "--output",
                    str(submitted_file),
                ]
                if args.submit:
                    submit_cmd.append("--submit")
                run_command(submit_cmd)
                append_orders(watch_file, submitted_file)

        if args.cycles != 0 and cycle >= args.cycles:
            break
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    main()
