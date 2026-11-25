#!/usr/bin/env python3
import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time, timedelta
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
OUT_COLS = [
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
OUT_INTRADAY_COLS = ["timestamp"] + OUT_COLS


def parse_args():
    parser = argparse.ArgumentParser(description="Fast Databento OPRA fetcher using one multi-symbol request per day.")
    parser.add_argument("--weights", default="artifacts/synthetic_optionlike_5x/latest_weights.csv")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-dir", default="data/options/databento_year")
    parser.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY", ""))
    parser.add_argument("--schema", default="cbbo-1m", choices=["cbbo-1m", "bbo-1m", "tbbo", "trades"])
    parser.add_argument("--minutes-before-close", type=int, default=15)
    parser.add_argument(
        "--preserve-intraday",
        action="store_true",
        help="Keep every fetched quote row with timestamps instead of writing only the final quote snapshot",
    )
    parser.add_argument("--max-symbols-per-day", type=int, default=3)
    parser.add_argument(
        "--coverage-lookback-trading-days",
        type=int,
        default=0,
        help="Also fetch symbols that were top-ranked in this many previous trading rows, so held positions keep quote coverage",
    )
    parser.add_argument("--max-request-cost", type=float, default=0.50)
    parser.add_argument("--max-total-cost", type=float, default=20.0)
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--skip-estimate", action="store_true", help="Fetch directly from the generated/resumed plan without Databento cost preflight")
    parser.add_argument("--use-existing-plan", action="store_true")
    parser.add_argument("--workers", type=int, default=1, help="Number of day-level Databento fetches to run in parallel")
    parser.add_argument("--plan-file", default="")
    parser.add_argument("--flat", action="store_true", help="Write files directly under output-dir instead of YYYY-MM subfolders")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=float, default=5.0)
    parser.add_argument("--start-equity-cache", default="2016-01-01")
    return parser.parse_args()


def close_window(trade_date, minutes_before_close):
    eastern = ZoneInfo("US/Eastern")
    day = pd.Timestamp(trade_date).date()
    close_time = dt_time(13, 0) if day.isoformat() in EARLY_CLOSE_DATES else dt_time(16, 0)
    end = datetime.combine(day, close_time, tzinfo=eastern)
    start = end - timedelta(minutes=minutes_before_close)
    return start, end


def option_file(output_dir, symbol, date, flat=False):
    date = pd.Timestamp(date)
    parent = Path(output_dir)
    if not flat:
        parent = parent / date.strftime("%Y-%m")
    return parent / f"{symbol}_{date.date().isoformat()}.csv"


def build_plan(args):
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    weights = weights.loc[(weights.index >= pd.Timestamp(args.start)) & (weights.index <= pd.Timestamp(args.end))]
    if weights.empty:
        raise SystemExit("No weights found in the requested date range.")
    rows = []
    for idx, (date, row) in enumerate(weights.iterrows()):
        symbols = set(row[row > 0].sort_values(ascending=False).head(args.max_symbols_per_day).index.tolist())
        if args.coverage_lookback_trading_days > 0:
            start_idx = max(0, idx - args.coverage_lookback_trading_days)
            for _, past_row in weights.iloc[start_idx:idx].iterrows():
                symbols.update(past_row[past_row > 0].sort_values(ascending=False).head(args.max_symbols_per_day).index.tolist())
        symbols = sorted(symbols)
        if not symbols:
            continue
        missing = []
        for symbol in symbols:
            path = option_file(args.output_dir, symbol, date, args.flat)
            if path.exists() and path.stat().st_size > 0:
                rows.append(
                    {
                        "date": date.date().isoformat(),
                        "symbol": symbol,
                        "path": str(path),
                        "cached": True,
                        "estimated_cost": 0.0,
                    }
                )
            else:
                missing.append(symbol)
        for symbol in missing:
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "path": str(option_file(args.output_dir, symbol, date, args.flat)),
                    "cached": False,
                    "estimated_cost": pd.NA,
                }
            )
    return pd.DataFrame(rows)


def parents(symbols):
    return [f"{symbol}.OPT" for symbol in symbols]


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


def estimate_day(client, args, date, symbols):
    start, end = close_window(date, args.minutes_before_close)
    parent_symbols = parents(symbols)
    quote_cost = client.metadata.get_cost(
        dataset=DATASET,
        schema=args.schema,
        stype_in="parent",
        symbols=parent_symbols,
        start=start,
        end=end,
    )
    definition_cost = client.metadata.get_cost(
        dataset=DATASET,
        schema="definition",
        stype_in="parent",
        symbols=parent_symbols,
        start=pd.Timestamp(date).date().isoformat(),
    )
    return float(quote_cost + definition_cost)


def instrument_class_to_type(value):
    text = str(value).upper()
    if text.startswith("C") or "CALL" in text:
        return "C"
    if text.startswith("P") or "PUT" in text:
        return "P"
    return text[:1]


def compact_symbol(value):
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def infer_underlying(raw_symbol, requested_symbols):
    compact = compact_symbol(raw_symbol)
    for symbol in sorted(requested_symbols, key=len, reverse=True):
        if compact.startswith(compact_symbol(symbol)):
            return symbol
    return pd.NA


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
    date = pd.Timestamp(date)
    available = series.loc[series.index <= date]
    if available.empty:
        return float("nan")
    return float(available.iloc[-1])


def timestamp_column(frame):
    for col in ["ts_recv", "ts_event", "timestamp", "index"]:
        if col in frame.columns:
            return col
    return ""


def to_eastern_naive(series):
    parsed = pd.to_datetime(series, errors="coerce")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        return parsed.dt.tz_convert("US/Eastern").dt.tz_localize(None)
    return parsed


def fetch_day(client, args, date, symbols, closes):
    start, end = close_window(date, args.minutes_before_close)
    parent_symbols = parents(symbols)
    data = run_with_retries(
        args,
        f"quote fetch {date} {','.join(symbols)}",
        lambda: client.timeseries.get_range(
            dataset=DATASET,
            schema=args.schema,
            stype_in="parent",
            symbols=parent_symbols,
            start=start,
            end=end,
        ).to_df(),
    )
    definitions = run_with_retries(
        args,
        f"definition fetch {date} {','.join(symbols)}",
        lambda: client.timeseries.get_range(
            dataset=DATASET,
            schema="definition",
            stype_in="parent",
            symbols=parent_symbols,
            start=pd.Timestamp(date).date().isoformat(),
        ).to_df(),
    )
    if data.empty or definitions.empty:
        written = []
        columns = OUT_INTRADAY_COLS if args.preserve_intraday else OUT_COLS
        for symbol in symbols:
            path = option_file(args.output_dir, symbol, date, args.flat)
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(columns=columns).to_csv(path, index=False)
            written.append({"symbol": symbol, "path": str(path), "rows": 0})
        return written
    if "symbol" not in data.columns or not timestamp_column(data):
        data = data.reset_index()
    if "symbol" not in definitions.columns:
        definitions = definitions.reset_index()
    if "bid_px_00" not in data.columns or "ask_px_00" not in data.columns:
        raise RuntimeError(f"Expected bid_px_00 and ask_px_00 in {args.schema}; columns={list(data.columns)}")

    def_cols = ["symbol", "instrument_class", "expiration", "strike_price"]
    missing = [col for col in def_cols if col not in definitions.columns]
    if missing:
        raise RuntimeError(f"Missing definition columns {missing}; columns={list(definitions.columns)}")
    definitions = definitions[def_cols].drop_duplicates("symbol", keep="last")
    if args.preserve_intraday:
        ts_col = timestamp_column(data)
        if not ts_col:
            raise RuntimeError(f"Could not infer timestamp column from Databento output; columns={list(data.columns)}")
        quote_rows = data[[ts_col, "symbol", "bid_px_00", "ask_px_00"]].copy()
        quote_rows = quote_rows.rename(columns={ts_col: "timestamp"})
        quote_rows["timestamp"] = to_eastern_naive(quote_rows["timestamp"])
        chain = quote_rows.merge(definitions, on="symbol", how="left").dropna(subset=["timestamp", "expiration", "strike_price"])
    else:
        close_rows = data.groupby("symbol")[["bid_px_00", "ask_px_00"]].last().reset_index()
        chain = close_rows.merge(definitions, on="symbol", how="left").dropna(subset=["expiration", "strike_price"])
    chain = chain.rename(columns={"bid_px_00": "bid", "ask_px_00": "ask", "strike_price": "strike"})
    if args.preserve_intraday:
        chain["quote_date"] = pd.to_datetime(chain["timestamp"]).dt.normalize()
    else:
        chain["quote_date"] = pd.Timestamp(date)
    chain["underlying_symbol"] = chain["symbol"].map(lambda raw: infer_underlying(raw, symbols))
    chain = chain.dropna(subset=["underlying_symbol"])
    chain["expiration"] = pd.to_datetime(chain["expiration"]).dt.tz_localize(None)
    chain["option_type"] = chain["instrument_class"].map(instrument_class_to_type)
    chain["last"] = (chain["bid"] + chain["ask"]) / 2.0
    for col in ["volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega", "rho"]:
        chain[col] = pd.NA

    written = []
    for symbol, subset in chain.groupby("underlying_symbol"):
        subset = subset.copy()
        subset["underlying_price"] = underlying_close(closes, symbol, date)
        path = option_file(args.output_dir, symbol, date, args.flat)
        path.parent.mkdir(parents=True, exist_ok=True)
        columns = OUT_INTRADAY_COLS if args.preserve_intraday else OUT_COLS
        subset[columns].to_csv(path, index=False)
        written.append({"symbol": symbol, "path": str(path), "rows": len(subset)})
    return written


def save_plan(plan, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    plan.to_csv(path, index=False)


def main():
    args = parse_args()
    if not args.api_key:
        raise SystemExit("Missing Databento key. Set DATABENTO_API_KEY or pass --api-key.")
    import databento as db

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_file = Path(args.plan_file) if args.plan_file else output_dir / "download_plan.csv"
    if args.use_existing_plan:
        if not plan_file.exists():
            raise SystemExit(f"Plan file not found: {plan_file}")
        plan = pd.read_csv(plan_file)
    else:
        plan = build_plan(args)

    if plan.empty:
        print("No symbols to fetch.")
        return

    client = db.Historical(args.api_key)
    if not args.use_existing_plan and not args.skip_estimate:
        missing = plan[~plan["cached"].astype(bool)].copy()
        estimates = []
        for date, group in missing.groupby("date", sort=True):
            symbols = sorted(group["symbol"].tolist())
            cost = run_with_retries(args, f"estimate {date} {','.join(symbols)}", lambda d=date, s=symbols: estimate_day(client, args, d, s))
            if cost > args.max_request_cost:
                raise SystemExit(f"Refusing {date}: estimated request ${cost:.4f} exceeds --max-request-cost ${args.max_request_cost:.2f}")
            per_symbol = cost / max(len(symbols), 1)
            plan.loc[(plan["date"] == date) & (plan["symbol"].isin(symbols)), "estimated_cost"] = per_symbol
            estimates.append((date, symbols, cost))
            print(f"Estimated {date} {','.join(symbols)}: ${cost:.4f}")
        total_cost = sum(cost for _, _, cost in estimates)
        print(f"Estimated uncached total for {len(estimates)} day requests / {len(missing)} chain files: ${total_cost:.4f}")
        if total_cost > args.max_total_cost:
            save_plan(plan, plan_file)
            raise SystemExit(f"Refusing batch: estimated total ${total_cost:.4f} exceeds --max-total-cost ${args.max_total_cost:.2f}")
        save_plan(plan, plan_file)
    elif args.skip_estimate and not args.use_existing_plan:
        save_plan(plan, plan_file)
        missing = plan[~plan["cached"].astype(bool)]
        print(f"Skipping Databento estimates. Plan written to {plan_file} with {len(missing)} uncached chain files.")
    else:
        total_cost = pd.to_numeric(plan.get("estimated_cost", 0.0), errors="coerce").fillna(0.0).sum()
        print(f"Loaded existing plan {plan_file}; planned uncached cost allocation: ${total_cost:.4f}")

    if args.estimate_only:
        print(f"Estimate-only mode. Plan written to {plan_file}")
        return

    pending = []
    for _, row in plan.iterrows():
        path = Path(str(row["path"]))
        if bool(row.get("cached", False)) or (path.exists() and path.stat().st_size > 0):
            continue
        pending.append(row)
    if not pending:
        print(f"All planned chain files already exist under {output_dir}")
        return

    symbols_all = sorted({str(row["symbol"]) for row in pending})
    closes = load_underlying_prices(symbols_all, args.start, args.end, args.start_equity_cache)
    day_groups = [(date, sorted(group["symbol"].tolist())) for date, group in pd.DataFrame(pending).groupby("date", sort=True)]
    fetched_files = 0
    if args.workers <= 1:
        for date, symbols in day_groups:
            written = fetch_day(client, args, date, symbols, closes)
            fetched_files += len(written)
            details = ", ".join(f"{item['symbol']}:{item['rows']}" for item in written)
            print(f"Fetched {date} {details}")
    else:
        def fetch_with_new_client(date, symbols):
            worker_client = db.Historical(args.api_key)
            return date, fetch_day(worker_client, args, date, symbols, closes)

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(fetch_with_new_client, date, symbols) for date, symbols in day_groups]
            for future in as_completed(futures):
                date, written = future.result()
                fetched_files += len(written)
                details = ", ".join(f"{item['symbol']}:{item['rows']}" for item in written)
                print(f"Fetched {date} {details}")
    print(f"Fetched {fetched_files} chain files into {output_dir}")


if __name__ == "__main__":
    main()
