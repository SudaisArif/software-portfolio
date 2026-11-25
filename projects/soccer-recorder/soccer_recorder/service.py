from __future__ import annotations

import json
import logging
import signal
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .hudl import HudlAdapter
from .models import Game
from .notifications import EmailNotifier
from .recorder import GameRecorder, RecorderSettings, RecordingResult
from .xlsx_schedule import XlsxScheduleReader


LOG = logging.getLogger(__name__)


class RecorderService:
    def __init__(self, workbook: Path, settings: RecorderSettings, timezone: str = "America/New_York") -> None:
        self.workbook = workbook.resolve()
        self.settings = settings
        self.timezone = timezone
        self.adapter = HudlAdapter()
        notification_config = settings.output_dir.resolve().parent / "email-notifications.json"
        self.notifier = EmailNotifier.from_file(notification_config)
        self.recorder = GameRecorder(self.adapter, settings, self.notifier)
        self.stop_event = threading.Event()
        self.state_path = settings.output_dir.resolve() / "recorder-state.json"
        self.state = self._load_state()

    def games(self) -> list[Game]:
        return XlsxScheduleReader(self.workbook, self.timezone).read_games(selected_only=True)

    def preflight(self, games: list[Game]) -> list[tuple[Game, object]]:
        results: list[tuple[Game, object]] = []
        for game in games:
            try:
                event = self.adapter.resolve(game)
                results.append((game, event))
            except Exception as exc:
                results.append((game, exc))
        return results

    def run_games(self, games: list[Game]) -> list[RecordingResult]:
        if not games:
            return []
        self._install_signal_handlers()
        with ThreadPoolExecutor(max_workers=max(1, len(games)), thread_name_prefix="game") as executor:
            future_map = {executor.submit(self.recorder.record, game, self.stop_event): game for game in games}
            results: list[RecordingResult] = []
            for future, game in future_map.items():
                try:
                    result = future.result()
                except Exception as exc:
                    LOG.exception("Unhandled recorder failure for %s", game.label)
                    result = RecordingResult(game.key, None, "failed", error=str(exc))
                results.append(result)
                self._save_result(result)
            return results

    def watch(self, interval_seconds: int = 60) -> None:
        self._install_signal_handlers()
        running: dict[str, Future[RecordingResult]] = {}
        executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="game")
        LOG.info("Watching %s for green-highlighted games", self.workbook)
        try:
            while not self.stop_event.is_set():
                today = datetime.now(ZoneInfo(self.timezone)).date()
                for game in self.games():
                    if game.game_date != today or game.key in running or self._is_completed(game.key):
                        continue
                    LOG.info("Launching monitor for Excel row %s: %s", game.row, game.label)
                    running[game.key] = executor.submit(self.recorder.record, game, self.stop_event)
                for key, future in list(running.items()):
                    if future.done():
                        result = future.result()
                        self._save_result(result)
                        del running[key]
                self.stop_event.wait(interval_seconds)
        finally:
            self.stop_event.set()
            executor.shutdown(wait=True, cancel_futures=False)

    def _load_state(self) -> dict[str, object]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"results": {}}

    def _is_completed(self, key: str) -> bool:
        result = self.state.get("results", {}).get(key, {})
        return result.get("status") in {"completed", "already-recorded"}

    def _save_result(self, result: RecordingResult) -> None:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        self.state.setdefault("results", {})[result.game_key] = {
            **asdict(result),
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return

        def stop(_signum: int, _frame: object) -> None:
            LOG.info("Shutdown requested; safely stopping active recorders")
            self.stop_event.set()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)


def games_for_date(games: list[Game], requested: date) -> list[Game]:
    return [game for game in games if game.game_date == requested]
