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
    parser = argparse.ArgumentParser(description="Focused sweep from refined-best loss diagnostics.")
    parser.add_argument("--chains", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--output-dir", default="artifacts/option_loss_autopsy_sweep")
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


def drawdown(equity):
    curve = equity["equity"]
    return float((curve / curve.cummax() - 1.0).min())


def make_weights(base_weights, exclude_symbols):
    weights = base_weights.copy()
    for symbol in exclude_symbols:
        if symbol in weights.columns:
            weights[symbol] = 0.0
    return weights


def base_config():
    return {
        "monthly_loss_stop": 0.10,
        "monthly_profit_lock": 0.50,
        "max_premium_fraction": 0.15,
        "max_total_premium_fraction": 0.45,
        "max_otm_pct": 0.06,
        "min_entry_weight": 0.75,
        "min_contract_price": 1.0,
        "close_losers_on_monthly_loss_stop": True,
        "stop_loss": 0.45,
        "take_profit": 1.25,
        "max_hold_days": 7,
    }


def variants():
    base = base_config()
    return {
        "refined_best": ({}, []),
        "cooldown_1": ({"stop_loss_cooldown_days": 1}, []),
        "cooldown_2": ({"stop_loss_cooldown_days": 2}, []),
        "max_dte_35": ({"max_dte": 35}, []),
        "max_dte_30": ({"max_dte": 30}, []),
        "max_spread_06": ({"max_spread_pct": 0.06}, []),
        "max_spread_04": ({"max_spread_pct": 0.04}, []),
        "contract_cap_8": ({"max_contracts_per_trade": 8}, []),
        "contract_cap_10": ({"max_contracts_per_trade": 10}, []),
        "contract_cap_12": ({"max_contracts_per_trade": 12}, []),
        "min_otm_0": ({"min_otm_pct": 0.0}, []),
        "min_otm_neg_005": ({"min_otm_pct": -0.005}, []),
        "otm_0_to_04": ({"min_otm_pct": 0.0, "max_otm_pct": 0.04}, []),
        "otm_neg_005_to_04": ({"min_otm_pct": -0.005, "max_otm_pct": 0.04}, []),
        "exclude_net_negative_symbols": ({}, ["XLV", "TLT", "XLF", "META", "DIA"]),
        "exclude_worst_three": ({}, ["XLV", "TLT", "XLF"]),
        "exclude_low_sample_losers": ({}, ["XLV", "META", "DIA"]),
        "exclude_xlv_only": ({}, ["XLV"]),
        "exclude_tlt_xlf_xlv_cap_10": ({"max_contracts_per_trade": 10}, ["XLV", "TLT", "XLF"]),
        "exclude_negative_min_otm_neg_005": ({"min_otm_pct": -0.005}, ["XLV", "TLT", "XLF", "META", "DIA"]),
        "exclude_negative_cap_10": ({"max_contracts_per_trade": 10}, ["XLV", "TLT", "XLF", "META", "DIA"]),
        "exclude_negative_cooldown_1": ({"stop_loss_cooldown_days": 1}, ["XLV", "TLT", "XLF", "META", "DIA"]),
        "exclude_negative_max_spread_06": ({"max_spread_pct": 0.06}, ["XLV", "TLT", "XLF", "META", "DIA"]),
        "min_otm_0_exclude_negative": ({"min_otm_pct": 0.0}, ["XLV", "TLT", "XLF", "META", "DIA"]),
        "min_otm_0_exclude_low_sample": ({"min_otm_pct": 0.0}, ["XLV", "META", "DIA"]),
        "min_otm_0_contract_cap_10": ({"min_otm_pct": 0.0, "max_contracts_per_trade": 10}, []),
        "min_otm_0_max_dte_30": ({"min_otm_pct": 0.0, "max_dte": 30}, []),
        "min_otm_0_max_dte_35": ({"min_otm_pct": 0.0, "max_dte": 35}, []),
        "profit_lock_075": ({"monthly_profit_lock": 0.75}, []),
        "profit_lock_100": ({"monthly_profit_lock": 1.00}, []),
        "profit_lock_off": ({"monthly_profit_lock": 0.0}, []),
        "monthly_loss_08": ({"monthly_loss_stop": 0.08}, []),
        "monthly_loss_12": ({"monthly_loss_stop": 0.12}, []),
        "monthly_loss_15": ({"monthly_loss_stop": 0.15}, []),
        "take_profit_150": ({"take_profit": 1.50}, []),
        "take_profit_175": ({"take_profit": 1.75}, []),
        "take_profit_200": ({"take_profit": 2.00}, []),
        "risk_total_50": ({"max_total_premium_fraction": 0.50}, []),
        "risk_total_55": ({"max_total_premium_fraction": 0.55}, []),
        "risk_idea_18_total_50": ({"max_premium_fraction": 0.18, "max_total_premium_fraction": 0.50}, []),
        "risk_idea_12_total_45": ({"max_premium_fraction": 0.12, "max_total_premium_fraction": 0.45}, []),
        "monthly08_min_otm0": ({"monthly_loss_stop": 0.08, "min_otm_pct": 0.0}, []),
        "monthly08_min_otm0_maxdte30": ({"monthly_loss_stop": 0.08, "min_otm_pct": 0.0, "max_dte": 30}, []),
        "monthly08_min_otm0_maxdte35": ({"monthly_loss_stop": 0.08, "min_otm_pct": 0.0, "max_dte": 35}, []),
        "monthly08_exclude_negative": ({"monthly_loss_stop": 0.08}, ["XLV", "TLT", "XLF", "META", "DIA"]),
        "monthly08_exclude_low_sample": ({"monthly_loss_stop": 0.08}, ["XLV", "META", "DIA"]),
        "monthly08_min_otm0_exclude_low_sample": (
            {"monthly_loss_stop": 0.08, "min_otm_pct": 0.0},
            ["XLV", "META", "DIA"],
        ),
        "min_otm0_take_profit150": ({"min_otm_pct": 0.0, "take_profit": 1.50}, []),
        "min_otm0_take_profit175": ({"min_otm_pct": 0.0, "take_profit": 1.75}, []),
        "min_otm0_maxdte30_take_profit150": (
            {"min_otm_pct": 0.0, "max_dte": 30, "take_profit": 1.50},
            [],
        ),
        "risk55_monthly08": ({"max_total_premium_fraction": 0.55, "monthly_loss_stop": 0.08}, []),
        "risk55_min_otm0": ({"max_total_premium_fraction": 0.55, "min_otm_pct": 0.0}, []),
        "close_all_monthly_loss": ({"close_on_monthly_loss_stop": True, "close_losers_on_monthly_loss_stop": False}, []),
        "close_all_monthly_loss08": (
            {"monthly_loss_stop": 0.08, "close_on_monthly_loss_stop": True, "close_losers_on_monthly_loss_stop": False},
            [],
        ),
        "close_profit_lock": ({"close_on_monthly_profit_lock": True}, []),
    }


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chain = load_option_chains(args.chains)
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    weights = weights.loc[(weights.index >= start) & (weights.index <= end)]

    rows = []
    base = base_config()
    for name, (overrides, excludes) in variants().items():
        config = OptionBacktestConfig(**{**base, **overrides})
        test_weights = make_weights(weights, excludes)
        result = run_long_call_backtest(chain, test_weights, args.initial_cash, config)
        variant_dir = output_dir / name
        variant_dir.mkdir(parents=True, exist_ok=True)
        for result_name, frame in result.items():
            frame.to_csv(variant_dir / f"{result_name}.csv", index=False)
        monthly = monthly_breakdown(result["equity"], start, args.initial_cash)
        monthly.to_csv(variant_dir / "monthly.csv", index_label="date")
        final = float(result["equity"]["equity"].iloc[-1])
        rows.append(
            {
                "variant": name,
                "excluded_symbols": ",".join(excludes),
                "final_equity": final,
                "total_return": final / args.initial_cash - 1.0,
                "max_drawdown": drawdown(result["equity"]),
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
            f"dd={drawdown(result['equity']) * 100:,.2f}%"
        )

    summary = pd.DataFrame(rows).sort_values(["losing_months", "final_equity"], ascending=[True, False])
    summary.to_csv(output_dir / "summary.csv", index=False)
    print(f"Summary: {output_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
