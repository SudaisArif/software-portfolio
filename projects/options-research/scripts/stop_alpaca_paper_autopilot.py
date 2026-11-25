#!/usr/bin/env python3
"""Stop the detached Alpaca paper autopilot process."""
import argparse
import os
import signal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Stop the detached Alpaca paper autopilot.")
    parser.add_argument("--output-dir", default="artifacts/alpaca_paper_autopilot_live_2026_05_01")
    return parser.parse_args()


def main():
    args = parse_args()
    pid_file = ROOT / args.output_dir / "autopilot.pid"
    if not pid_file.exists():
        raise SystemExit(f"No PID file found: {pid_file}")
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"Autopilot process {pid} is not running.")
        return
    print(f"Stopped Alpaca paper autopilot PID {pid}")


if __name__ == "__main__":
    main()
