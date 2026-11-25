#!/usr/bin/env python3
"""Fetch Alpaca option snapshots and normalize them for the local ticket generator."""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.alpaca import (  # noqa: E402
    data_base_url,
    option_symbol_to_contract_id,
    parse_option_symbol,
    request_json,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Alpaca option-chain snapshots into local canonical CSV.")
    parser.add_argument("--symbols", default="", help="Comma-separated underlyings. If omitted, use active weights.")
    parser.add_argument("--weights", default="reports_live/latest_otm_weights.csv")
    parser.add_argument("--date", default="", help="Quote date label. Defaults to today UTC.")
    parser.add_argument("--output", default="data/live/current_options_chain.csv")
    parser.add_argument("--option-feed", default="indicative", choices=["indicative", "opra"])
    parser.add_argument("--stock-feed", default="iex")
    parser.add_argument("--min-dte", type=int, default=14)
    parser.add_argument("--max-dte", type=int, default=45)
    parser.add_argument("--strike-window-pct", type=float, default=0.18)
    parser.add_argument("--limit", type=int, default=1000)
    return parser.parse_args()


def active_symbols_from_weights(path):
    weights = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
    latest = weights.iloc[-1]
    active = latest[latest.abs() > 1e-9]
    return [str(symbol).upper() for symbol in active.abs().sort_values(ascending=False).index]


def latest_underlying_prices(symbols, stock_feed):
    if not symbols:
        return {}
    payload = request_json(
        "GET",
        f"{data_base_url()}/v2/stocks/quotes/latest",
        {"symbols": ",".join(symbols), "feed": stock_feed},
    )
    quotes = payload.get("quotes", {})
    prices = {}
    for symbol, quote in quotes.items():
        bid = float(quote.get("bp") or 0.0)
        ask = float(quote.get("ap") or 0.0)
        if bid > 0 and ask > 0:
            prices[str(symbol).upper()] = (bid + ask) / 2.0
        elif ask > 0:
            prices[str(symbol).upper()] = ask
        elif bid > 0:
            prices[str(symbol).upper()] = bid
    return prices


def snapshot_quote(snapshot):
    quote = snapshot.get("latestQuote") or snapshot.get("latest_quote") or snapshot.get("quote") or {}
    bid = quote.get("bp", quote.get("bid_price", quote.get("bidPrice")))
    ask = quote.get("ap", quote.get("ask_price", quote.get("askPrice")))
    timestamp = quote.get("t", quote.get("timestamp"))
    return bid, ask, timestamp


def snapshot_greeks(snapshot):
    greeks = snapshot.get("greeks") or {}
    return {
        "delta": greeks.get("delta"),
        "gamma": greeks.get("gamma"),
        "theta": greeks.get("theta"),
        "vega": greeks.get("vega"),
        "rho": greeks.get("rho"),
    }


def fetch_snapshots(symbol, price, args, quote_date):
    rows = []
    start = pd.Timestamp(quote_date).date() + timedelta(days=args.min_dte)
    end = pd.Timestamp(quote_date).date() + timedelta(days=args.max_dte)
    strike_low = price * (1.0 - args.strike_window_pct)
    strike_high = price * (1.0 + args.strike_window_pct)
    for option_type in ["call", "put"]:
        page_token = None
        while True:
            params = {
                "feed": args.option_feed,
                "type": option_type,
                "expiration_date_gte": start.isoformat(),
                "expiration_date_lte": end.isoformat(),
                "strike_price_gte": round(strike_low, 2),
                "strike_price_lte": round(strike_high, 2),
                "limit": args.limit,
            }
            if page_token:
                params["page_token"] = page_token
            payload = request_json(
                "GET",
                f"{data_base_url()}/v1beta1/options/snapshots/{symbol}",
                params,
            )
            snapshots = payload.get("snapshots") or {}
            for broker_symbol, snapshot in snapshots.items():
                try:
                    root, expiration, right, strike = parse_option_symbol(broker_symbol)
                except ValueError:
                    continue
                bid, ask, timestamp = snapshot_quote(snapshot)
                if bid is None or ask is None:
                    continue
                bid = float(bid)
                ask = float(ask)
                if bid <= 0 or ask <= 0:
                    continue
                greeks = snapshot_greeks(snapshot)
                rows.append(
                    {
                        "quote_date": quote_date,
                        "underlying_symbol": root,
                        "expiration": pd.Timestamp(expiration).date().isoformat(),
                        "strike": strike,
                        "option_type": right,
                        "bid": bid,
                        "ask": ask,
                        "last": None,
                        "volume": None,
                        "open_interest": None,
                        "implied_volatility": snapshot.get("impliedVolatility") or snapshot.get("implied_volatility"),
                        **greeks,
                        "underlying_price": price,
                        "broker_symbol": broker_symbol,
                        "contract_id": option_symbol_to_contract_id(broker_symbol),
                    }
                )
            page_token = payload.get("next_page_token")
            if not page_token:
                break
    return rows


def main():
    args = parse_args()
    quote_date = pd.Timestamp(args.date).date().isoformat() if args.date else pd.Timestamp.utcnow().date().isoformat()
    if args.symbols:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    else:
        symbols = active_symbols_from_weights(args.weights)
    if not symbols:
        raise SystemExit("No symbols supplied and no active weights found.")

    prices = latest_underlying_prices(symbols, args.stock_feed)
    missing = sorted(set(symbols) - set(prices))
    if missing:
        print(f"Skipping symbols without stock quote: {','.join(missing)}")
    rows = []
    for symbol in symbols:
        price = prices.get(symbol)
        if not price:
            continue
        rows.extend(fetch_snapshots(symbol, price, args, quote_date))
        print(f"{symbol}: fetched {len([row for row in rows if row['underlying_symbol'] == symbol])} option rows")

    if not rows:
        raise SystemExit("No option rows fetched. Check Alpaca data permissions/feed and active symbols.")
    frame = pd.DataFrame(rows).sort_values(["underlying_symbol", "expiration", "strike", "option_type"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    print(f"Wrote: {output}")
    print(f"Rows: {len(frame)}")
    print(f"Symbols: {','.join(sorted(frame['underlying_symbol'].unique()))}")


if __name__ == "__main__":
    main()
