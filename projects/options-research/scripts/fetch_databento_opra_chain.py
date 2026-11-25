#!/usr/bin/env python3
import argparse
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.data import download_prices


DATASET = "OPRA.PILLAR"
EARLY_CLOSE_DATES = {
    "2025-07-03",
    "2025-11-28",
    "2025-12-24",
    "2026-07-02",
    "2026-11-27",
    "2026-12-24",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Estimate/fetch a Databento OPRA close-of-day option chain.")
    parser.add_argument("--symbol", required=True, help="Underlying symbol, e.g. AAPL")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--schema", default="cbbo-1m", choices=["cbbo-1m", "bbo-1m", "tbbo", "trades"])
    parser.add_argument("--minutes-before-close", type=int, default=15)
    parser.add_argument("--output-dir", default="data/options/databento")
    parser.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY", ""))
    parser.add_argument("--fetch", action="store_true", help="Actually download after estimating cost")
    parser.add_argument("--max-cost", type=float, default=1.0)
    parser.add_argument("--start-equity-cache", default="2016-01-01")
    return parser.parse_args()


def close_window(trade_date: str, minutes_before_close: int):
    eastern = ZoneInfo("US/Eastern")
    day = pd.Timestamp(trade_date).date()
    close_time = time(13, 0) if day.isoformat() in EARLY_CLOSE_DATES else time(16, 0)
    end = datetime.combine(day, close_time, tzinfo=eastern)
    start = end - timedelta(minutes=minutes_before_close)
    return start, end


def get_underlying_price(symbol: str, trade_date: str, start: str) -> float:
    prices = download_prices([symbol], start, trade_date, "data/cache", refresh=False)
    frame = prices[symbol]
    date = pd.Timestamp(trade_date)
    close = frame.loc[frame.index <= date, "Close"]
    if close.empty:
        return float("nan")
    return float(close.iloc[-1])


def instrument_class_to_type(value) -> str:
    text = str(value).upper()
    if text.startswith("C") or "CALL" in text:
        return "C"
    if text.startswith("P") or "PUT" in text:
        return "P"
    return text[:1]


def main():
    args = parse_args()
    if not args.api_key:
        raise SystemExit("Missing Databento key. Set DATABENTO_API_KEY or pass --api-key.")
    import databento as db

    symbol = args.symbol.upper()
    parent = f"{symbol}.OPT"
    start, end = close_window(args.date, args.minutes_before_close)
    client = db.Historical(args.api_key)

    quote_cost = client.metadata.get_cost(
        dataset=DATASET,
        schema=args.schema,
        stype_in="parent",
        symbols=[parent],
        start=start,
        end=end,
    )
    definition_cost = client.metadata.get_cost(
        dataset=DATASET,
        schema="definition",
        stype_in="parent",
        symbols=[parent],
        start=args.date,
    )
    total_cost = float(quote_cost + definition_cost)
    print(f"Estimated cost for {symbol} {args.date} {args.schema}: ${total_cost:.4f}")
    if not args.fetch:
        print("Dry run only. Add --fetch to download.")
        return
    if total_cost > args.max_cost:
        raise SystemExit(f"Refusing download: estimated cost ${total_cost:.4f} exceeds --max-cost ${args.max_cost:.2f}")

    data = client.timeseries.get_range(
        dataset=DATASET,
        schema=args.schema,
        stype_in="parent",
        symbols=[parent],
        start=start,
        end=end,
    ).to_df()
    definitions = client.timeseries.get_range(
        dataset=DATASET,
        schema="definition",
        stype_in="parent",
        symbols=[parent],
        start=args.date,
    ).to_df()
    if data.empty or definitions.empty:
        raise SystemExit("Databento returned no rows for data or definitions.")
    if "symbol" not in data.columns:
        data = data.reset_index()
    if "symbol" not in definitions.columns:
        definitions = definitions.reset_index()

    if "bid_px_00" not in data.columns or "ask_px_00" not in data.columns:
        raise SystemExit(f"Expected bid_px_00 and ask_px_00 in {args.schema}; columns={list(data.columns)}")

    close_rows = data.groupby("symbol")[["bid_px_00", "ask_px_00"]].last().reset_index()
    def_cols = ["symbol", "instrument_class", "expiration", "strike_price"]
    missing = [col for col in def_cols if col not in definitions.columns]
    if missing:
        raise SystemExit(f"Missing definition columns {missing}; columns={list(definitions.columns)}")
    definitions = definitions[def_cols].drop_duplicates("symbol", keep="last")
    chain = close_rows.merge(definitions, on="symbol", how="left").dropna(subset=["expiration", "strike_price"])
    chain = chain.rename(columns={"bid_px_00": "bid", "ask_px_00": "ask", "strike_price": "strike"})
    chain["quote_date"] = pd.Timestamp(args.date)
    chain["underlying_symbol"] = symbol
    chain["expiration"] = pd.to_datetime(chain["expiration"]).dt.tz_localize(None)
    chain["option_type"] = chain["instrument_class"].map(instrument_class_to_type)
    chain["last"] = (chain["bid"] + chain["ask"]) / 2.0
    chain["underlying_price"] = get_underlying_price(symbol, args.date, args.start_equity_cache)
    for col in ["volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega", "rho"]:
        chain[col] = pd.NA
    out_cols = [
        "quote_date",
        "underlying_symbol",
        "expiration",
        "strike",
        "option_type",
        "bid",
        "ask",
        "last",
        "volume",
        "open_interest",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "underlying_price",
    ]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{symbol}_{args.date}.csv"
    chain[out_cols].to_csv(path, index=False)
    print(f"Wrote {len(chain):,d} option rows to {path}")


if __name__ == "__main__":
    main()
