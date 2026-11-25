from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from .config import StrategyConfig


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    daily_returns: pd.Series
    weights: pd.DataFrame
    costs: pd.Series
    benchmark_equity: pd.Series
    benchmark_returns: pd.Series
    events: pd.DataFrame


def _drift_weights(weights: pd.Series, asset_returns: pd.Series, portfolio_return: float) -> pd.Series:
    if 1.0 + portfolio_return <= 1e-12:
        return weights * 0.0
    drifted = weights * (1.0 + asset_returns.fillna(0.0)) / (1.0 + portfolio_return)
    return drifted.fillna(0.0)


def run_backtest(
    close_prices: pd.DataFrame,
    target_weights: pd.DataFrame,
    initial_cash: float,
    config: StrategyConfig,
    benchmark_symbol: str = "SPY",
) -> BacktestResult:
    close = close_prices[target_weights.columns].reindex(target_weights.index).ffill()
    returns = close.pct_change().fillna(0.0)
    weights = target_weights.reindex(close.index).fillna(0.0)
    cost_rate = config.transaction_cost_bps / 10000.0

    dates = close.index
    equity = pd.Series(index=dates, dtype=float)
    strategy_returns = pd.Series(index=dates, dtype=float)
    costs = pd.Series(0.0, index=dates, dtype=float)
    events = []

    current_equity = float(initial_cash)
    equity.iloc[0] = current_equity
    strategy_returns.iloc[0] = 0.0
    prev_weights = pd.Series(0.0, index=weights.columns)
    peak_equity = current_equity
    cooldown_remaining = 0
    month_start_equity = current_equity
    current_month = dates[0].to_period("M")
    monthly_stopped = False

    for i in range(1, len(dates)):
        prev_date = dates[i - 1]
        date = dates[i]
        date_month = date.to_period("M")
        if date_month != current_month:
            current_month = date_month
            month_start_equity = current_equity
            monthly_stopped = False

        desired = weights.loc[prev_date].copy()
        if cooldown_remaining > 0 or monthly_stopped:
            desired *= 0.0
        if cooldown_remaining > 0:
            cooldown_remaining -= 1

        turnover = float((desired - prev_weights).abs().sum())
        cost = turnover * cost_rate
        costs.loc[date] = cost * current_equity
        current_equity *= max(0.0, 1.0 - cost)

        asset_ret = returns.loc[date].fillna(0.0)
        gross_ret = float((desired * asset_ret).sum())
        current_equity *= 1.0 + gross_ret
        strategy_returns.loc[date] = gross_ret - cost
        equity.loc[date] = current_equity

        peak_equity = max(peak_equity, current_equity)
        drawdown = current_equity / peak_equity - 1.0
        if drawdown <= -config.drawdown_stop and cooldown_remaining <= 0:
            cooldown_remaining = config.cooldown_days
            peak_equity = current_equity
            events.append(
                {
                    "Date": date,
                    "Event": "drawdown_cooldown",
                    "Drawdown": drawdown,
                    "CooldownDays": config.cooldown_days,
                }
            )

        month_return = current_equity / month_start_equity - 1.0 if month_start_equity > 0.0 else 0.0
        if (
            config.monthly_loss_stop > 0.0
            and month_return <= -config.monthly_loss_stop
            and not monthly_stopped
        ):
            monthly_stopped = True
            events.append(
                {
                    "Date": date,
                    "Event": "monthly_loss_stop",
                    "Drawdown": month_return,
                    "CooldownDays": 0,
                }
            )
        if (
            config.monthly_profit_lock > 0.0
            and month_return >= config.monthly_profit_lock
            and not monthly_stopped
        ):
            monthly_stopped = True
            events.append(
                {
                    "Date": date,
                    "Event": "monthly_profit_lock",
                    "Drawdown": month_return,
                    "CooldownDays": 0,
                }
            )

        prev_weights = _drift_weights(desired, asset_ret, gross_ret)

    benchmark_close = close_prices[benchmark_symbol].reindex(dates).ffill()
    benchmark_returns = benchmark_close.pct_change().fillna(0.0)
    benchmark_equity = initial_cash * (1.0 + benchmark_returns).cumprod()
    return BacktestResult(
        equity_curve=equity.dropna(),
        daily_returns=strategy_returns.reindex(equity.dropna().index).fillna(0.0),
        weights=weights,
        costs=costs.reindex(equity.dropna().index).fillna(0.0),
        benchmark_equity=benchmark_equity.reindex(equity.dropna().index).ffill(),
        benchmark_returns=benchmark_returns.reindex(equity.dropna().index).fillna(0.0),
        events=pd.DataFrame(events),
    )
