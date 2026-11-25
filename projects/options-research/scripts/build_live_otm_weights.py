#!/usr/bin/env python3
"""Transform raw live weights into the OTM profile's tradable signal file."""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sweep_gap_push import Dataset, transformed_weights  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Build live OTM weights with trend/VIX transformations applied.")
    parser.add_argument("--weights", default="reports_live/latest_weights.csv")
    parser.add_argument("--output", default="reports_live/latest_otm_weights.csv")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--start", default="", help="Defaults to first date in --weights")
    parser.add_argument("--end", default="", help="Defaults to last date in --weights")
    return parser.parse_args()


def main():
    args = parse_args()
    raw = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date").sort_index()
    if raw.empty:
        raise SystemExit(f"No weights found in {args.weights}")
    start = args.start or raw.index.min().date().isoformat()
    end = args.end or raw.index.max().date().isoformat()
    dataset = Dataset("live", "", start, end)
    out = transformed_weights(raw, dataset, args.cache_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index_label="Date")

    latest = out.iloc[-1]
    active = latest[latest.abs() > 1e-9]
    active = active.reindex(active.abs().sort_values(ascending=False).index)
    print(f"Wrote: {output}")
    print(f"Latest date: {out.index[-1].date()}")
    if active.empty:
        print("Latest active weights: none")
    else:
        print("Latest active weights:")
        for symbol, weight in active.head(10).items():
            print(f"  {symbol}: {weight:.4f}")


if __name__ == "__main__":
    main()
