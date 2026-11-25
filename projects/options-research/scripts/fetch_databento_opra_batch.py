#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Databento OPRA chains for active weighted symbols.")
    parser.add_argument("--weights", default="reports/latest_weights.csv")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", default="data/options/databento")
    parser.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY", ""))
    parser.add_argument("--max-symbols-per-day", type=int, default=3)
    parser.add_argument("--max-cost-per-request", type=float, default=1.0)
    parser.add_argument("--max-total-cost", type=float, default=5.0)
    parser.add_argument("--schema", default="cbbo-1m")
    parser.add_argument("--minutes-before-close", type=int, default=15)
    parser.add_argument("--estimate-only", action="store_true", help="Estimate uncached requests and exit without fetching")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=float, default=5.0)
    return parser.parse_args()


def run_chain_script(args, symbol, date, output_dir, fetch):
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "fetch_databento_opra_chain.py"),
        "--symbol",
        symbol,
        "--date",
        date.date().isoformat(),
        "--output-dir",
        str(output_dir),
        "--schema",
        args.schema,
        "--minutes-before-close",
        str(args.minutes_before_close),
        "--max-cost",
        str(args.max_cost_per_request),
    ]
    if fetch:
        cmd.append("--fetch")
    env = os.environ.copy()
    env["DATABENTO_API_KEY"] = args.api_key
    return subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, env=env)


def run_chain_script_with_retries(args, symbol, date, output_dir, fetch):
    result = None
    for attempt in range(args.retries + 1):
        result = run_chain_script(args, symbol, date, output_dir, fetch)
        if result.returncode == 0:
            return result
        message = result.stderr.strip() or result.stdout.strip()
        retryable = any(text in message.lower() for text in ["504", "timed out", "timeout", "temporarily"])
        if not retryable or attempt >= args.retries:
            return result
        wait = args.retry_sleep_seconds * (attempt + 1)
        print(f"Retrying {symbol} {date.date()} after transient Databento error; attempt {attempt + 2}/{args.retries + 1} in {wait:.1f}s")
        time.sleep(wait)
    return result


def parse_estimated_cost(stdout):
    match = re.search(r"Estimated cost .*: \$([0-9]+(?:\.[0-9]+)?)", stdout)
    if not match:
        raise ValueError(f"Could not parse Databento estimate from output: {stdout.strip()}")
    return float(match.group(1))


def main():
    args = parse_args()
    if not args.api_key:
        raise SystemExit("Missing Databento key. Set DATABENTO_API_KEY or pass --api-key.")
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    weights = weights.loc[(weights.index >= pd.Timestamp(args.start)) & (weights.index <= pd.Timestamp(args.end))]
    if weights.empty:
        raise SystemExit("No weights found in the requested date range.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = []
    for date, row in weights.iterrows():
        symbols = row[row > 0].sort_values(ascending=False).head(args.max_symbols_per_day).index.tolist()
        for symbol in symbols:
            path = output_dir / f"{symbol}_{date.date().isoformat()}.csv"
            if path.exists() and path.stat().st_size > 0:
                continue
            plan.append((date, symbol))

    if not plan:
        print(f"All requested chain files already exist in {output_dir}")
        return

    estimates = []
    for date, symbol in plan:
        result = run_chain_script_with_retries(args, symbol, date, output_dir, fetch=False)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise SystemExit(f"Stopped after failed estimate for {symbol} {date.date()}: {message}")
        cost = parse_estimated_cost(result.stdout)
        estimates.append({"date": date.date().isoformat(), "symbol": symbol, "estimated_cost": cost})
        print(result.stdout.strip())

    total_cost = sum(item["estimated_cost"] for item in estimates)
    print(f"Estimated uncached total for {len(estimates)} chain files: ${total_cost:.4f}")
    if total_cost > args.max_total_cost:
        raise SystemExit(f"Refusing batch: estimated total ${total_cost:.4f} exceeds --max-total-cost ${args.max_total_cost:.2f}")
    if args.estimate_only:
        print("Estimate-only mode. No chains downloaded.")
        return

    fetched = 0
    for date, symbol in plan:
        result = run_chain_script_with_retries(args, symbol, date, output_dir, fetch=True)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise SystemExit(f"Stopped after failed fetch for {symbol} {date.date()}: {message}")
        fetched += 1
        print(result.stdout.strip())
    print(f"Fetched {fetched} chain files into {output_dir}")


if __name__ == "__main__":
    main()
