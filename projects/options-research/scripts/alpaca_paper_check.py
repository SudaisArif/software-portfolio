#!/usr/bin/env python3
"""Check Alpaca paper-account connectivity without placing orders."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.alpaca import request_json, trading_base_url  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Check Alpaca paper-account connectivity.")
    return parser.parse_args()


def main():
    parse_args()
    base_url = trading_base_url()
    if "paper-api.alpaca.markets" not in base_url:
        raise SystemExit(f"Refusing to check non-paper Alpaca URL by default: {base_url}")
    account = request_json("GET", f"{base_url}/v2/account")
    keys = [
        "id",
        "status",
        "currency",
        "cash",
        "buying_power",
        "portfolio_value",
        "trading_blocked",
        "account_blocked",
        "options_approved_level",
        "options_trading_level",
        "options_buying_power",
    ]
    print("Alpaca paper account connection OK")
    for key in keys:
        if key in account:
            print(f"{key}: {account[key]}")


if __name__ == "__main__":
    main()
