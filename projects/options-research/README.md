# Options Trading Research System

This repository is a local research scaffold for daily systematic equities and options research. It is built for education, paper trading, and repeatable backtesting, not as financial advice or a profit guarantee.

## What It Does

- Downloads no-key historical market data with `yfinance`.
- Builds daily technical, volatility, volume, and market-regime features.
- Trains a rolling regularized ML classifier only on past data.
- Combines ML probability with fixed factor signals.
- Runs a riskier-but-bounded long-only daily strategy from a starting balance such as `$1,000`.
- Prices option contracts and Greeks with Black-Scholes utilities.
- Can ingest Databento OPRA historical option quotes for real bid/ask chain backtests.
- Writes markdown reports, metrics CSVs, allocation CSVs, and equity-curve charts.

## Quick Start

```bash
python3 scripts/run_research.py --initial-cash 1000 --start 2016-01-01
```

The default profile is moderately aggressive: it holds up to three names, caps each at 35%, and can target more than 100% gross exposure in research. Use `--max-gross 1.0` for a cash-account style backtest.

Aggressive research example:

```bash
python3 scripts/run_research.py --initial-cash 1000 --start 2016-01-01 --max-positions 3 --max-position-weight 0.70 --max-gross 2.0 --risk-off-gross 0.5 --drawdown-stop 0.40
```

Run the smoke tests:

```bash
python3 -m unittest discover -s tests
```

For sharing this project with a collaborator, see `docs/SHARING_WITH_FRIEND.md`.
Keep real API keys in a local `.env` file created from `.env.example`; `.env` is intentionally ignored by git.

Databento OPRA real-chain smoke test:

```bash
export DATABENTO_API_KEY="..."
python3 scripts/fetch_databento_opra_chain.py --symbol NVDA --date 2026-04-24 --max-cost 1.00
python3 scripts/fetch_databento_opra_chain.py --symbol NVDA --date 2026-04-24 --max-cost 1.00 --fetch
python3 scripts/run_real_options_backtest.py --chains data/options/databento --weights artifacts/synthetic_optionlike_5x/latest_weights.csv --initial-cash 1000 --start 2026-04-24 --end 2026-04-24
```

Outputs are written to:

- `reports/latest_summary.md`
- `reports/latest_metrics.csv`
- `reports/latest_equity_curve.csv`
- `reports/latest_allocations.csv`
- `reports/latest_equity_curve.png`
- `reports/latest_equity_curve.svg` if PNG rendering is unavailable locally

QuantConnect export notes and a LEAN template are in `exports/quantconnect/`.

## Important Limits

Free historical equity data is suitable for research, but it is not institutional-grade. Historical option-chain data usually requires a paid data source, so option backtests here are intentionally kept synthetic unless you provide real option quotes. Use paper trading before any live use.

Options are leveraged and complex. A small account can lose money quickly, especially with short-dated contracts. This system defaults to bounded equity exposure and no naked short options.
