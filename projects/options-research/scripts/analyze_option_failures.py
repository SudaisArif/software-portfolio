#!/usr/bin/env python3
import argparse
import sys
from collections import defaultdict, deque
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algotrader.option_chain import load_option_chains


def parse_args():
    parser = argparse.ArgumentParser(description="Pair real option orders and summarize losing trades.")
    parser.add_argument("--chains", required=True)
    parser.add_argument("--orders", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def markdown_table(frame, max_rows=None):
    if frame.empty:
        return "_No rows._"
    if max_rows is not None:
        frame = frame.head(max_rows)
    out = frame.reset_index() if frame.index.name is not None else frame.copy()
    columns = [str(col) for col in out.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in out.iterrows():
        values = []
        for value in row:
            if isinstance(value, pd.Timestamp):
                values.append(str(value.date()))
            elif isinstance(value, float):
                values.append(f"{value:,.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def enrich_entry(order, chain_by_key, weights):
    date = pd.Timestamp(order["date"])
    contract_id = str(order["contract_id"])
    quote = chain_by_key.get((date, contract_id))
    out = {
        "entry_spread_pct": None,
        "entry_dte": None,
        "entry_otm_pct": None,
        "entry_underlying_price": None,
        "entry_mid": None,
        "entry_weight": None,
    }
    if quote is not None:
        underlying = float(quote["underlying_price"]) if pd.notna(quote.get("underlying_price")) else None
        strike = float(quote["strike"])
        out.update(
            {
                "entry_spread_pct": float(quote["spread_pct"]) if pd.notna(quote.get("spread_pct")) else None,
                "entry_dte": int((pd.Timestamp(quote["expiration"]) - date).days),
                "entry_otm_pct": strike / underlying - 1.0 if underlying and underlying > 0 else None,
                "entry_underlying_price": underlying,
                "entry_mid": float(quote["mid"]) if pd.notna(quote.get("mid")) else None,
            }
        )
    if date in weights.index and order["symbol"] in weights.columns:
        out["entry_weight"] = float(weights.loc[date, order["symbol"]])
    return out


def pair_trades(orders, chain, weights):
    chain_by_key = {
        (pd.Timestamp(row["quote_date"]), str(row["contract_id"])): row
        for row in chain[
            [
                "quote_date",
                "contract_id",
                "expiration",
                "strike",
                "underlying_price",
                "spread_pct",
                "mid",
            ]
        ].to_dict("records")
    }
    open_lots = defaultdict(deque)
    trades = []
    for _, order in orders.sort_values("date").iterrows():
        action = str(order["action"]).upper()
        contract_id = str(order["contract_id"])
        qty = int(order["quantity"])
        if action == "BUY":
            lot = order.to_dict()
            lot["remaining_quantity"] = qty
            lot.update(enrich_entry(order, chain_by_key, weights))
            open_lots[contract_id].append(lot)
            continue
        remaining = qty
        while remaining > 0 and open_lots[contract_id]:
            lot = open_lots[contract_id][0]
            matched_qty = min(remaining, int(lot["remaining_quantity"]))
            entry_price = float(lot["price"])
            exit_price = float(order["price"])
            entry_value = entry_price * 100 * matched_qty
            exit_value = exit_price * 100 * matched_qty
            entry_date = pd.Timestamp(lot["date"])
            exit_date = pd.Timestamp(order["date"])
            trades.append(
                {
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "month": exit_date.to_period("M").strftime("%Y-%m"),
                    "symbol": order["symbol"],
                    "contract_id": contract_id,
                    "quantity": matched_qty,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "entry_value": entry_value,
                    "exit_value": exit_value,
                    "pnl_dollars": exit_value - entry_value,
                    "pnl_pct": exit_price / entry_price - 1.0 if entry_price > 0 else 0.0,
                    "hold_days": (exit_date - entry_date).days,
                    "entry_spread_pct": lot["entry_spread_pct"],
                    "entry_dte": lot["entry_dte"],
                    "entry_otm_pct": lot["entry_otm_pct"],
                    "entry_underlying_price": lot["entry_underlying_price"],
                    "entry_mid": lot["entry_mid"],
                    "entry_weight": lot["entry_weight"],
                    "exit_reason": order.get("reason", ""),
                }
            )
            lot["remaining_quantity"] -= matched_qty
            remaining -= matched_qty
            if int(lot["remaining_quantity"]) <= 0:
                open_lots[contract_id].popleft()
    return pd.DataFrame(trades)


def load_chain_subset(path, contract_ids):
    source = Path(path)
    columns = [
        "quote_date",
        "contract_id",
        "expiration",
        "strike",
        "underlying_price",
        "spread_pct",
        "mid",
    ]
    if source.is_file() and source.suffix.lower() == ".parquet":
        try:
            chain = pd.read_parquet(source, columns=columns, filters=[("contract_id", "in", list(contract_ids))])
        except Exception:
            chain = pd.read_parquet(source, columns=columns)
        chain = chain[chain["contract_id"].astype(str).isin(contract_ids)].copy()
        chain["quote_date"] = pd.to_datetime(chain["quote_date"]).dt.tz_localize(None)
        chain["expiration"] = pd.to_datetime(chain["expiration"]).dt.tz_localize(None)
        return chain
    chain = load_option_chains(path)
    return chain[chain["contract_id"].astype(str).isin(contract_ids)].copy()


def write_report(trades, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(output_dir / "paired_trades.csv", index=False)
    losers = trades[trades["pnl_dollars"] < 0].copy()
    monthly = trades.groupby("month").agg(
        trades=("pnl_dollars", "size"),
        win_rate=("pnl_dollars", lambda s: float((s > 0).mean())),
        pnl_dollars=("pnl_dollars", "sum"),
        avg_pnl_pct=("pnl_pct", "mean"),
        worst_pnl_pct=("pnl_pct", "min"),
        avg_entry_spread=("entry_spread_pct", "mean"),
        avg_entry_otm=("entry_otm_pct", "mean"),
        avg_entry_weight=("entry_weight", "mean"),
    )
    symbols = trades.groupby("symbol").agg(
        trades=("pnl_dollars", "size"),
        win_rate=("pnl_dollars", lambda s: float((s > 0).mean())),
        pnl_dollars=("pnl_dollars", "sum"),
        avg_pnl_pct=("pnl_pct", "mean"),
        worst_pnl_pct=("pnl_pct", "min"),
        avg_entry_spread=("entry_spread_pct", "mean"),
        avg_entry_otm=("entry_otm_pct", "mean"),
        avg_entry_weight=("entry_weight", "mean"),
    ).sort_values("pnl_dollars")
    worst = trades.sort_values("pnl_dollars").head(20)
    loser_profile = losers.agg(
        {
            "pnl_dollars": "sum",
            "pnl_pct": "mean",
            "entry_spread_pct": "mean",
            "entry_dte": "mean",
            "entry_otm_pct": "mean",
            "entry_weight": "mean",
            "hold_days": "mean",
        }
    )
    monthly.to_csv(output_dir / "trade_summary_by_month.csv")
    symbols.to_csv(output_dir / "trade_summary_by_symbol.csv")
    worst.to_csv(output_dir / "worst_trades.csv", index=False)
    report = [
        "# Option Loss Diagnostics",
        "",
        f"Closed trades: **{len(trades)}**",
        f"Losing trades: **{len(losers)}**",
        f"Win rate: **{(trades['pnl_dollars'] > 0).mean() * 100:,.2f}%**" if len(trades) else "Win rate: n/a",
        f"Total closed-trade PnL: **${trades['pnl_dollars'].sum():,.2f}**",
        "",
        "## Losing Trade Profile",
        "",
        markdown_table(loser_profile.to_frame("value")),
        "",
        "## Worst Symbols",
        "",
        markdown_table(symbols.head(10)),
        "",
        "## Worst Trades",
        "",
        markdown_table(
            worst[
                [
                    "entry_date",
                    "exit_date",
                    "symbol",
                    "contract_id",
                    "quantity",
                    "entry_price",
                    "exit_price",
                    "pnl_dollars",
                    "pnl_pct",
                    "entry_dte",
                    "entry_otm_pct",
                    "entry_spread_pct",
                    "entry_weight",
                ]
            ],
        ),
    ]
    (output_dir / "REPORT.md").write_text("\n".join(report))


def main():
    args = parse_args()
    orders = pd.read_csv(args.orders, parse_dates=["date"])
    contract_ids = set(orders["contract_id"].astype(str))
    chain = load_chain_subset(args.chains, contract_ids)
    weights = pd.read_csv(args.weights, parse_dates=["Date"]).set_index("Date")
    trades = pair_trades(orders, chain, weights)
    write_report(trades, Path(args.output_dir))
    print(f"Closed trades: {len(trades)}")
    print(f"Win rate: {(trades['pnl_dollars'] > 0).mean() * 100:,.2f}%")
    print(f"Closed-trade PnL: ${trades['pnl_dollars'].sum():,.2f}")
    print(f"Report: {args.output_dir}/REPORT.md")


if __name__ == "__main__":
    main()
