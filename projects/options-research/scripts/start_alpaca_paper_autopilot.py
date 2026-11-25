#!/usr/bin/env python3
"""Start the Alpaca paper autopilot as a detached local process."""
import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED_ORDERS = [
    "artifacts/live_run_now_2026_05_01/alpaca_orders.csv",
    "artifacts/live_run_now_2026_05_01/googl_retry_order.csv",
    "artifacts/live_run_now_2026_05_01/duplicate_exit_replace_order.csv",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Launch the Alpaca paper autopilot in the background.")
    parser.add_argument("--output-dir", default="artifacts/alpaca_paper_autopilot_live_2026_05_01")
    parser.add_argument("--state-dir", default="data/paper_trading")
    parser.add_argument("--weights", default="reports_live/latest_otm_weights.csv")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--cycles", type=int, default=0)
    parser.add_argument("--seed-order", action="append", default=[])
    parser.add_argument("--option-feed", default="indicative", choices=["indicative", "opra"])
    parser.add_argument("--stop-loss", type=float, default=0.70)
    parser.add_argument("--monthly-loss-stop", type=float, default=0.00)
    parser.add_argument("--min-entry-weight", type=float, default=0.30)
    parser.add_argument("--no-submit", action="store_true", help="Run monitor-only without submitting paper orders.")
    return parser.parse_args()


def require_paper_env(env):
    missing = [name for name in ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"] if not env.get(name)]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
    base_url = env.get("APCA_API_BASE_URL", "")
    if "paper-api.alpaca.markets" not in base_url:
        raise SystemExit("Refusing to start: APCA_API_BASE_URL must point to Alpaca paper trading.")


def main():
    args = parse_args()
    env = os.environ.copy()
    require_paper_env(env)

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "autopilot.log"
    pid_file = output_dir / "autopilot.pid"
    seed_orders = args.seed_order or DEFAULT_SEED_ORDERS

    command = [
        sys.executable,
        "-u",
        "scripts/alpaca_paper_autopilot.py",
        "--output-dir",
        args.output_dir,
        "--state-dir",
        args.state_dir,
        "--weights",
        args.weights,
        "--interval-seconds",
        str(args.interval_seconds),
        "--cycles",
        str(args.cycles),
        "--option-feed",
        args.option_feed,
        "--stop-loss",
        str(args.stop_loss),
        "--monthly-loss-stop",
        str(args.monthly_loss_stop),
        "--min-entry-weight",
        str(args.min_entry_weight),
    ]
    for seed_order in seed_orders:
        command.extend(["--seed-order", seed_order])
    if not args.no_submit:
        command.append("--submit")

    log_handle = log_file.open("ab", buffering=0)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
    print(f"Started Alpaca paper autopilot PID {process.pid}")
    print(f"Log: {log_file}")
    print(f"PID file: {pid_file}")


if __name__ == "__main__":
    main()
