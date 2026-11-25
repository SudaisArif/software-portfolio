#!/usr/bin/env python3
"""Fetch intraday Databento quotes for specific OCC option contracts."""
import argparse
import os
import sys
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.data import download_prices  # noqa: E402


DATASET = "OPRA.PILLAR"
EARLY_CLOSE_DATES = {
    "2025-07-03",
    "2025-11-28",
    "2025-12-24",
    "2026-07-02",
    "2026-11-27",
    "2026-12-24",
}
OUT_COLS = [
    "timestamp",
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
    "contract_id",
    "broker_symbol",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch minute OPRA quotes for selected option contracts.")
    parser.add_argument("--orders", required=True, help="Orders CSV containing contract_id rows")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", default="data/options_intraday/databento_contracts")
    parser.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY", ""))
    parser.add_argument("--schema", default="cbbo-1m", choices=["cbbo-1m", "bbo-1m", "tbbo", "trades"])
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--skip-estimate", action="store_true")
    parser.add_argument("--max-cost", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=float, default=5.0)
    parser.add_argument("--start-equity-cache", default="2016-01-01")
    return parser.parse_args()


def parse_contract_id(contract_id):
    parts = str(contract_id).split("_")
    if len(parts) != 4:
        raise ValueError(f"Cannot parse contract_id: {contract_id}")
    root, expiration, option_type, strike = parts
    return root.upper(), pd.Timestamp(expiration), option_type.upper()[0], float(strike)


def contract_id_to_occ_symbol(contract_id):
    root, expiration, option_type, strike = parse_contract_id(contract_id)
    yymmdd = expiration.strftime("%y%m%d")
    strike_int = int(round(strike * 1000))
    return f"{root:<6}{yymmdd}{option_type}{strike_int:08d}"


def session_window(trade_date):
    eastern = ZoneInfo("US/Eastern")
    day = pd.Timestamp(trade_date).date()
    close_time = dt_time(13, 0) if day.isoformat() in EARLY_CLOSE_DATES else dt_time(16, 0)
    start = datetime.combine(day, dt_time(9, 30), tzinfo=eastern)
    end = datetime.combine(day, close_time, tzinfo=eastern)
    return start, end


def trading_days(start, end):
    return list(pd.bdate_range(start, end))


def build_contracts(orders_path):
    orders = pd.read_csv(orders_path)
    if "contract_id" not in orders.columns:
        raise ValueError("Orders CSV must contain contract_id")
    contracts = []
    for contract_id in sorted(set(orders["contract_id"].dropna().astype(str))):
        root, expiration, option_type, strike = parse_contract_id(contract_id)
        broker_symbol = contract_id_to_occ_symbol(contract_id)
        contracts.append(
            {
                "contract_id": contract_id,
                "broker_symbol": broker_symbol,
                "underlying_symbol": root,
                "expiration": expiration,
                "option_type": option_type,
                "strike": strike,
            }
        )
    return pd.DataFrame(contracts)


def to_eastern_naive(series):
    parsed = pd.to_datetime(series, errors="coerce")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        return parsed.dt.tz_convert("US/Eastern").dt.tz_localize(None)
    return parsed


def timestamp_column(frame):
    for col in ["ts_recv", "ts_event", "timestamp", "index"]:
        if col in frame.columns:
            return col
    return ""


def run_with_retries(args, label, fn):
    last_error = None
    for attempt in range(args.retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            text = str(exc).lower()
            retryable = any(part in text for part in ["504", "timed out", "timeout", "temporarily"])
            if not retryable or attempt >= args.retries:
                raise
            wait = args.retry_sleep_seconds * (attempt + 1)
            print(f"Retrying {label}; attempt {attempt + 2}/{args.retries + 1} in {wait:.1f}s")
            time.sleep(wait)
    raise last_error


def load_underlying_prices(symbols, start, end, cache_start):
    prices = download_prices(sorted(symbols), cache_start, end, "data/cache", refresh=False)
    closes = {}
    for symbol, frame in prices.items():
        series = frame["Close"].copy()
        series.index = pd.to_datetime(series.index).tz_localize(None)
        closes[symbol] = series
    return closes


def underlying_close(closes, symbol, date):
    series = closes.get(symbol)
    if series is None or series.empty:
        return float("nan")
    available = series.loc[series.index <= pd.Timestamp(date)]
    if available.empty:
        return float("nan")
    return float(available.iloc[-1])


def normalize_quotes(data, contracts, closes, date):
    if data.empty:
        return pd.DataFrame(columns=OUT_COLS)
    if "symbol" not in data.columns or not timestamp_column(data):
        data = data.reset_index()
    ts_col = timestamp_column(data)
    required = [ts_col, "symbol", "bid_px_00", "ask_px_00"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise RuntimeError(f"Missing quote columns {missing}; columns={list(data.columns)}")
    rows = data[required].rename(columns={ts_col: "timestamp", "bid_px_00": "bid", "ask_px_00": "ask"}).copy()
    rows["timestamp"] = to_eastern_naive(rows["timestamp"])
    rows = rows.merge(contracts, left_on="symbol", right_on="broker_symbol", how="inner")
    if rows.empty:
        return pd.DataFrame(columns=OUT_COLS)
    rows["quote_date"] = pd.to_datetime(rows["timestamp"]).dt.normalize()
    rows["last"] = (rows["bid"] + rows["ask"]) / 2.0
    for col in ["volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega", "rho"]:
        rows[col] = pd.NA
    rows["underlying_price"] = rows["underlying_symbol"].map(
        lambda symbol: underlying_close(closes, symbol, date)
    )
    return rows[OUT_COLS].sort_values(["timestamp", "underlying_symbol", "expiration", "strike", "option_type"])


def main():
    args = parse_args()
    if not args.api_key:
        raise SystemExit("Missing Databento key. Set DATABENTO_API_KEY or pass --api-key.")
    import databento as db

    contracts = build_contracts(args.orders)
    if contracts.empty:
        raise SystemExit("No contracts found in orders CSV.")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts.to_csv(output_dir / "contracts.csv", index=False)
    symbols = contracts["broker_symbol"].tolist()
    days = trading_days(args.start, args.end)

    client = db.Historical(args.api_key)
    if not args.skip_estimate:
        total = 0.0
        for day in days:
            start, end = session_window(day)
            cost = run_with_retries(
                args,
                f"estimate {day.date()}",
                lambda s=start, e=end: client.metadata.get_cost(
                    dataset=DATASET,
                    schema=args.schema,
                    stype_in="raw_symbol",
                    symbols=symbols,
                    start=s,
                    end=e,
                ),
            )
            total += float(cost)
            print(f"Estimated {day.date()}: ${float(cost):.4f}")
        print(f"Estimated total: ${total:.4f}")
        if total > args.max_cost:
            raise SystemExit(f"Refusing fetch: estimated ${total:.4f} exceeds --max-cost ${args.max_cost:.2f}")
        if args.estimate_only:
            return
    elif args.estimate_only:
        raise SystemExit("--estimate-only cannot be combined with --skip-estimate")

    closes = load_underlying_prices(contracts["underlying_symbol"].unique(), args.start_equity_cache, args.end, args.start_equity_cache)
    written = []
    all_frames = []
    for day in days:
        output_file = output_dir / f"quotes_{day.date().isoformat()}.csv"
        if output_file.exists() and output_file.stat().st_size > 0:
            frame = pd.read_csv(output_file)
            all_frames.append(frame)
            written.append({"date": day.date().isoformat(), "rows": len(frame), "cached": True})
            continue
        start, end = session_window(day)
        data = run_with_retries(
            args,
            f"fetch {day.date()}",
            lambda s=start, e=end: client.timeseries.get_range(
                dataset=DATASET,
                schema=args.schema,
                stype_in="raw_symbol",
                symbols=symbols,
                start=s,
                end=e,
            ).to_df(),
        )
        frame = normalize_quotes(data, contracts, closes, day)
        frame.to_csv(output_file, index=False)
        all_frames.append(frame)
        written.append({"date": day.date().isoformat(), "rows": len(frame), "cached": False})
        print(f"Fetched {day.date()}: {len(frame)} rows")

    manifest = pd.DataFrame(written)
    manifest.to_csv(output_dir / "manifest.csv", index=False)
    combined = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame(columns=OUT_COLS)
    combined.to_parquet(output_dir / "quotes.parquet", index=False)
    print(f"Wrote: {output_dir / 'quotes.parquet'}")
    print(f"Rows: {len(combined)}")
    print(f"Contracts: {len(contracts)}")


if __name__ == "__main__":
    main()
