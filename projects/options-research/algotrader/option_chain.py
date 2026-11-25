from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from algotrader.risk import ProfitLockConfig, option_exit_reason, update_profit_lock_state


CANONICAL_COLUMNS = [
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


ALIASES = {
    "date": "quote_date",
    "quote_datetime": "quote_date",
    "quote date": "quote_date",
    "underlying": "underlying_symbol",
    "underlying symbol": "underlying_symbol",
    "symbol": "underlying_symbol",
    "root": "underlying_symbol",
    "expiry": "expiration",
    "expiration_date": "expiration",
    "option type": "option_type",
    "right": "option_type",
    "call_put": "option_type",
    "open interest": "open_interest",
    "openinterest": "open_interest",
    "iv": "implied_volatility",
    "implied volatility": "implied_volatility",
    "active underlying price": "underlying_price",
    "underlying price": "underlying_price",
    "underlying_close": "underlying_price",
}


@dataclass(frozen=True)
class OptionBacktestConfig:
    min_dte: int = 14
    max_dte: int = 45
    target_delta: float = 0.45
    min_delta: float = 0.25
    max_delta: float = 0.70
    max_spread_pct: float = 0.18
    min_open_interest: int = 50
    min_volume: int = 1
    max_premium_fraction: float = 0.35
    max_total_premium_fraction: float = 0.85
    put_max_premium_fraction: Optional[float] = None
    min_contract_price: float = 0.0
    max_contracts_per_trade: int = 0
    min_otm_pct: Optional[float] = None
    max_otm_pct: Optional[float] = None
    min_otm_pct_by_symbol: Optional[Dict[str, Optional[float]]] = None
    max_otm_pct_by_symbol: Optional[Dict[str, Optional[float]]] = None
    min_entry_weight: float = 0.0
    stop_loss: float = 0.45
    take_profit: float = 1.25
    profit_lock_activation: float = 0.0
    profit_lock_floor: float = 0.0
    profit_lock_trail: float = 0.0
    max_hold_days: int = 7
    exit_losing_on_signal_loss: bool = False
    signal_loss_weight_threshold: float = 0.0
    min_hold_days_for_signal_exit: int = 1
    stop_loss_cooldown_days: int = 0
    min_equity_for_new_entries: float = 0.0
    low_equity_risk_scale_threshold: float = 0.0
    low_equity_risk_scale: float = 1.0
    max_equity_drawdown_for_new_entries: float = 0.0
    drawdown_risk_scale_threshold: float = 0.0
    drawdown_risk_scale: float = 1.0
    monthly_loss_stop: float = 0.20
    monthly_profit_lock: float = 0.60
    close_on_monthly_loss_stop: bool = False
    close_losers_on_monthly_loss_stop: bool = False
    close_on_monthly_profit_lock: bool = False
    close_before_month_end: bool = False
    allow_put_entries: bool = False
    contract_multiplier: int = 100


@dataclass
class OptionPosition:
    contract_id: str
    underlying_symbol: str
    expiration: pd.Timestamp
    strike: float
    option_type: str
    quantity: int
    entry_date: pd.Timestamp
    entry_price: float
    entry_cost: float


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in frame.columns:
        key = str(col).strip().lower().replace("-", "_")
        key = key.replace(" ", "_")
        rename[col] = ALIASES.get(key, key)
    out = frame.rename(columns=rename).copy()
    if "option_type" in out.columns:
        out["option_type"] = out["option_type"].astype(str).str.upper().str[0]
    for col in ["quote_date", "expiration"]:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col]).dt.tz_localize(None)
    for col in [
        "strike",
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
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_option_chains(path: str) -> pd.DataFrame:
    source = Path(path)
    if source.is_file() and source.suffix.lower() == ".parquet":
        out = pd.read_parquet(source)
        required = ["quote_date", "underlying_symbol", "expiration", "strike", "option_type", "bid", "ask"]
        if any(col not in out.columns for col in required):
            out = _normalize_columns(out)
        missing = [col for col in required if col not in out.columns]
        if missing:
            raise ValueError(f"Missing required option-chain columns: {missing}")
        out = out.dropna(subset=required).copy()
        if not pd.api.types.is_datetime64_any_dtype(out["quote_date"]):
            out["quote_date"] = pd.to_datetime(out["quote_date"]).dt.tz_localize(None)
        if not pd.api.types.is_datetime64_any_dtype(out["expiration"]):
            out["expiration"] = pd.to_datetime(out["expiration"]).dt.tz_localize(None)
        out["underlying_symbol"] = out["underlying_symbol"].astype(str).str.upper()
        out["option_type"] = out["option_type"].astype(str).str.upper().str[0]
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
        return out
    files: List[Path]
    if source.is_dir():
        files = sorted(file for file in source.rglob("*.csv") if file.name != "download_plan.csv")
    else:
        files = [source]
    if not files:
        raise FileNotFoundError(f"No option chain CSV files found at {path}")
    frames = []
    for file in files:
        if file.suffix.lower() == ".parquet":
            frame = pd.read_parquet(file)
        else:
            frame = pd.read_csv(file)
        frame = _normalize_columns(frame)
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    required = ["quote_date", "underlying_symbol", "expiration", "strike", "option_type", "bid", "ask"]
    missing = [col for col in required if col not in out.columns]
    if missing:
        raise ValueError(f"Missing required option-chain columns: {missing}")
    out = out.dropna(subset=required)
    out["underlying_symbol"] = out["underlying_symbol"].astype(str).str.upper()
    out["mid"] = (out["bid"] + out["ask"]) / 2.0
    out["spread_pct"] = (out["ask"] - out["bid"]) / out["mid"].replace(0.0, np.nan)
    out["contract_id"] = (
        out["underlying_symbol"]
        + "_"
        + out["expiration"].dt.strftime("%Y%m%d")
        + "_"
        + out["option_type"]
        + "_"
        + out["strike"].round(3).astype(str)
    )
    return out.sort_values(["quote_date", "underlying_symbol", "expiration", "strike", "option_type"])


def select_call_contract(
    chain: pd.DataFrame,
    symbol: str,
    date: pd.Timestamp,
    equity: float,
    config: OptionBacktestConfig,
) -> Optional[pd.Series]:
    return select_option_contract(chain, symbol, date, equity, config, "C")


def select_option_contract(
    chain: pd.DataFrame,
    symbol: str,
    date: pd.Timestamp,
    equity: float,
    config: OptionBacktestConfig,
    option_type: str = "C",
) -> Optional[pd.Series]:
    option_type = option_type.upper()[0]
    subset = chain[
        (chain["quote_date"] == date)
        & (chain["underlying_symbol"] == symbol.upper())
        & (chain["option_type"] == option_type)
    ].copy()
    return _select_option_from_subset(subset, date, equity, config, option_type)


def _select_call_from_subset(
    subset: pd.DataFrame,
    date: pd.Timestamp,
    equity: float,
    config: OptionBacktestConfig,
) -> Optional[pd.Series]:
    return _select_option_from_subset(subset, date, equity, config, "C")


def _select_option_from_subset(
    subset: pd.DataFrame,
    date: pd.Timestamp,
    equity: float,
    config: OptionBacktestConfig,
    option_type: str,
) -> Optional[pd.Series]:
    if subset.empty:
        return None
    option_type = option_type.upper()
    subset["dte"] = (subset["expiration"] - date).dt.days
    subset = subset[(subset["dte"] >= config.min_dte) & (subset["dte"] <= config.max_dte)]
    subset = subset[(subset["bid"] > 0.0) & (subset["ask"] > 0.0)]
    if config.min_contract_price > 0:
        subset = subset[subset["ask"] >= config.min_contract_price]
    subset = subset[subset["spread_pct"].fillna(999.0) <= config.max_spread_pct]
    if "open_interest" in subset.columns and subset["open_interest"].notna().any():
        subset = subset[subset["open_interest"].fillna(0) >= config.min_open_interest]
    if "volume" in subset.columns and subset["volume"].notna().any():
        subset = subset[subset["volume"].fillna(0) >= config.min_volume]
    if "delta" in subset.columns and subset["delta"].notna().any():
        subset["abs_delta"] = subset["delta"].abs()
        subset = subset[(subset["abs_delta"] >= config.min_delta) & (subset["abs_delta"] <= config.max_delta)]
        subset["score"] = (subset["abs_delta"] - config.target_delta).abs() + subset["spread_pct"].fillna(1.0)
    else:
        if "underlying_price" not in subset.columns:
            return None
        subset["moneyness"] = (subset["strike"] / subset["underlying_price"] - 1.0).abs()
        subset["score"] = subset["moneyness"] + subset["spread_pct"].fillna(1.0)
    if subset.empty:
        return None
    if (
        config.min_otm_pct is not None
        or config.max_otm_pct is not None
        or config.min_otm_pct_by_symbol
        or config.max_otm_pct_by_symbol
    ):
        symbol = str(subset["underlying_symbol"].iloc[0]).upper() if "underlying_symbol" in subset.columns else ""
        min_otm_pct = config.min_otm_pct
        max_otm_pct = config.max_otm_pct
        if config.min_otm_pct_by_symbol and symbol in config.min_otm_pct_by_symbol:
            min_otm_pct = config.min_otm_pct_by_symbol[symbol]
        if config.max_otm_pct_by_symbol and symbol in config.max_otm_pct_by_symbol:
            max_otm_pct = config.max_otm_pct_by_symbol[symbol]
        if "underlying_price" not in subset.columns:
            return None
        if option_type == "P":
            subset["otm_pct"] = 1.0 - subset["strike"] / subset["underlying_price"]
        else:
            subset["otm_pct"] = subset["strike"] / subset["underlying_price"] - 1.0
        if min_otm_pct is not None:
            subset = subset[subset["otm_pct"] >= min_otm_pct]
        if max_otm_pct is not None:
            subset = subset[subset["otm_pct"] <= max_otm_pct]
    subset["contract_cost"] = subset["ask"] * config.contract_multiplier
    premium_fraction = config.max_premium_fraction
    if option_type == "P" and config.put_max_premium_fraction is not None:
        premium_fraction = config.put_max_premium_fraction
    subset = subset[subset["contract_cost"] <= equity * premium_fraction]
    if subset.empty:
        return None
    return subset.sort_values(["score", "dte"]).iloc[0]


def quote_for_position(chain: pd.DataFrame, position: OptionPosition, date: pd.Timestamp) -> Optional[pd.Series]:
    subset = chain[(chain["quote_date"] == date) & (chain["contract_id"] == position.contract_id)]
    if subset.empty:
        return None
    return subset.iloc[0]


def _build_option_indexes(chain: pd.DataFrame) -> tuple[pd.DataFrame, Dict[tuple[pd.Timestamp, str], pd.DataFrame]]:
    quote_lookup = chain.set_index(["quote_date", "contract_id"], drop=False)
    call_groups: Dict[tuple[pd.Timestamp, str], pd.DataFrame] = {}
    calls = chain[chain["option_type"] == "C"]
    for (quote_date, symbol), frame in calls.groupby(["quote_date", "underlying_symbol"], sort=False):
        call_groups[(pd.Timestamp(quote_date), str(symbol).upper())] = frame
    return quote_lookup, call_groups


def _build_option_type_groups(chain: pd.DataFrame) -> Dict[tuple[pd.Timestamp, str, str], pd.DataFrame]:
    option_groups: Dict[tuple[pd.Timestamp, str, str], pd.DataFrame] = {}
    for (quote_date, symbol, option_type), frame in chain.groupby(
        ["quote_date", "underlying_symbol", "option_type"], sort=False
    ):
        option_groups[(pd.Timestamp(quote_date), str(symbol).upper(), str(option_type).upper())] = frame
    return option_groups


def _quote_for_position_lookup(
    quote_lookup: pd.DataFrame,
    position: OptionPosition,
    date: pd.Timestamp,
) -> Optional[pd.Series]:
    try:
        quote = quote_lookup.loc[(date, position.contract_id)]
    except KeyError:
        return None
    if isinstance(quote, pd.DataFrame):
        if quote.empty:
            return None
        return quote.iloc[0]
    return quote


def run_long_call_backtest(
    chain: pd.DataFrame,
    target_weights: pd.DataFrame,
    initial_cash: float,
    config: OptionBacktestConfig,
    prepared_indexes: Optional[tuple] = None,
) -> Dict[str, pd.DataFrame]:
    dates = sorted(set(target_weights.index).intersection(set(chain["quote_date"].unique())))
    if not dates:
        raise ValueError("No overlapping dates between target weights and option chain")
    if prepared_indexes:
        quote_lookup, call_groups = prepared_indexes[:2]
        option_type_groups = prepared_indexes[2] if config.allow_put_entries and len(prepared_indexes) > 2 else {}
    else:
        quote_lookup, call_groups = _build_option_indexes(chain)
        option_type_groups = {}
    if config.allow_put_entries and not option_type_groups:
        option_type_groups = _build_option_type_groups(chain)
    cash = float(initial_cash)
    positions: Dict[str, OptionPosition] = {}
    profit_lock_state: Dict[str, dict] = {}
    equity_rows = []
    order_rows = []
    events = []
    stopped_symbol_dates: Dict[str, pd.Timestamp] = {}
    current_month = pd.Timestamp(dates[0]).to_period("M")
    month_start_equity = cash
    monthly_stopped = False
    peak_equity = cash

    for idx, raw_date in enumerate(dates):
        date = pd.Timestamp(raw_date)
        next_date = pd.Timestamp(dates[idx + 1]) if idx + 1 < len(dates) else None
        is_last_trading_day_of_month = bool(next_date is not None and next_date.to_period("M") != date.to_period("M"))
        if date.to_period("M") != current_month:
            current_month = date.to_period("M")
            month_start_equity = cash + _mark_positions(quote_lookup, positions, date, config)
            monthly_stopped = False

        # Exit first using bid prices.
        for key, pos in list(positions.items()):
            quote = _quote_for_position_lookup(quote_lookup, pos, date)
            if quote is None:
                continue
            exit_price = float(quote["bid"])
            pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
            hold_days = (date - pos.entry_date).days
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
                5,
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
                if date in target_weights.index and pos.underlying_symbol in target_weights.columns:
                    current_weight = float(target_weights.loc[date, pos.underlying_symbol])
                if current_weight <= config.signal_loss_weight_threshold:
                    reason = "signal_loss"
            should_exit = bool(reason)
            if should_exit:
                proceeds = exit_price * config.contract_multiplier * pos.quantity
                cash += proceeds
                if reason in {"stop_loss", "signal_loss"}:
                    stopped_symbol_dates[pos.underlying_symbol] = date
                order_rows.append(
                    {
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

        marked_value = _mark_positions(quote_lookup, positions, date, config)
        equity = cash + marked_value
        peak_equity = max(peak_equity, equity)
        equity_drawdown = 1.0 - equity / peak_equity if peak_equity > 0 else 0.0
        month_return = equity / month_start_equity - 1.0 if month_start_equity > 0 else 0.0
        if not monthly_stopped and config.monthly_loss_stop > 0 and month_return <= -config.monthly_loss_stop:
            monthly_stopped = True
            events.append({"date": date, "event": "monthly_loss_stop", "month_return": month_return})
            if config.close_on_monthly_loss_stop:
                cash = _liquidate_positions(quote_lookup, positions, date, config, order_rows, "monthly_loss_stop", cash)
                marked_value = _mark_positions(quote_lookup, positions, date, config)
                equity = cash + marked_value
            elif config.close_losers_on_monthly_loss_stop:
                cash = _liquidate_positions(
                    quote_lookup,
                    positions,
                    date,
                    config,
                    order_rows,
                    "monthly_loss_stop_loser",
                    cash,
                    only_losers=True,
                )
                marked_value = _mark_positions(quote_lookup, positions, date, config)
                equity = cash + marked_value
        if not monthly_stopped and config.monthly_profit_lock > 0 and month_return >= config.monthly_profit_lock:
            monthly_stopped = True
            events.append({"date": date, "event": "monthly_profit_lock", "month_return": month_return})
            if config.close_on_monthly_profit_lock:
                cash = _liquidate_positions(quote_lookup, positions, date, config, order_rows, "monthly_profit_lock", cash)
                marked_value = _mark_positions(quote_lookup, positions, date, config)
                equity = cash + marked_value

        if config.close_before_month_end and is_last_trading_day_of_month and positions:
            cash = _liquidate_positions(quote_lookup, positions, date, config, order_rows, "month_end", cash)
            marked_value = _mark_positions(quote_lookup, positions, date, config)
            equity = cash + marked_value
            monthly_stopped = True
            events.append({"date": date, "event": "month_end_flatten", "month_return": month_return})

        marked_value = _mark_positions(quote_lookup, positions, date, config)
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

        effective_config = config
        risk_scale = 1.0
        risk_scale_reason = ""
        if (
            not entry_block_reason
            and config.low_equity_risk_scale_threshold > 0
            and equity < config.low_equity_risk_scale_threshold
            and config.low_equity_risk_scale < risk_scale
        ):
            risk_scale = max(0.0, float(config.low_equity_risk_scale))
            risk_scale_reason = "entry_low_equity_risk_scale"
        if (
            not entry_block_reason
            and config.drawdown_risk_scale_threshold > 0
            and equity_drawdown >= config.drawdown_risk_scale_threshold
            and config.drawdown_risk_scale < risk_scale
        ):
            risk_scale = max(0.0, float(config.drawdown_risk_scale))
            risk_scale_reason = "entry_drawdown_risk_scale"
        if not entry_block_reason and risk_scale < 1.0:
            effective_config = replace(
                config,
                max_premium_fraction=config.max_premium_fraction * risk_scale,
                max_total_premium_fraction=config.max_total_premium_fraction * risk_scale,
            )
            events.append(
                {
                    "date": date,
                    "event": risk_scale_reason,
                    "equity": equity,
                    "equity_drawdown": equity_drawdown,
                    "risk_scale": risk_scale,
                }
            )

        if entry_block_reason:
            events.append(
                {
                    "date": date,
                    "event": entry_block_reason,
                    "equity": equity,
                    "peak_equity": peak_equity,
                    "equity_drawdown": equity_drawdown,
                }
            )

        # Enter new calls for top target symbols if monthly and account-level risk are open.
        if not monthly_stopped and not entry_block_reason:
            weights = target_weights.loc[date]
            if config.allow_put_entries:
                weights = weights.reindex(weights.abs().sort_values(ascending=False).index)
            else:
                weights = weights.sort_values(ascending=False)
            gross_premium = sum(pos.entry_cost for pos in positions.values())
            for symbol, weight in weights.items():
                symbol = str(symbol).upper()
                signal_strength = abs(float(weight)) if config.allow_put_entries else float(weight)
                if (
                    signal_strength <= 0
                    or signal_strength < config.min_entry_weight
                    or symbol in [p.underlying_symbol for p in positions.values()]
                ):
                    continue
                option_type = "P" if config.allow_put_entries and float(weight) < 0 else "C"
                last_stop_date = stopped_symbol_dates.get(symbol)
                if (
                    config.stop_loss_cooldown_days > 0
                    and last_stop_date is not None
                    and (date - last_stop_date).days <= config.stop_loss_cooldown_days
                ):
                    continue
                equity = cash + _mark_positions(quote_lookup, positions, date, config)
                if gross_premium >= equity * effective_config.max_total_premium_fraction:
                    break
                if option_type == "P":
                    subset = option_type_groups.get((date, str(symbol).upper(), "P"))
                else:
                    subset = call_groups.get((date, str(symbol).upper()))
                if subset is None:
                    continue
                pick = _select_option_from_subset(subset.copy(), date, equity, effective_config, option_type)
                if pick is None:
                    continue
                contract_cost = float(pick["ask"]) * effective_config.contract_multiplier
                max_contracts_by_cash = int(cash // contract_cost)
                if max_contracts_by_cash <= 0:
                    continue
                premium_fraction = effective_config.max_premium_fraction
                if option_type == "P" and effective_config.put_max_premium_fraction is not None:
                    premium_fraction = effective_config.put_max_premium_fraction
                desired_premium = min(equity * signal_strength, equity * premium_fraction)
                remaining_total_budget = equity * effective_config.max_total_premium_fraction - gross_premium
                max_contracts_by_total = int(remaining_total_budget // contract_cost)
                if max_contracts_by_total <= 0:
                    continue
                max_contracts_by_config = (
                    effective_config.max_contracts_per_trade
                    if effective_config.max_contracts_per_trade > 0
                    else max_contracts_by_cash
                )
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
                if (
                    total_cost > cash
                    or gross_premium + total_cost > equity * effective_config.max_total_premium_fraction
                ):
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
                    entry_date=date,
                    entry_price=float(pick["ask"]),
                    entry_cost=total_cost,
                )
                positions[pos.contract_id] = pos
                profit_lock_state.pop(pos.contract_id, None)
                order_rows.append(
                    {
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

        marked_value = _mark_positions(quote_lookup, positions, date, config)
        equity = cash + marked_value
        equity_rows.append(
            {
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


def _mark_positions(
    quote_lookup: pd.DataFrame,
    positions: Dict[str, OptionPosition],
    date: pd.Timestamp,
    config: OptionBacktestConfig,
) -> float:
    value = 0.0
    for pos in positions.values():
        quote = _quote_for_position_lookup(quote_lookup, pos, date)
        if quote is None:
            continue
        mark = float(quote["bid"])
        value += mark * config.contract_multiplier * pos.quantity
    return value


def _liquidate_positions(
    quote_lookup: pd.DataFrame,
    positions: Dict[str, OptionPosition],
    date: pd.Timestamp,
    config: OptionBacktestConfig,
    order_rows: List[dict],
    reason: str,
    starting_cash: float,
    only_losers: bool = False,
) -> float:
    cash = starting_cash
    for key, pos in list(positions.items()):
        quote = _quote_for_position_lookup(quote_lookup, pos, date)
        if quote is None:
            continue
        exit_price = float(quote["bid"])
        pnl_pct = exit_price / pos.entry_price - 1.0 if pos.entry_price > 0 else 0.0
        if only_losers and pnl_pct >= 0:
            continue
        sale_value = exit_price * config.contract_multiplier * pos.quantity
        cash += sale_value
        order_rows.append(
            {
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
