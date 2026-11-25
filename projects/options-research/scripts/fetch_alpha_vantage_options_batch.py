#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Alpha Vantage historical option chains for active signal dates.")
    parser.add_argument("--weights", default="reports/latest_weights.csv")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", default="data/options/alpha_vantage")
    parser.add_argument("--apikey", default=os.environ.get("ALPHA_VANTAGE_API_KEY", ""))
    parser.add_argument("--sleep-seconds", type=float, default=12.5)
    parser.add_argument("--max-symbols-per-day", type=int, default=3)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.apikey:
        raise SystemExit("Missing Alpha Vantage key. Set ALPHA_VANTAGE_API_KEY or pass --apikey.")
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    weights = weights.loc[(weights.index >= pd.Timestamp(args.start)) & (weights.index <= pd.Timestamp(args.end))]
    if weights.empty:
        raise SystemExit("No weights found in the requested date range.")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    attempted = 0
    fetched = 0
    for date, row in weights.iterrows():
        symbols = row[row > 0].sort_values(ascending=False).head(args.max_symbols_per_day).index.tolist()
        for symbol in symbols:
            target = output_dir / f"{symbol}_{date.date().isoformat()}.csv"
            if target.exists() and target.stat().st_size > 0:
                continue
            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "fetch_alpha_vantage_options.py"),
                "--symbol",
                symbol,
                "--date",
                date.date().isoformat(),
                "--output-dir",
                str(output_dir),
                "--apikey",
                args.apikey,
            ]
            attempted += 1
            result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
            if result.returncode != 0:
                message = result.stderr.strip() or result.stdout.strip()
                raise SystemExit(f"Stopped after failed fetch for {symbol} {date.date()}: {message}")
            fetched += 1
            print(f"Fetched {symbol} {date.date()} -> {target}")
            time.sleep(args.sleep_seconds)
    print(f"Attempted: {attempted}; fetched: {fetched}; output: {output_dir}")


if __name__ == "__main__":
    main()

