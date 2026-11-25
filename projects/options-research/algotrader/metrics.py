from typing import Dict

import numpy as np
import pandas as pd


TRADING_DAYS = 252.0


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min())


def drawdown_series(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1.0 / 365.25)
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def annual_volatility(returns: pd.Series) -> float:
    return float(returns.std(ddof=0) * np.sqrt(TRADING_DAYS))


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    daily_rf = risk_free_rate / TRADING_DAYS
    excess = returns - daily_rf
    vol = excess.std(ddof=0)
    if vol <= 1e-12:
        return 0.0
    return float(excess.mean() / vol * np.sqrt(TRADING_DAYS))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    daily_rf = risk_free_rate / TRADING_DAYS
    excess = returns - daily_rf
    downside = excess[excess < 0.0].std(ddof=0)
    if downside <= 1e-12:
        return 0.0
    return float(excess.mean() / downside * np.sqrt(TRADING_DAYS))


def value_at_risk(returns: pd.Series, level: float = 0.95) -> float:
    return float(np.quantile(returns.dropna(), 1.0 - level))


def conditional_value_at_risk(returns: pd.Series, level: float = 0.95) -> float:
    clean = returns.dropna()
    threshold = np.quantile(clean, 1.0 - level)
    tail = clean[clean <= threshold]
    return float(tail.mean()) if len(tail) else float(threshold)


def summarize_performance(
    equity: pd.Series,
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    average_turnover: float = 0.0,
) -> Dict[str, float]:
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) else 0.0
    mdd = max_drawdown(equity)
    ann_return = cagr(equity)
    ann_vol = annual_volatility(returns)
    return {
        "start_equity": float(equity.iloc[0]),
        "final_equity": float(equity.iloc[-1]),
        "total_return": total_return,
        "cagr": ann_return,
        "annual_volatility": ann_vol,
        "sharpe": sharpe_ratio(returns, risk_free_rate),
        "sortino": sortino_ratio(returns, risk_free_rate),
        "max_drawdown": mdd,
        "calmar": float(ann_return / abs(mdd)) if abs(mdd) > 1e-12 else 0.0,
        "hit_rate": float((returns > 0.0).mean()),
        "best_day": float(returns.max()),
        "worst_day": float(returns.min()),
        "var_95": value_at_risk(returns, 0.95),
        "cvar_95": conditional_value_at_risk(returns, 0.95),
        "average_daily_turnover": float(average_turnover),
    }


def by_calendar_year(equity: pd.Series) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame()
    yearly = equity.resample("YE").last()
    yearly = pd.concat([pd.Series([equity.iloc[0]], index=[equity.index[0]]), yearly])
    rows = []
    for i in range(1, len(yearly)):
        start = yearly.index[i - 1]
        end = yearly.index[i]
        rows.append(
            {
                "Year": int(end.year),
                "Start": float(yearly.iloc[i - 1]),
                "End": float(yearly.iloc[i]),
                "Return": float(yearly.iloc[i] / yearly.iloc[i - 1] - 1.0),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_projection(
    returns: pd.Series,
    initial_cash: float,
    horizon_days: int = 252,
    paths: int = 2000,
    seed: int = 42,
) -> Dict[str, float]:
    clean = returns.dropna().values
    clean = clean[np.isfinite(clean)]
    if len(clean) < 30:
        return {"p05": initial_cash, "median": initial_cash, "p95": initial_cash}
    rng = np.random.default_rng(seed)
    samples = rng.choice(clean, size=(paths, horizon_days), replace=True)
    terminal = initial_cash * np.prod(1.0 + samples, axis=1)
    return {
        "p05": float(np.quantile(terminal, 0.05)),
        "median": float(np.quantile(terminal, 0.50)),
        "p95": float(np.quantile(terminal, 0.95)),
    }

