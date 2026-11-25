import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
DATA_BASE_URL = "https://data.alpaca.markets"


def alpaca_headers() -> Dict[str, str]:
    key_id = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key_id or not secret:
        raise RuntimeError(
            "Missing Alpaca paper credentials. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in your shell."
        )
    return {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def trading_base_url() -> str:
    return os.environ.get("APCA_API_BASE_URL", PAPER_BASE_URL).rstrip("/")


def data_base_url() -> str:
    return os.environ.get("APCA_DATA_BASE_URL", DATA_BASE_URL).rstrip("/")


def request_json(method: str, url: str, params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=alpaca_headers(), method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Alpaca HTTP {exc.code} for {url}: {detail}") from exc


def option_symbol_to_contract_id(symbol: str) -> str:
    root, expiration, option_type, strike = parse_option_symbol(symbol)
    return f"{root}_{expiration:%Y%m%d}_{option_type}_{strike:g}"


def parse_option_symbol(symbol: str):
    match = re.match(r"^(.+?)(\d{6})([CP])(\d{8})$", str(symbol).upper())
    if not match:
        raise ValueError(f"Cannot parse Alpaca/OCC option symbol: {symbol}")
    root, yymmdd, option_type, strike_raw = match.groups()
    expiration = datetime.strptime(yymmdd, "%y%m%d").replace(tzinfo=None)
    strike = int(strike_raw) / 1000.0
    return root, expiration, option_type, strike


def contract_id_to_option_symbol(contract_id: str) -> str:
    parts = str(contract_id).split("_")
    if len(parts) != 4:
        raise ValueError(f"Cannot convert contract_id to Alpaca option symbol: {contract_id}")
    root, expiration, option_type, strike = parts
    yymmdd = datetime.strptime(expiration, "%Y%m%d").strftime("%y%m%d")
    strike_int = int(round(float(strike) * 1000))
    return f"{root.upper()}{yymmdd}{option_type.upper()[0]}{strike_int:08d}"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def chunked(items: Iterable[str], size: int):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
