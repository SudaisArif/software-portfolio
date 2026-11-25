import os
import re
from datetime import date
from typing import Dict, Iterable

import pandas as pd


OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def safe_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", symbol)


def _cache_path(cache_dir: str, symbol: str, start: str, end: str) -> str:
    end_label = end or "latest"
    name = f"{safe_symbol(symbol)}_{start}_{end_label}.csv"
    return os.path.join(cache_dir, name)


def _find_covering_cache_path(cache_dir: str, symbol: str, start: str, end: str) -> str:
    """Return a broader cached file that covers the requested end date."""
    exact = _cache_path(cache_dir, symbol, start, end)
    if os.path.exists(exact):
        return exact

    requested_end = pd.Timestamp(end or date.today().isoformat())
    prefix = f"{safe_symbol(symbol)}_{start}_"
    best_path = ""
    best_end = pd.Timestamp.min
    if not os.path.isdir(cache_dir):
        return exact

    for name in os.listdir(cache_dir):
        if not name.startswith(prefix) or not name.endswith(".csv"):
            continue
        label = name[len(prefix) : -4]
        candidate_end = pd.Timestamp.max if label == "latest" else pd.to_datetime(label, errors="coerce")
        if pd.isna(candidate_end) or candidate_end < requested_end:
            continue
        if candidate_end < best_end:
            continue
        best_end = candidate_end
        best_path = os.path.join(cache_dir, name)
    return best_path or exact


def read_cached_prices(cache_dir: str, symbol: str, start: str, end: str) -> pd.DataFrame:
    path = _find_covering_cache_path(cache_dir, symbol, start, end)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    frame = _normalize_ohlcv(frame)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end or date.today().isoformat())
    return frame.loc[(frame.index >= start_ts) & (frame.index <= end_ts)]


def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [col[0] for col in frame.columns]
    frame = frame.copy()
    rename = {col: col.title() for col in frame.columns}
    frame = frame.rename(columns=rename)
    missing = [col for col in OHLCV_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")
    frame = frame[OHLCV_COLUMNS].dropna(subset=["Close"])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame


def download_prices(
    symbols: Iterable[str],
    start: str,
    end: str,
    cache_dir: str,
    refresh: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Download adjusted OHLCV data with a CSV cache fallback."""
    import yfinance as yf

    os.makedirs(cache_dir, exist_ok=True)
    prices: Dict[str, pd.DataFrame] = {}
    failures = []
    for symbol in dict.fromkeys(symbols):
        path = _find_covering_cache_path(cache_dir, symbol, start, end)
        if os.path.exists(path) and not refresh:
            prices[symbol] = read_cached_prices(cache_dir, symbol, start, end)
            continue

        try:
            raw = yf.download(
                symbol,
                start=start,
                end=end or None,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if raw.empty:
                raise ValueError("download returned no rows")
            frame = _normalize_ohlcv(raw)
            frame.to_csv(path, index_label="Date")
            prices[symbol] = frame
        except Exception as exc:  # pragma: no cover - depends on network provider
            if os.path.exists(path):
                prices[symbol] = read_cached_prices(cache_dir, symbol, start, end)
            else:
                failures.append(f"{symbol}: {exc}")
    if failures:
        raise RuntimeError("Unable to load data for " + "; ".join(failures))
    return prices


def close_matrix(prices: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    closes = {symbol: frame["Close"] for symbol, frame in prices.items()}
    out = pd.DataFrame(closes).sort_index()
    return out.dropna(how="all")


def ohlcv_panel(prices: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for symbol, frame in prices.items():
        item = frame.copy()
        item["Symbol"] = symbol
        frames.append(item.reset_index().rename(columns={"index": "Date"}))
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.rename(columns={panel.columns[0]: "Date"})
    panel["Date"] = pd.to_datetime(panel["Date"]).dt.tz_localize(None)
    return panel.set_index(["Date", "Symbol"]).sort_index()
