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
    parser = argparse.ArgumentParser(description="Targeted sweep around near-$20k real-options profiles.")
    parser.add_argument("--chains", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--initial-cash", type=float, default=1000.0)
    parser.add_argument("--output-dir", default="artifacts/option_20k_push")
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


def make_weights(weights, excludes):
    out = weights.copy()
    for symbol in excludes:
        if symbol in out.columns:
            out[symbol] = 0.0
    return out


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
    out = {
        "refined_best": ({}, []),
        "monthly_loss_08": ({"monthly_loss_stop": 0.08}, []),
        "risk_total_55": ({"max_total_premium_fraction": 0.55}, []),
    }
    for total in [0.47, 0.48, 0.49, 0.50, 0.52, 0.55]:
        out[f"total_{int(total*100):02d}_monthly08"] = (
            {"max_total_premium_fraction": total, "monthly_loss_stop": 0.08},
            [],
        )
        out[f"total_{int(total*100):02d}_cap10"] = (
            {"max_total_premium_fraction": total, "max_contracts_per_trade": 10},
            [],
        )
        out[f"total_{int(total*100):02d}_cap12"] = (
            {"max_total_premium_fraction": total, "max_contracts_per_trade": 12},
            [],
        )
    for cap in [8, 10, 12, 14]:
        out[f"risk55_cap{cap}"] = ({"max_total_premium_fraction": 0.55, "max_contracts_per_trade": cap}, [])
        out[f"monthly08_cap{cap}"] = ({"monthly_loss_stop": 0.08, "max_contracts_per_trade": cap}, [])
    for loss in [0.075, 0.08, 0.085, 0.09, 0.095]:
        out[f"loss{int(loss*1000):03d}"] = ({"monthly_loss_stop": loss}, [])
        out[f"loss{int(loss*1000):03d}_total50"] = (
            {"monthly_loss_stop": loss, "max_total_premium_fraction": 0.50},
            [],
        )
    out.update(
        {
            "risk55_exclude_tlt": ({"max_total_premium_fraction": 0.55}, ["TLT"]),
            "risk55_exclude_xlv_tlt_xlf": ({"max_total_premium_fraction": 0.55}, ["XLV", "TLT", "XLF"]),
            "risk55_exclude_tlt_cap12": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_loss075": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12, "monthly_loss_stop": 0.075},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_loss085": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12, "monthly_loss_stop": 0.085},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_loss090": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12, "monthly_loss_stop": 0.09},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_loss095": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12, "monthly_loss_stop": 0.095},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_profit45": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12, "monthly_profit_lock": 0.45},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_profit55": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12, "monthly_profit_lock": 0.55},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_profit60": (
                {"max_total_premium_fraction": 0.55, "max_contracts_per_trade": 12, "monthly_profit_lock": 0.60},
                ["TLT"],
            ),
            "risk55_exclude_tlt_cap12_close_profit": (
                {
                    "max_total_premium_fraction": 0.55,
                    "max_contracts_per_trade": 12,
                    "close_on_monthly_profit_lock": True,
                },
                ["TLT"],
            ),
            "risk55_exclude_tlt_monthly08": (
                {"max_total_premium_fraction": 0.55, "monthly_loss_stop": 0.08},
                ["TLT"],
            ),
            "monthly08_exclude_tlt": ({"monthly_loss_stop": 0.08}, ["TLT"]),
            "monthly08_exclude_xlv": ({"monthly_loss_stop": 0.08}, ["XLV"]),
            "monthly08_exclude_xlv_tlt_xlf": ({"monthly_loss_stop": 0.08}, ["XLV", "TLT", "XLF"]),
            "monthly08_take150": ({"monthly_loss_stop": 0.08, "take_profit": 1.50}, []),
            "monthly08_take175": ({"monthly_loss_stop": 0.08, "take_profit": 1.75}, []),
            "monthly08_hold6": ({"monthly_loss_stop": 0.08, "max_hold_days": 6}, []),
            "monthly08_hold5": ({"monthly_loss_stop": 0.08, "max_hold_days": 5}, []),
            "monthly08_dte30": ({"monthly_loss_stop": 0.08, "max_dte": 30}, []),
            "monthly08_dte35": ({"monthly_loss_stop": 0.08, "max_dte": 35}, []),
            "monthly08_min_price125": ({"monthly_loss_stop": 0.08, "min_contract_price": 1.25}, []),
            "monthly08_min_price150": ({"monthly_loss_stop": 0.08, "min_contract_price": 1.50}, []),
            "monthly08_spread06": ({"monthly_loss_stop": 0.08, "max_spread_pct": 0.06}, []),
            "monthly08_spread08": ({"monthly_loss_stop": 0.08, "max_spread_pct": 0.08}, []),
        }
    )
    return {name: ({**base, **overrides}, excludes) for name, (overrides, excludes) in out.items()}


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
    for name, (config_kwargs, excludes) in variants().items():
        config = OptionBacktestConfig(**config_kwargs)
        result = run_long_call_backtest(chain, make_weights(weights, excludes), args.initial_cash, config)
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
    summary = pd.DataFrame(rows).sort_values(["final_equity"], ascending=False)
    summary.to_csv(output_dir / "summary.csv", index=False)
    print(f"Summary: {output_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
