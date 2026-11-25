#!/usr/bin/env python3
import argparse
import os
import sys
import warnings
from datetime import date

import pandas as pd

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from algotrader.backtest import run_backtest
from algotrader.config import ModelConfig, ResearchConfig, StrategyConfig
from algotrader.data import close_matrix, download_prices
from algotrader.features import build_feature_panel
from algotrader.reports import save_equity_plot, write_summary_report
from algotrader.strategy import build_strategy, construct_target_weights, latest_allocation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily equity/options research backtest.")
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="")
    parser.add_argument("--tickers", default="")
    parser.add_argument("--refresh-data", action="store_true")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--max-positions", type=int, default=3)
    parser.add_argument("--max-position-weight", type=float, default=0.35)
    parser.add_argument("--max-gross", type=float, default=1.25)
    parser.add_argument("--risk-off-gross", type=float, default=0.25)
    parser.add_argument("--drawdown-stop", type=float, default=0.25)
    parser.add_argument("--cooldown-days", type=int, default=21)
    parser.add_argument("--monthly-loss-stop", type=float, default=0.0)
    parser.add_argument("--monthly-profit-lock", type=float, default=0.0)
    parser.add_argument("--transaction-cost-bps", type=float, default=8.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    research_config = ResearchConfig(
        initial_cash=args.initial_cash,
        start=args.start,
        end=args.end or date.today().isoformat(),
        cache_dir=args.cache_dir,
        report_dir=args.report_dir,
        refresh_data=args.refresh_data,
        tickers=tickers or ResearchConfig().tickers,
    )
    model_config = ModelConfig()
    strategy_config = StrategyConfig(
        max_positions=args.max_positions,
        max_position_weight=args.max_position_weight,
        max_gross_exposure=args.max_gross,
        risk_off_gross_exposure=args.risk_off_gross,
        drawdown_stop=args.drawdown_stop,
        cooldown_days=args.cooldown_days,
        monthly_loss_stop=args.monthly_loss_stop,
        monthly_profit_lock=args.monthly_profit_lock,
        transaction_cost_bps=args.transaction_cost_bps,
    )

    symbols_to_download = list(dict.fromkeys(research_config.tickers + [research_config.market_ticker, research_config.vix_ticker]))
    prices = download_prices(
        symbols_to_download,
        research_config.start,
        research_config.end,
        research_config.cache_dir,
        refresh=research_config.refresh_data,
    )
    closes = close_matrix({symbol: prices[symbol] for symbol in symbols_to_download if symbol in prices})
    panel = build_feature_panel(
        prices,
        research_config.tickers,
        research_config.market_ticker,
        research_config.vix_ticker,
    )
    scored = build_strategy(panel, model_config, strategy_config)
    weights = construct_target_weights(scored, strategy_config)
    result = run_backtest(
        closes,
        weights,
        research_config.initial_cash,
        strategy_config,
        benchmark_symbol=research_config.benchmark,
    )

    os.makedirs(research_config.report_dir, exist_ok=True)
    equity_path = os.path.join(research_config.report_dir, "latest_equity_curve.csv")
    metrics_path = os.path.join(research_config.report_dir, "latest_metrics.csv")
    weights_path = os.path.join(research_config.report_dir, "latest_weights.csv")
    allocation_path = os.path.join(research_config.report_dir, "latest_allocations.csv")
    chart_path = os.path.join(research_config.report_dir, "latest_equity_curve.png")
    summary_path = os.path.join(research_config.report_dir, "latest_summary.md")

    pd.DataFrame(
        {
            "StrategyEquity": result.equity_curve,
            "StrategyReturn": result.daily_returns,
            "BenchmarkEquity": result.benchmark_equity,
            "BenchmarkReturn": result.benchmark_returns,
            "EstimatedCostDollars": result.costs,
        }
    ).to_csv(equity_path, index_label="Date")
    weights.to_csv(weights_path, index_label="Date")
    allocation = latest_allocation(weights, closes, research_config.initial_cash)
    allocation.to_csv(allocation_path, index=False)
    save_equity_plot(result, chart_path)
    metrics = write_summary_report(result, research_config, model_config, strategy_config, summary_path)
    pd.DataFrame([metrics]).to_csv(metrics_path, index=False)

    print("Backtest complete")
    print(f"Summary: {summary_path}")
    print(f"Final equity: ${metrics['final_equity']:.2f}")
    print(f"Total return: {metrics['total_return'] * 100:.2f}%")
    print(f"Sharpe: {metrics['sharpe']:.2f}")
    print(f"Max drawdown: {metrics['max_drawdown'] * 100:.2f}%")


if __name__ == "__main__":
    main()
