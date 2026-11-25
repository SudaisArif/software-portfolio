import os
from datetime import datetime
from typing import Dict

import pandas as pd

from .backtest import BacktestResult
from .config import ModelConfig, ResearchConfig, StrategyConfig
from .metrics import bootstrap_projection, by_calendar_year, drawdown_series, summarize_performance


def _pct(value: float) -> str:
    return f"{value * 100.0:,.2f}%"


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No data._"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---" for _ in columns]) + " |",
    ]
    for _, row in frame.iterrows():
        values = []
        for col in columns:
            value = row[col]
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _polyline(series: pd.Series, width: int, top: int, height: int) -> str:
    clean = series.dropna()
    if clean.empty:
        return ""
    values = clean.astype(float).values
    lo = float(values.min())
    hi = float(values.max())
    span = hi - lo if hi > lo else 1.0
    points = []
    denom = max(len(values) - 1, 1)
    for idx, value in enumerate(values):
        x = 50 + idx / denom * (width - 80)
        y = top + height - ((float(value) - lo) / span * height)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def save_equity_svg(result: BacktestResult, path: str) -> None:
    width = 1000
    height = 620
    strategy = _polyline(result.equity_curve, width, 50, 280)
    benchmark = _polyline(result.benchmark_equity, width, 50, 280)
    drawdown = _polyline(drawdown_series(result.equity_curve), width, 400, 150)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <text x="50" y="30" font-family="Arial" font-size="20" fill="#222">Equity Curve</text>
  <line x1="50" y1="330" x2="970" y2="330" stroke="#ddd"/>
  <polyline fill="none" stroke="#1f77b4" stroke-width="3" points="{strategy}"/>
  <polyline fill="none" stroke="#777" stroke-width="2" points="{benchmark}"/>
  <text x="760" y="30" font-family="Arial" font-size="13" fill="#1f77b4">Strategy</text>
  <text x="840" y="30" font-family="Arial" font-size="13" fill="#777">SPY buy/hold</text>
  <text x="50" y="380" font-family="Arial" font-size="20" fill="#222">Strategy Drawdown</text>
  <line x1="50" y1="550" x2="970" y2="550" stroke="#ddd"/>
  <polyline fill="none" stroke="#b22222" stroke-width="2" points="{drawdown}"/>
</svg>
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)


def save_equity_plot(result: BacktestResult, path: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - depends on local GUI/image stack
        fallback = os.path.splitext(path)[0] + ".svg"
        save_equity_svg(result, fallback)
        note = os.path.splitext(path)[0] + "_plot_unavailable.txt"
        with open(note, "w", encoding="utf-8") as handle:
            handle.write(f"PNG generation unavailable, wrote SVG fallback: {fallback}\nReason: {exc}\n")
        return

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    result.equity_curve.plot(ax=axes[0], label="Strategy", linewidth=2)
    result.benchmark_equity.plot(ax=axes[0], label="SPY buy-and-hold", linewidth=1.5, alpha=0.8)
    axes[0].set_title("Equity Curve")
    axes[0].set_ylabel("Account Value")
    axes[0].legend()
    drawdown_series(result.equity_curve).plot(ax=axes[1], color="firebrick", label="Strategy drawdown")
    axes[1].set_title("Drawdown")
    axes[1].set_ylabel("Drawdown")
    axes[1].set_xlabel("")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_summary_report(
    result: BacktestResult,
    research_config: ResearchConfig,
    model_config: ModelConfig,
    strategy_config: StrategyConfig,
    output_path: str,
) -> Dict[str, float]:
    average_turnover = float(result.weights.diff().abs().sum(axis=1).mean())
    metrics = summarize_performance(
        result.equity_curve,
        result.daily_returns,
        research_config.risk_free_rate,
        average_turnover=average_turnover,
    )
    average_gross = float(result.weights.abs().sum(axis=1).mean())
    peak_gross = float(result.weights.abs().sum(axis=1).max())
    benchmark_metrics = summarize_performance(
        result.benchmark_equity,
        result.benchmark_returns,
        research_config.risk_free_rate,
        average_turnover=0.0,
    )
    projection = bootstrap_projection(
        result.daily_returns.loc[result.daily_returns.index >= result.daily_returns.index.max() - pd.Timedelta(days=365 * 4)],
        research_config.initial_cash,
    )
    yearly = by_calendar_year(result.equity_curve)
    yearly_md = _markdown_table(yearly) if not yearly.empty else "_No yearly data._"

    events_md = _markdown_table(result.events) if not result.events.empty else "_No drawdown cooldown events triggered._"

    lines = [
        "# Latest Algorithmic Trading Research Report",
        "",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "## Research Warning",
        "",
        "This is a historical simulation for research and paper trading. It is not financial advice, and it does not guarantee future returns. Free data can contain survivorship, adjustment, latency, and quote-quality issues. Options trading can lose money quickly because leverage magnifies both gains and losses.",
        "",
        "## Strategy Snapshot",
        "",
        f"- Starting cash: {_money(research_config.initial_cash)}",
        f"- Universe: {', '.join(research_config.tickers)}",
        f"- Benchmark: {research_config.benchmark}",
        f"- Daily model: rolling L2-regularized linear classifier with logistic probability scoring, retrained every {model_config.retrain_every_days} trading days",
        f"- Risk profile: max {strategy_config.max_positions} positions, {strategy_config.max_position_weight:.0%} max per name, {strategy_config.max_gross_exposure:.0%} max gross exposure",
        f"- Realized target exposure: {average_gross:.0%} average gross, {peak_gross:.0%} peak gross",
        f"- Risk-off: gross exposure scales to {strategy_config.risk_off_gross_exposure:.0%} when SPY is below its long trend or VIX is high",
        f"- Monthly guard: loss stop {strategy_config.monthly_loss_stop:.0%}, profit lock {strategy_config.monthly_profit_lock:.0%}",
        f"- Cost model: {strategy_config.transaction_cost_bps:.1f} bps per unit of turnover",
        "",
        "## Core Results",
        "",
        "| Metric | Strategy | SPY Buy/Hold |",
        "|---|---:|---:|",
        f"| Final equity | {_money(metrics['final_equity'])} | {_money(benchmark_metrics['final_equity'])} |",
        f"| Total return | {_pct(metrics['total_return'])} | {_pct(benchmark_metrics['total_return'])} |",
        f"| CAGR | {_pct(metrics['cagr'])} | {_pct(benchmark_metrics['cagr'])} |",
        f"| Annual volatility | {_pct(metrics['annual_volatility'])} | {_pct(benchmark_metrics['annual_volatility'])} |",
        f"| Sharpe | {metrics['sharpe']:.2f} | {benchmark_metrics['sharpe']:.2f} |",
        f"| Sortino | {metrics['sortino']:.2f} | {benchmark_metrics['sortino']:.2f} |",
        f"| Max drawdown | {_pct(metrics['max_drawdown'])} | {_pct(benchmark_metrics['max_drawdown'])} |",
        f"| Worst day | {_pct(metrics['worst_day'])} | {_pct(benchmark_metrics['worst_day'])} |",
        f"| 95% daily CVaR | {_pct(metrics['cvar_95'])} | {_pct(benchmark_metrics['cvar_95'])} |",
        "",
        "## One-Year Bootstrap Projection",
        "",
        "This resamples recent strategy daily returns. It is a scenario distribution, not a forecast promise.",
        "",
        f"- 5th percentile: {_money(projection['p05'])}",
        f"- Median: {_money(projection['median'])}",
        f"- 95th percentile: {_money(projection['p95'])}",
        "",
        "## Calendar-Year Strategy Returns",
        "",
        yearly_md,
        "",
        "## Risk Events",
        "",
        events_md,
        "",
        "## Model Notes",
        "",
        "- The model scores next-day positive-return probability using only lagged daily features available at the rebalance date.",
        "- Hyperparameters are fixed in code rather than selected by chasing the best backtest.",
        "- The factor blend is deliberately simple: momentum, trend, volume confirmation, overbought penalty, and market regime.",
        "- The options module provides Black-Scholes pricing and Greeks. Historical options P&L should only be trusted once real historical option quotes are supplied.",
        "",
        "## Live/Paper Trading Path",
        "",
        "Use `reports/latest_allocations.csv` for target weights. For live trading, connect the same signal logic to a paper brokerage first. The safest production path is to port the algorithm to QuantConnect LEAN or a broker API such as Interactive Brokers, Alpaca, or Tradier, then run it in paper mode for several weeks before any real capital.",
        "",
    ]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return metrics
