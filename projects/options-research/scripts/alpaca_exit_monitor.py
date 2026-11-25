#!/usr/bin/env python3
"""Periodic supervised exit monitor for Alpaca paper option positions.

This script only manages existing positions. It can poll submitted exit orders,
apply filled exits to the local paper ledger, run the risk manager, and submit
fresh exit orders when risk rules fire. It never opens new trades.
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Run periodic Alpaca paper exit checks.")
    parser.add_argument("--positions", default="data/paper_trading/open_positions.csv")
    parser.add_argument("--account", default="data/paper_trading/account.csv")
    parser.add_argument(
        "--orders",
        action="append",
        default=[],
        help="Submitted-order CSV to monitor. Can be provided multiple times.",
    )
    parser.add_argument("--state-dir", default="data/paper_trading")
    parser.add_argument("--output-dir", default="artifacts/exit_monitor")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--cycles", type=int, default=1, help="Use 0 for continuous monitoring.")
    parser.add_argument("--starting-cash", type=float, default=3000.0)
    parser.add_argument("--submit-exits", action="store_true")
    parser.add_argument("--option-feed", default="indicative", choices=["indicative", "opra"])
    return parser.parse_args()


def run_command(parts):
    result = subprocess.run(parts, cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(parts)}")


def read_csv_if_present(path):
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(source)


def normalize_order_frame(frame):
    if frame.empty:
        return frame
    out = frame.copy()
    if "alpaca_symbol" not in out.columns and "broker_symbol" in out.columns:
        out["alpaca_symbol"] = out["broker_symbol"]
    if "action" not in out.columns:
        out["action"] = "SELL"
    if "date" not in out.columns:
        out["date"] = datetime.now().date().isoformat()
    for col in ["contract_id", "alpaca_symbol", "quantity", "limit_price", "alpaca_order_id", "status"]:
        if col not in out.columns:
            out[col] = ""
    return out


def combine_orders(order_paths, output):
    frames = [normalize_order_frame(read_csv_if_present(path)) for path in order_paths]
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
                "alpaca_order_id",
                "status",
            ]
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output, index=False)
    return output


def append_submitted(watch_file, submitted_file):
    current = read_csv_if_present(watch_file)
    submitted = normalize_order_frame(read_csv_if_present(submitted_file))
    if submitted.empty:
        return
    combined = pd.concat([normalize_order_frame(current), submitted], ignore_index=True)
    combined = combined[combined["alpaca_order_id"].astype(str).str.len() > 0]
    combined = combined.drop_duplicates(subset=["alpaca_order_id"], keep="last")
    combined.to_csv(watch_file, index=False)


def main():
    args = parse_args()
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    watch_file = output_dir / "watched_orders.csv"
    combine_orders(args.orders, watch_file)

    cycle = 0
    while args.cycles == 0 or cycle < args.cycles:
        cycle += 1
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cycle_dir = output_dir / f"cycle_{cycle:03d}_{stamp}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== Exit monitor cycle {cycle} at {stamp} ===")

        fills_file = cycle_dir / "fills.csv"
        if read_csv_if_present(watch_file).empty:
            print("No submitted orders to poll yet.")
        else:
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

        risk_cmd = [
            "python3",
            "scripts/alpaca_intraday_risk_manager.py",
            "--positions",
            args.positions,
            "--account",
            args.account,
            "--orders",
            str(watch_file),
            "--output-dir",
            str(cycle_dir),
            "--option-feed",
            args.option_feed,
            "--cancel-conflicting-open-exits",
        ]
        if args.submit_exits:
            risk_cmd.append("--submit-exits")
        run_command(risk_cmd)
        append_submitted(watch_file, cycle_dir / "submitted_exits.csv")

        if args.cycles != 0 and cycle >= args.cycles:
            break
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    main()
