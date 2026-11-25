"""Intraday replay engine for historical option quote data."""
from dataclasses import replace
from datetime import time as dt_time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from algotrader.option_chain import (
    OptionBacktestConfig,
    OptionPosition,
    _normalize_columns,
    _select_option_from_subset,
)
from algotrader.risk import ProfitLockConfig, option_exit_reason, update_profit_lock_state


TIMESTAMP_ALIASES = {
    "datetime": "timestamp",
    "date_time": "timestamp",
    "quote_datetime": "timestamp",
    "quote_time": "timestamp",
    "time": "timestamp",
    "ts": "timestamp",
    "timestamp": "timestamp",
    "ts_recv": "timestamp",
    "ts_event": "timestamp",
}


def load_intraday_option_quotes(path: str) -> pd.DataFrame:
    """Load one or more intraday option-quote files.

    Expected core columns are timestamp, underlying_symbol, expiration, strike,
    option_type, bid, ask, and underlying_price. Missing ``contract_id``,
    ``mid``, ``spread_pct``, and ``quote_date`` columns are derived.
    """

    source = Path(path)
    if source.is_dir():
        files = sorted(
            file
            for file in source.rglob("*")
            if file.suffix.lower() in {".csv", ".parquet"} and file.name != "download_plan.csv"
        )
    else:
        files = [source]
    if not files:
        raise FileNotFoundError(f"No intraday quote files found at {path}")

    frames = []
    for file in files:
        if file.suffix.lower() == ".parquet":
            frames.append(pd.read_parquet(file))
        else:
            frames.append(pd.read_csv(file))
    return prepare_intraday_option_quotes(pd.concat(frames, ignore_index=True))


def prepare_intraday_option_quotes(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize intraday quote data into the replay engine's canonical shape."""

    rename = {}
    for col in frame.columns:
        key = str(col).strip().lower().replace("-", "_").replace(" ", "_")
        rename[col] = TIMESTAMP_ALIASES.get(key, col)
    out = _normalize_columns(frame.rename(columns=rename))

    if "timestamp" not in out.columns:
        if "quote_date" in out.columns:
            out["timestamp"] = out["quote_date"]
        else:
            raise ValueError("Intraday option quotes require a timestamp column")

    out["timestamp"] = _parse_timestamp(out["timestamp"])
    out = out.dropna(subset=["timestamp"]).copy()
    out["quote_date"] = out["timestamp"].dt.normalize()

    required = ["underlying_symbol", "expiration", "strike", "option_type", "bid", "ask"]
    missing = [col for col in required if col not in out.columns]
    if missing:
        raise ValueError(f"Missing required intraday quote columns: {missing}")

    out = out.dropna(subset=required).copy()
    out["underlying_symbol"] = out["underlying_symbol"].astype(str).str.upper()
    out["option_type"] = out["option_type"].astype(str).str.upper().str[0]
    out["expiration"] = pd.to_datetime(out["expiration"]).dt.tz_localize(None).dt.normalize()
    for col in ["strike", "bid", "ask", "last", "volume", "open_interest", "underlying_price"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "underlying_price" not in out.columns:
        out["underlying_price"] = np.nan
    if "mid" not in out.columns:
        out["mid"] = (out["bid"] + out["ask"]) / 2.0
    if "spread_pct" not in out.columns:
        out["spread_pct"] = (out["ask"] - out["bid"]) / out["mid"].replace(0.0, np.nan)
    if "contract_id" not in out.columns:
        out["contract_id"] = (
            out["underlying_symbol"]
            + "_"
            + out["expiration"].dt.strftime("%Y%m%d")
            + "_"
            + out["option_type"]
            + "_"
            + out["strike"].round(3).astype(str)
        )
    return out.sort_values(["timestamp", "underlying_symbol", "expiration", "strike", "option_type"])


def run_intraday_long_option_replay(
    quotes: pd.DataFrame,
    target_weights: pd.DataFrame,
    initial_cash: float,
    config: OptionBacktestConfig,
    entry_start_time: str = "09:45",
    entry_end_time: str = "15:30",
    entry_frequency_minutes: int = 390,
    check_frequency_minutes: int = 5,
    max_quote_age_minutes: int = 15,
    expiration_exit_days: int = 5,
) -> Dict[str, pd.DataFrame]:
    """Replay the option strategy against intraday quotes.

    Buys fill at ask and sells/marks use bid. The signal weights remain daily,
    but entries can be checked repeatedly inside each session while exits are
    evaluated on every scheduled intraday check.
    """

    quotes = prepare_intraday_option_quotes(quotes)
    if target_weights.empty:
        raise ValueError("Target weights are empty")
    weights = target_weights.copy()
    weights.index = pd.to_datetime(weights.index).tz_localize(None).normalize()
    available_dates = set(weights.index).intersection(set(quotes["quote_date"].unique()))
    if not available_dates:
        raise ValueError("No overlapping dates between target weights and intraday quotes")

    entry_start = _parse_time(entry_start_time)
    entry_end = _parse_time(entry_end_time)
    timestamps = _scheduled_timestamps(
        quotes.loc[quotes["quote_date"].isin(available_dates), "timestamp"].drop_duplicates().sort_values(),
        check_frequency_minutes,
    )
    if not timestamps:
        raise ValueError("No intraday timestamps available after scheduling")

    contract_quotes = _build_contract_quote_book(quotes)
    cash = float(initial_cash)
    positions: Dict[str, OptionPosition] = {}
    profit_lock_state: Dict[str, dict] = {}
    equity_rows: List[dict] = []
    order_rows: List[dict] = []
    events: List[dict] = []
    stopped_symbol_dates: Dict[str, pd.Timestamp] = {}
    last_entry_check: Dict[pd.Timestamp, pd.Timestamp] = {}

    current_month = pd.Timestamp(timestamps[0]).to_period("M")
    month_start_equity = cash
    monthly_stopped = False
    peak_equity = cash

    for timestamp in timestamps:
        date = pd.Timestamp(timestamp).normalize()
        if date not in weights.index:
            continue
        if date.to_period("M") != current_month:
            current_month = date.to_period("M")
            month_start_equity = cash + _mark_positions_intraday(
                contract_quotes, positions, timestamp, config, max_quote_age_minutes
            )
            monthly_stopped = False

        for key, pos in list(positions.items()):
            quote = _latest_contract_quote(contract_quotes, pos.contract_id, timestamp, max_quote_age_minutes)
            if quote is None:
                continue
            exit_price = float(quote["bid"])
            pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
            hold_days = (date - pd.Timestamp(pos.entry_date).normalize()).days
            dte = (pos.expiration - date).days
            profit_lock_config = ProfitLockConfig(
                activation=config.profit_lock_activation,
                floor=config.profit_lock_floor,
                trail=config.profit_lock_trail,
            )
            current_profit_state = profit_lock_state.get(pos.contract_id, {})
            profit_lock_armed = bool(current_profit_state.get("armed", False))
            max_pnl_pct = current_profit_state.get("max_pnl_pct")
            if config.profit_lock_activation > 0 and config.profit_lock_floor > 0:
                profit_lock_armed, max_pnl_pct = update_profit_lock_state(
                    pnl_pct,
                    profit_lock_armed,
                    max_pnl_pct,
                    profit_lock_config,
                )
                profit_lock_state[pos.contract_id] = {
                    "armed": profit_lock_armed,
                    "max_pnl_pct": max_pnl_pct,
                }
            reason = option_exit_reason(
                pnl_pct,
                hold_days,
                dte,
                config.stop_loss,
                config.take_profit,
                config.max_hold_days,
                expiration_exit_days,
                profit_lock_armed=profit_lock_armed,
                max_pnl_pct=max_pnl_pct,
                profit_lock_config=profit_lock_config,
            )
            if (
                not reason
                and config.exit_losing_on_signal_loss
                and hold_days >= config.min_hold_days_for_signal_exit
                and pnl_pct < 0
            ):
                current_weight = 0.0
                if pos.underlying_symbol in weights.columns:
                    current_weight = float(weights.loc[date, pos.underlying_symbol])
                if current_weight <= config.signal_loss_weight_threshold:
                    reason = "signal_loss"
            if not reason:
                continue

            proceeds = exit_price * config.contract_multiplier * pos.quantity
            cash += proceeds
            if reason in {"stop_loss", "signal_loss"}:
                stopped_symbol_dates[pos.underlying_symbol] = date
            order_rows.append(
                {
                    "timestamp": timestamp,
                    "date": date,
                    "symbol": pos.underlying_symbol,
                    "contract_id": pos.contract_id,
                    "action": "SELL",
                    "quantity": pos.quantity,
                    "price": exit_price,
                    "cash_after": cash,
                    "pnl_pct": pnl_pct,
                    "reason": reason,
                }
            )
            del positions[key]
            profit_lock_state.pop(pos.contract_id, None)

        marked_value = _mark_positions_intraday(contract_quotes, positions, timestamp, config, max_quote_age_minutes)
        equity = cash + marked_value
        peak_equity = max(peak_equity, equity)
        equity_drawdown = 1.0 - equity / peak_equity if peak_equity > 0 else 0.0
        month_return = equity / month_start_equity - 1.0 if month_start_equity > 0 else 0.0

        if not monthly_stopped and config.monthly_loss_stop > 0 and month_return <= -config.monthly_loss_stop:
            monthly_stopped = True
            events.append({"timestamp": timestamp, "date": date, "event": "monthly_loss_stop", "month_return": month_return})
            if config.close_on_monthly_loss_stop:
                cash = _liquidate_positions_intraday(
                    contract_quotes,
                    positions,
                    timestamp,
                    config,
                    order_rows,
                    "monthly_loss_stop",
                    cash,
                    max_quote_age_minutes,
                )
                marked_value = _mark_positions_intraday(
                    contract_quotes, positions, timestamp, config, max_quote_age_minutes
                )
                equity = cash + marked_value
            elif config.close_losers_on_monthly_loss_stop:
                cash = _liquidate_positions_intraday(
                    contract_quotes,
                    positions,
                    timestamp,
                    config,
                    order_rows,
                    "monthly_loss_stop_loser",
                    cash,
                    max_quote_age_minutes,
                    only_losers=True,
                )
                marked_value = _mark_positions_intraday(
                    contract_quotes, positions, timestamp, config, max_quote_age_minutes
                )
                equity = cash + marked_value
        if not monthly_stopped and config.monthly_profit_lock > 0 and month_return >= config.monthly_profit_lock:
            monthly_stopped = True
            events.append({"timestamp": timestamp, "date": date, "event": "monthly_profit_lock", "month_return": month_return})
            if config.close_on_monthly_profit_lock:
                cash = _liquidate_positions_intraday(
                    contract_quotes,
                    positions,
                    timestamp,
                    config,
                    order_rows,
                    "monthly_profit_lock",
                    cash,
                    max_quote_age_minutes,
                )
                marked_value = _mark_positions_intraday(
                    contract_quotes, positions, timestamp, config, max_quote_age_minutes
                )
                equity = cash + marked_value

        marked_value = _mark_positions_intraday(contract_quotes, positions, timestamp, config, max_quote_age_minutes)
        equity = cash + marked_value
        peak_equity = max(peak_equity, equity)
        equity_drawdown = 1.0 - equity / peak_equity if peak_equity > 0 else 0.0

        entry_block_reason = ""
        if config.min_equity_for_new_entries > 0 and equity < config.min_equity_for_new_entries:
            entry_block_reason = "entry_equity_floor"
        elif (
            config.max_equity_drawdown_for_new_entries > 0
            and equity_drawdown >= config.max_equity_drawdown_for_new_entries
        ):
            entry_block_reason = "entry_drawdown_pause"
        if entry_block_reason:
            events.append(
                {
                    "timestamp": timestamp,
                    "date": date,
                    "event": entry_block_reason,
                    "equity": equity,
                    "peak_equity": peak_equity,
                    "equity_drawdown": equity_drawdown,
                }
            )

        effective_config = config
        risk_scale = 1.0
        if (
            not entry_block_reason
            and config.low_equity_risk_scale_threshold > 0
            and equity < config.low_equity_risk_scale_threshold
            and config.low_equity_risk_scale < risk_scale
        ):
            risk_scale = max(0.0, float(config.low_equity_risk_scale))
        if (
            not entry_block_reason
            and config.drawdown_risk_scale_threshold > 0
            and equity_drawdown >= config.drawdown_risk_scale_threshold
            and config.drawdown_risk_scale < risk_scale
        ):
            risk_scale = max(0.0, float(config.drawdown_risk_scale))
        if not entry_block_reason and risk_scale < 1.0:
            effective_config = replace(
                config,
                max_premium_fraction=config.max_premium_fraction * risk_scale,
                max_total_premium_fraction=config.max_total_premium_fraction * risk_scale,
            )

        if (
            not monthly_stopped
            and not entry_block_reason
            and _within_time_window(timestamp, entry_start, entry_end)
            and _entry_due(last_entry_check.get(date), timestamp, entry_frequency_minutes)
        ):
            last_entry_check[date] = timestamp
            cash, equity = _enter_positions_intraday(
                quotes,
                contract_quotes,
                weights.loc[date],
                positions,
                stopped_symbol_dates,
                timestamp,
                cash,
                equity,
                effective_config,
                order_rows,
                max_quote_age_minutes,
            )

        marked_value = _mark_positions_intraday(contract_quotes, positions, timestamp, config, max_quote_age_minutes)
        equity = cash + marked_value
        equity_rows.append(
            {
                "timestamp": timestamp,
                "date": date,
                "cash": cash,
                "option_value": marked_value,
                "equity": equity,
                "open_positions": len(positions),
            }
        )

    return {
        "equity": pd.DataFrame(equity_rows),
        "orders": pd.DataFrame(order_rows),
        "events": pd.DataFrame(events),
    }


def _parse_timestamp(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_convert("US/Eastern").dt.tz_localize(None)
    return parsed


def _parse_time(value: str) -> dt_time:
    parsed = pd.Timestamp(f"2000-01-01 {value}")
    return dt_time(parsed.hour, parsed.minute)


def _within_time_window(timestamp: pd.Timestamp, start: dt_time, end: dt_time) -> bool:
    current = pd.Timestamp(timestamp).time()
    return start <= current <= end


def _entry_due(previous: Optional[pd.Timestamp], timestamp: pd.Timestamp, frequency_minutes: int) -> bool:
    if frequency_minutes <= 0:
        return False
    if previous is None:
        return True
    return (pd.Timestamp(timestamp) - pd.Timestamp(previous)).total_seconds() >= frequency_minutes * 60


def _scheduled_timestamps(timestamps: Iterable[pd.Timestamp], frequency_minutes: int) -> List[pd.Timestamp]:
    if frequency_minutes <= 1:
        return [pd.Timestamp(ts) for ts in timestamps]
    scheduled: List[pd.Timestamp] = []
    last_by_date: Dict[pd.Timestamp, pd.Timestamp] = {}
    for raw in timestamps:
        ts = pd.Timestamp(raw)
        date = ts.normalize()
        previous = last_by_date.get(date)
        if previous is None or (ts - previous).total_seconds() >= frequency_minutes * 60:
            scheduled.append(ts)
            last_by_date[date] = ts
    return scheduled


def _build_contract_quote_book(quotes: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    book = {}
    for contract_id, frame in quotes.groupby("contract_id", sort=False):
        book[str(contract_id)] = frame.sort_values("timestamp").set_index("timestamp", drop=False)
    return book


def _latest_contract_quote(
    quote_book: Dict[str, pd.DataFrame],
    contract_id: str,
    timestamp: pd.Timestamp,
    max_quote_age_minutes: int,
) -> Optional[pd.Series]:
    frame = quote_book.get(str(contract_id))
    if frame is None or frame.empty:
        return None
    index = frame.index
    loc = index.searchsorted(pd.Timestamp(timestamp), side="right") - 1
    if loc < 0:
        return None
    quote = frame.iloc[loc]
    age_minutes = (pd.Timestamp(timestamp) - pd.Timestamp(quote["timestamp"])).total_seconds() / 60.0
    if max_quote_age_minutes > 0 and age_minutes > max_quote_age_minutes:
        return None
    return quote


def _latest_symbol_snapshot(
    quotes: pd.DataFrame,
    symbol: str,
    timestamp: pd.Timestamp,
    max_quote_age_minutes: int,
) -> pd.DataFrame:
    timestamp = pd.Timestamp(timestamp)
    date = timestamp.normalize()
    subset = quotes[
        (quotes["quote_date"] == date)
        & (quotes["underlying_symbol"] == symbol.upper())
        & (quotes["timestamp"] <= timestamp)
    ].copy()
    if subset.empty:
        return subset
    if max_quote_age_minutes > 0:
        cutoff = timestamp - pd.Timedelta(minutes=max_quote_age_minutes)
        subset = subset[subset["timestamp"] >= cutoff]
    if subset.empty:
        return subset
    snapshot = subset.sort_values("timestamp").drop_duplicates("contract_id", keep="last")
    snapshot["quote_date"] = date
    return snapshot


def _mark_positions_intraday(
    quote_book: Dict[str, pd.DataFrame],
    positions: Dict[str, OptionPosition],
    timestamp: pd.Timestamp,
    config: OptionBacktestConfig,
    max_quote_age_minutes: int,
) -> float:
    value = 0.0
    for pos in positions.values():
        quote = _latest_contract_quote(quote_book, pos.contract_id, timestamp, max_quote_age_minutes)
        if quote is None:
            continue
        value += float(quote["bid"]) * config.contract_multiplier * pos.quantity
    return value


def _liquidate_positions_intraday(
    quote_book: Dict[str, pd.DataFrame],
    positions: Dict[str, OptionPosition],
    timestamp: pd.Timestamp,
    config: OptionBacktestConfig,
    order_rows: List[dict],
    reason: str,
    starting_cash: float,
    max_quote_age_minutes: int,
    only_losers: bool = False,
) -> float:
    cash = starting_cash
    date = pd.Timestamp(timestamp).normalize()
    for key, pos in list(positions.items()):
        quote = _latest_contract_quote(quote_book, pos.contract_id, timestamp, max_quote_age_minutes)
        if quote is None:
            continue
        exit_price = float(quote["bid"])
        pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
        if only_losers and pnl_pct >= 0:
            continue
        cash += exit_price * config.contract_multiplier * pos.quantity
        order_rows.append(
            {
                "timestamp": timestamp,
                "date": date,
                "symbol": pos.underlying_symbol,
                "contract_id": pos.contract_id,
                "action": "SELL",
                "quantity": pos.quantity,
                "price": exit_price,
                "cash_after": cash,
                "pnl_pct": pnl_pct,
                "reason": reason,
            }
        )
        del positions[key]
    return cash


def _enter_positions_intraday(
    quotes: pd.DataFrame,
    quote_book: Dict[str, pd.DataFrame],
    weights: pd.Series,
    positions: Dict[str, OptionPosition],
    stopped_symbol_dates: Dict[str, pd.Timestamp],
    timestamp: pd.Timestamp,
    cash: float,
    equity: float,
    config: OptionBacktestConfig,
    order_rows: List[dict],
    max_quote_age_minutes: int,
) -> tuple[float, float]:
    date = pd.Timestamp(timestamp).normalize()
    if config.allow_put_entries:
        ordered_weights = weights.reindex(weights.abs().sort_values(ascending=False).index)
    else:
        ordered_weights = weights.sort_values(ascending=False)
    gross_premium = sum(pos.entry_cost for pos in positions.values())
    open_symbols = {pos.underlying_symbol for pos in positions.values()}
    for symbol, raw_weight in ordered_weights.items():
        symbol = str(symbol).upper()
        weight = float(raw_weight)
        signal_strength = abs(weight) if config.allow_put_entries else weight
        if signal_strength <= 0 or signal_strength < config.min_entry_weight or symbol in open_symbols:
            continue
        last_stop_date = stopped_symbol_dates.get(symbol)
        if (
            config.stop_loss_cooldown_days > 0
            and last_stop_date is not None
            and (date - last_stop_date).days <= config.stop_loss_cooldown_days
        ):
            continue
        equity = cash + _mark_positions_intraday(quote_book, positions, timestamp, config, max_quote_age_minutes)
        if gross_premium >= equity * config.max_total_premium_fraction:
            break
        option_type = "P" if config.allow_put_entries and weight < 0 else "C"
        snapshot = _latest_symbol_snapshot(quotes, symbol, timestamp, max_quote_age_minutes)
        if snapshot.empty:
            continue
        pick = _select_option_from_subset(snapshot, date, equity, config, option_type)
        if pick is None:
            continue
        contract_cost = float(pick["ask"]) * config.contract_multiplier
        max_contracts_by_cash = int(cash // contract_cost)
        if max_contracts_by_cash <= 0:
            continue
        premium_fraction = config.max_premium_fraction
        if option_type == "P" and config.put_max_premium_fraction is not None:
            premium_fraction = config.put_max_premium_fraction
        desired_premium = min(equity * signal_strength, equity * premium_fraction)
        remaining_total_budget = equity * config.max_total_premium_fraction - gross_premium
        max_contracts_by_total = int(remaining_total_budget // contract_cost)
        if max_contracts_by_total <= 0:
            continue
        max_contracts_by_config = config.max_contracts_per_trade if config.max_contracts_per_trade > 0 else max_contracts_by_cash
        qty = max(
            1,
            min(
                max_contracts_by_cash,
                max_contracts_by_total,
                max_contracts_by_config,
                int(desired_premium // contract_cost),
            ),
        )
        total_cost = contract_cost * qty
        if total_cost > cash or gross_premium + total_cost > equity * config.max_total_premium_fraction:
            continue
        cash -= total_cost
        gross_premium += total_cost
        pos = OptionPosition(
            contract_id=str(pick["contract_id"]),
            underlying_symbol=symbol,
            expiration=pd.Timestamp(pick["expiration"]),
            strike=float(pick["strike"]),
            option_type=option_type,
            quantity=qty,
            entry_date=timestamp,
            entry_price=float(pick["ask"]),
            entry_cost=total_cost,
        )
        positions[pos.contract_id] = pos
        open_symbols.add(symbol)
        order_rows.append(
            {
                "timestamp": timestamp,
                "date": date,
                "symbol": symbol,
                "contract_id": pos.contract_id,
                "action": "BUY",
                "quantity": qty,
                "price": pos.entry_price,
                "cash_after": cash,
                "pnl_pct": 0.0,
                "reason": "entry",
            }
        )
    equity = cash + _mark_positions_intraday(quote_book, positions, timestamp, config, max_quote_age_minutes)
    return cash, equity
