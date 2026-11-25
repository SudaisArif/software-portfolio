#!/usr/bin/env python3
import argparse
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Alpha Vantage historical option chain CSV.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output-dir", default="data/options/alpha_vantage")
    parser.add_argument("--apikey", default=os.environ.get("ALPHA_VANTAGE_API_KEY", ""))
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.apikey:
        raise SystemExit("Missing Alpha Vantage key. Set ALPHA_VANTAGE_API_KEY or pass --apikey.")
    params = {
        "function": "HISTORICAL_OPTIONS",
        "symbol": args.symbol.upper(),
        "date": args.date,
        "datatype": "csv",
        "apikey": args.apikey,
    }
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(params)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{args.symbol.upper()}_{args.date}.csv"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read()
    if b"premium" in payload.lower() or b"thank you" in payload.lower() or b"error" in payload.lower():
        preview = payload[:500].decode("utf-8", errors="replace")
        raise SystemExit(f"Alpha Vantage did not return option-chain CSV. Response starts with: {preview}")
    path.write_bytes(payload)
    print(path)


if __name__ == "__main__":
    main()

