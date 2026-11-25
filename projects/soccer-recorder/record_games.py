#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from soccer_recorder.models import HudlEvent
from soccer_recorder.recorder import RecorderSettings
from soccer_recorder.service import RecorderService, games_for_date


DEFAULT_TIMEZONE = "America/New_York"


def parse_date(value: str, timezone: str) -> date:
    today = datetime.now(ZoneInfo(timezone)).date()
    if value.casefold() == "today":
        return today
    if value.casefold() == "tomorrow":
        return today + timedelta(days=1)
    return date.fromisoformat(value)


def find_workbook(value: str | None) -> Path:
    if value:
        return Path(value)
    matches = sorted(Path.cwd().glob("*.xlsx"))
    if len(matches) != 1:
        raise SystemExit("Pass --workbook because exactly one .xlsx file was not found in this folder")
    return matches[0]


def configure_logging(output_dir: Path, verbose: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers.append(logging.FileHandler(output_dir / "recorder.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
        handlers=handlers,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record green-highlighted soccer streams from an Excel schedule")
    parser.add_argument("--workbook", help="Path to the .xlsx schedule (auto-detected when omitted)")
    parser.add_argument("--output-dir", default="recordings", help="Folder for recordings and logs")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="Timezone used by the Excel schedule")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List green-highlighted games")
    list_parser.add_argument("--date", default=None, help="today, tomorrow, YYYY-MM-DD, or omit for all")

    preflight = subparsers.add_parser("preflight", help="Resolve links and show provider status without recording")
    preflight.add_argument("--date", default="today")

    run = subparsers.add_parser("run", help="Monitor and record selected games for one date")
    run.add_argument("--date", default="today")
    run.add_argument("--poll-seconds", type=int, default=10)
    run.add_argument("--start-early-minutes", type=int, default=45)

    watch = subparsers.add_parser("watch", help="Continuously watch the workbook and record each day's green games")
    watch.add_argument("--interval-seconds", type=int, default=60)
    watch.add_argument("--poll-seconds", type=int, default=10)
    watch.add_argument("--start-early-minutes", type=int, default=45)

    smoke = subparsers.add_parser("smoke-test", help="Record and validate a short clip from real Hudl media")
    smoke.add_argument("--event-id", default="4029919", help="Playable public Hudl event ID")
    smoke.add_argument("--seconds", type=int, default=20, help="Clip duration, from 5 to 120 seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workbook = find_workbook(args.workbook)
    output_dir = Path(args.output_dir)
    configure_logging(output_dir, args.verbose)
    settings = RecorderSettings(
        output_dir=output_dir,
        poll_seconds=getattr(args, "poll_seconds", 10),
        start_early_minutes=getattr(args, "start_early_minutes", 45),
    )
    service = RecorderService(workbook, settings, args.timezone)
    games = service.games()

    if args.command == "list":
        if args.date:
            games = games_for_date(games, parse_date(args.date, args.timezone))
        for game in games:
            print(
                f"row={game.row:<3} {game.game_date} {game.kickoff.strftime('%I:%M %p')}  "
                f"{game.label}  {game.livestream_url}"
            )
        print(f"{len(games)} selected game(s)")
        return 0

    if args.command == "preflight":
        games = games_for_date(games, parse_date(args.date, args.timezone))
        failures = 0
        for game, resolved in service.preflight(games):
            if isinstance(resolved, Exception):
                failures += 1
                print(f"FAIL  row {game.row}: {game.label}: {resolved}")
                continue
            event = resolved
            assert isinstance(event, HudlEvent)
            provider_time = event.scheduled_at.astimezone(ZoneInfo(args.timezone))
            workbook_time = datetime.combine(game.game_date, game.kickoff, ZoneInfo(args.timezone))
            difference = abs((provider_time - workbook_time).total_seconds()) / 60
            warning = f"  WARNING: workbook differs by {difference:.0f} min" if difference >= 10 else ""
            print(
                f"OK    row {game.row}: Hudl {event.event_id} | {event.title} | "
                f"{provider_time.strftime('%Y-%m-%d %I:%M %p %Z')} | {event.status}{warning}"
            )
        return 1 if failures else 0

    if args.command == "run":
        games = games_for_date(games, parse_date(args.date, args.timezone))
        if not games:
            print("No green-highlighted games found for that date", file=sys.stderr)
            return 1
        results = service.run_games(games)
        for result in results:
            print(f"{result.status}: {result.output_file or result.error}")
        return 1 if any(result.status == "failed" for result in results) else 0

    if args.command == "watch":
        service.watch(args.interval_seconds)
        return 0
    if args.command == "smoke-test":
        output = service.recorder.smoke_test(args.event_id, args.seconds)
        print(f"PASS: recorded and validated {output}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
