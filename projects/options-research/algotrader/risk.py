"""Shared option-position risk rules."""
from dataclasses import dataclass
from math import isfinite
from typing import Optional, Tuple


@dataclass(frozen=True)
class ProfitLockConfig:
    """Stateful rule that protects large option gains without instant selling."""

    activation: float = 2.00
    floor: float = 2.00
    trail: float = 0.15


def clean_pnl(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def update_profit_lock_state(
    pnl_pct: Optional[float],
    was_armed: bool = False,
    previous_max_pnl_pct: Optional[float] = None,
    config: ProfitLockConfig = ProfitLockConfig(),
) -> Tuple[bool, Optional[float]]:
    """Return updated ``(armed, max_pnl_pct)`` for a position.

    The rule arms only after a position has reached the activation profit. Once
    armed, later checks can exit if profit falls through the floor or trails too
    far from the best observed profit.
    """

    pnl = clean_pnl(pnl_pct)
    previous_max = clean_pnl(previous_max_pnl_pct)
    if pnl is None:
        return was_armed, previous_max

    max_pnl = pnl if previous_max is None else max(previous_max, pnl)
    armed = bool(was_armed) or pnl >= config.activation or (
        previous_max is not None and previous_max >= config.activation
    )
    return armed, max_pnl


def profit_lock_exit_reason(
    pnl_pct: Optional[float],
    armed: bool,
    max_pnl_pct: Optional[float],
    config: ProfitLockConfig = ProfitLockConfig(),
) -> str:
    """Return the profit-lock exit reason, or an empty string if no exit."""

    pnl = clean_pnl(pnl_pct)
    max_pnl = clean_pnl(max_pnl_pct)
    if not armed or pnl is None:
        return ""
    if pnl < config.floor:
        return "profit_lock_floor"
    if max_pnl is not None and max_pnl - pnl >= config.trail:
        return "profit_lock_trail"
    return ""


def option_exit_reason(
    pnl_pct: Optional[float],
    hold_days: int,
    dte: int,
    stop_loss: float,
    take_profit: float,
    max_hold_days: int,
    expiration_exit_days: int,
    profit_lock_armed: bool = False,
    max_pnl_pct: Optional[float] = None,
    profit_lock_config: ProfitLockConfig = ProfitLockConfig(),
) -> str:
    """Evaluate the ordered exit rules for one long option position."""

    pnl = clean_pnl(pnl_pct)
    if pnl is not None and pnl <= -stop_loss:
        return "stop_loss"
    if pnl is not None and pnl >= take_profit:
        return "take_profit"
    profit_lock_reason = profit_lock_exit_reason(
        pnl, profit_lock_armed, max_pnl_pct, profit_lock_config
    )
    if profit_lock_reason:
        return profit_lock_reason
    if hold_days >= max_hold_days:
        return "max_hold"
    if dte <= expiration_exit_days:
        return "expiration"
    return ""
