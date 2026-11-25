#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.option_chain import OptionBacktestConfig, load_option_chains, run_long_call_backtest


def parse_args():
    parser = argparse.ArgumentParser(description="Sweep targeted real-options risk controls.")
    parser.add_argument("--chains", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--output-dir", default="artifacts/option_risk_control_sweep")
    return parser.parse_args()


def monthly_breakdown(equity, start, initial_cash):
    monthly = equity.assign(date=pd.to_datetime(equity["date"])).set_index("date")["equity"].resample("ME").last()
    monthly = pd.concat([pd.Series([initial_cash], index=[pd.Timestamp(start)]), monthly]).dropna()
    return pd.DataFrame(
        {
            "equity": monthly,
            "monthly_profit": monthly.diff(),
            "monthly_return": monthly.pct_change(),
        }
    ).dropna()


def max_drawdown(equity):
    curve = equity["equity"]
    return float((curve / curve.cummax() - 1.0).min())


def build_variants():
    base = {
        "monthly_loss_stop": 0.10,
        "monthly_profit_lock": 0.50,
        "max_premium_fraction": 0.15,
        "max_total_premium_fraction": 0.45,
        "stop_loss": 0.45,
        "take_profit": 1.25,
        "max_hold_days": 7,
    }
    variants = {
        "baseline_budget15_stop10": {},
        "max_otm_06": {"max_otm_pct": 0.06},
        "max_otm_06_min_price_1": {"max_otm_pct": 0.06, "min_contract_price": 1.0},
        "max_otm_06_min_weight_075": {"max_otm_pct": 0.06, "min_entry_weight": 0.75},
        "max_otm_06_contract_cap6": {"max_otm_pct": 0.06, "max_contracts_per_trade": 6},
        "max_otm_06_close_losers": {"max_otm_pct": 0.06, "close_losers_on_monthly_loss_stop": True},
        "max_otm_06_signal_exit": {"max_otm_pct": 0.06, "exit_losing_on_signal_loss": True},
        "min_weight_075_only": {"min_entry_weight": 0.75},
        "max_otm_06_min_weight_075_close_losers": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "close_losers_on_monthly_loss_stop": True,
        },
        "max_otm_06_min_weight_075_min_price_1": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "min_contract_price": 1.0,
        },
        "max_otm_06_min_weight_075_min_price_1_close_losers": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "min_contract_price": 1.0,
            "close_losers_on_monthly_loss_stop": True,
        },
        "best_cooldown_3": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "min_contract_price": 1.0,
            "close_losers_on_monthly_loss_stop": True,
            "stop_loss_cooldown_days": 3,
        },
        "best_cooldown_5": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "min_contract_price": 1.0,
            "close_losers_on_monthly_loss_stop": True,
            "stop_loss_cooldown_days": 5,
        },
        "best_cooldown_7": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "min_contract_price": 1.0,
            "close_losers_on_monthly_loss_stop": True,
            "stop_loss_cooldown_days": 7,
        },
        "best_cooldown_10": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "min_contract_price": 1.0,
            "close_losers_on_monthly_loss_stop": True,
            "stop_loss_cooldown_days": 10,
        },
        "max_otm_06_min_weight_075_min_price_1_contract_cap3": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "min_contract_price": 1.0,
            "max_contracts_per_trade": 3,
        },
        "max_otm_06_min_weight_075_contract_cap3": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "max_contracts_per_trade": 3,
        },
        "max_otm_06_min_weight_075_budget12": {
            **base,
            "max_premium_fraction": 0.12,
            "max_total_premium_fraction": 0.36,
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
        },
        "max_otm_06_min_weight_075_month08": {
            **base,
            "monthly_loss_stop": 0.08,
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
        },
        "max_otm_06_min_weight_075_stop35": {
            "max_otm_pct": 0.06,
            "min_entry_weight": 0.75,
            "stop_loss": 0.35,
        },
        "combined_loss_filter": {
            "max_otm_pct": 0.06,
            "min_contract_price": 1.0,
            "max_contracts_per_trade": 6,
            "close_losers_on_monthly_loss_stop": True,
            "exit_losing_on_signal_loss": True,
        },
    }
    return {name: OptionBacktestConfig(**{**base, **overrides}) for name, overrides in variants.items()}


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chain = load_option_chains(args.chains)
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    weights = weights.loc[(weights.index >= start) & (weights.index <= end)]

    summary_rows = []
    for name, config in build_variants().items():
        result = run_long_call_backtest(chain, weights, args.initial_cash, config)
        variant_dir = output_dir / name
        variant_dir.mkdir(parents=True, exist_ok=True)
        for result_name, frame in result.items():
            frame.to_csv(variant_dir / f"{result_name}.csv", index=False)
        monthly = monthly_breakdown(result["equity"], start, args.initial_cash)
        monthly.to_csv(variant_dir / "monthly.csv", index_label="date")
        final = float(result["equity"]["equity"].iloc[-1])
        summary_rows.append(
            {
                "variant": name,
                "final_equity": final,
                "total_return": final / args.initial_cash - 1.0,
                "max_drawdown": max_drawdown(result["equity"]),
                "orders": len(result["orders"]),
                "losing_months": int((monthly["monthly_profit"] < 0).sum()),
                "worst_month": float(monthly["monthly_profit"].min()),
                "best_month": float(monthly["monthly_profit"].max()),
            }
        )
        print(
            f"{name}: final=${final:,.0f}, "
            f"loss_months={(monthly['monthly_profit'] < 0).sum()}, "
            f"worst=${monthly['monthly_profit'].min():,.0f}, "
            f"dd={max_drawdown(result['equity']) * 100:,.2f}%"
        )

    summary = pd.DataFrame(summary_rows).sort_values(["losing_months", "final_equity"], ascending=[True, False])
    summary.to_csv(output_dir / "summary.csv", index=False)
    print(f"Summary: {output_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
