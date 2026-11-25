from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .hudl import ProviderError
from .models import Game, HudlEvent
from .notifications import EmailNotifier


LOG = logging.getLogger(__name__)
FINAL_STATUSES = {
    "ads-post",
    "archived",
    "complete",
    "completed",
    "concluded",
    "ended",
    "finished",
    "unavailable",
    "deleted",
}


def is_final_status(status: str) -> bool:
    normalized = status.strip().casefold().replace("_", "-").replace(" ", "-")
    return normalized in FINAL_STATUSES


@dataclass(slots=True)
class RecorderSettings:
    output_dir: Path
    poll_seconds: int = 10
    start_early_minutes: int = 45
    monitor_immediately: bool = False
    stop_grace_seconds: int = 20 * 60
    max_event_hours: int = 5


@dataclass(slots=True)
class RecordingResult:
    game_key: str
    event_id: str | None
    status: str
    output_file: str | None = None
    error: str | None = None


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return re.sub(r"-+", "-", cleaned).strip("-._") or "game"


def media_tool(name: str) -> str | None:
    """Find FFmpeg tools installed normally or bundled by PyInstaller."""
    bundled_root = getattr(sys, "_MEIPASS", None)
    candidates = []
    if bundled_root:
        candidates.append(Path(bundled_root) / name)
    candidates.extend(
        (
            Path(sys.executable).resolve().parent / name,
            Path(sys.executable).resolve().parent.parent / "Frameworks" / name,
            Path(sys.executable).resolve().parent.parent / "Resources" / name,
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


class GameRecorder:
    def __init__(
        self,
        adapter: object,
        settings: RecorderSettings,
        notifier: EmailNotifier | None = None,
    ) -> None:
        self.adapter = adapter
        self.settings = settings
        self.notifier = notifier or EmailNotifier()
        self.ffmpeg = media_tool("ffmpeg")
        self.ffprobe = media_tool("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            raise RuntimeError("FFmpeg and ffprobe are required. Install them with: brew install ffmpeg")

    def record(
        self,
        game: Game,
        stop_event: threading.Event | None = None,
        resolved_event: HudlEvent | None = None,
    ) -> RecordingResult:
        stop_event = stop_event or threading.Event()
        event: HudlEvent | None = resolved_event
        try:
            if event is None:
                event = self.adapter.resolve(game)
            provider_name = self._provider_name(event)
            if event.require_login and not bool(getattr(self.adapter, "supports_login", False)):
                raise ProviderError(f"This {provider_name} event requires a login; unattended capture is not enabled")
            if not event.available:
                raise ProviderError(f"{provider_name} marks this event unavailable")
            result = self._record_resolved(game, event, stop_event)
            if result.status == "failed":
                self.notifier.recording_failed(game, event.event_id, result.error or "Unknown failure")
            return result
        except Exception as exc:
            LOG.exception("Recording failed for %s", game.label)
            self.notifier.recording_failed(game, event.event_id if event else None, str(exc))
            return RecordingResult(
                game_key=game.key,
                event_id=event.event_id if event else None,
                status="failed",
                error=str(exc),
            )

    def smoke_test(self, event_id: str, seconds: int = 20) -> Path:
        """Record and validate a short clip from a real provider media feed."""
        if not 5 <= seconds <= 120:
            raise ValueError("Smoke-test duration must be between 5 and 120 seconds")
        snapshot = self.adapter.snapshot(event_id)
        if not snapshot.content_url:
            raise ProviderError(f"Event {event_id} does not currently expose playable media")
        output_dir = self.settings.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
        provider = str(getattr(self.adapter, "provider", "hudl"))
        base_name = safe_filename(f"smoke-test_{stamp}_{provider}-{event_id}")
        parts_dir = output_dir / ".parts" / f"smoke-{event_id}-{stamp}"
        parts_dir.mkdir(parents=True, exist_ok=True)
        part = parts_dir / "part-001.ts"
        output_file = output_dir / f"{base_name}.mp4"
        log_path = output_dir / "logs" / f"{base_name}.ffmpeg.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-y",
            "-rw_timeout",
            "30000000",
            "-i",
            snapshot.content_url,
            "-t",
            str(seconds),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-f",
            "mpegts",
            str(part),
        ]
        with log_path.open("ab") as log_file:
            completed = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT, timeout=seconds + 90, check=False)
        if completed.returncode != 0 or not part.exists() or part.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg smoke test failed; see {log_path}")
        self._finalize([part], output_file, parts_dir, output_dir / "logs" / f"{base_name}.finalize.log")
        close = getattr(self.adapter, "close", None)
        if callable(close):
            close(event_id)
        LOG.info("Provider smoke test passed: %s", output_file)
        return output_file

    def _record_resolved(self, game: Game, event: HudlEvent, stop_event: threading.Event) -> RecordingResult:
        output_dir = self.settings.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        provider = event.provider or str(getattr(self.adapter, "provider", "hudl"))
        provider_name = self._provider_name(event)
        parts_dir = output_dir / ".parts" / f"{provider}-{event.event_id}"
        parts_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = output_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        event_local = event.scheduled_at.astimezone(ZoneInfo(game.timezone))
        base_name = safe_filename(
            f"{event_local:%Y-%m-%d_%H%M}_{game.home_team}_vs_{game.away_team}_{provider}-{event.event_id}"
        )
        output_file = output_dir / f"{base_name}.mp4"
        checkpoint_file = output_dir / f"{base_name}_CHECKPOINT-first-2-minutes.mp4"
        if output_file.exists() and output_file.stat().st_size > 0:
            LOG.info("Recording already exists: %s", output_file)
            return RecordingResult(game.key, event.event_id, "already-recorded", str(output_file))

        now = datetime.now(event.scheduled_at.tzinfo)
        monitor_start = event.scheduled_at - timedelta(minutes=self.settings.start_early_minutes)
        if not self.settings.monitor_immediately and now < monitor_start:
            wait_seconds = (monitor_start - now).total_seconds()
            LOG.info("%s: waiting %.0f minutes before monitoring", game.label, wait_seconds / 60)
            if stop_event.wait(wait_seconds):
                return RecordingResult(game.key, event.event_id, "stopped")

        hard_deadline = event.scheduled_at + timedelta(hours=self.settings.max_event_hours)
        active_process: subprocess.Popen[bytes] | None = None
        parts: list[Path] = sorted(path for path in parts_dir.glob("part-*.ts") if path.stat().st_size > 0)
        started_once = bool(parts)
        inactive_since: float | None = None
        last_media_bytes = sum(path.stat().st_size for path in parts)
        last_media_growth_at: float | None = time.monotonic() if started_once else None
        last_status: tuple[str, bool] | None = None
        next_start_allowed = 0.0
        active_since: float | None = None
        start_notified = False
        checkpoint_done = checkpoint_file.exists() and checkpoint_file.stat().st_size > 0

        LOG.info(
            "%s: monitoring %s event %s (provider kickoff %s)",
            game.label,
            provider_name,
            event.event_id,
            event_local.strftime("%Y-%m-%d %I:%M %p %Z"),
        )
        while not stop_event.is_set():
            if datetime.now(event.scheduled_at.tzinfo) > hard_deadline:
                LOG.warning("%s: reached the five-hour safety deadline", game.label)
                break
            try:
                snapshot = self.adapter.snapshot(event.event_id)
            except Exception as exc:
                # A temporary provider/API failure must not kill a healthy
                # FFmpeg process that is still writing the already-issued URL.
                if active_process is not None and active_process.poll() is None:
                    LOG.warning("%s: provider check failed while capture continues: %s", game.label, exc)
                    if stop_event.wait(self.settings.poll_seconds):
                        break
                    continue
                raise
            state = (snapshot.status, snapshot.streaming)
            if state != last_status:
                LOG.info("%s: %s status=%s streaming=%s", game.label, provider_name, snapshot.status, snapshot.streaming)
                last_status = state

            # Providers can leave a stale playable URL and streaming=true after an
            # event has been archived.  Provider final state takes precedence
            # so completed games are finalized immediately instead of waiting
            # for the five-hour safety deadline.
            if is_final_status(snapshot.status):
                LOG.info("%s: provider reported final status %s; finalizing", game.label, snapshot.status)
                break

            if active_process is not None and active_process.poll() is not None:
                exit_code = active_process.returncode
                LOG.warning("%s: FFmpeg exited with code %s; monitoring for restart", game.label, exit_code)
                active_process = None
                active_since = None
                refresh_stream = getattr(self.adapter, "refresh_stream", None)
                if callable(refresh_stream):
                    # Flo playback URLs are intentionally short-lived. If the
                    # venue feed is still TESTING or briefly unavailable, never
                    # retry an expired URL; request a new token on the next poll.
                    refresh_stream(event.event_id)
                next_start_allowed = time.monotonic() + self.settings.poll_seconds
                if stop_event.wait(self.settings.poll_seconds):
                    break
                continue

            if (
                active_process is not None
                and active_process.poll() is None
                and active_since is not None
                and not start_notified
                and time.monotonic() - active_since >= 5
            ):
                self.notifier.recording_started(game, event)
                start_notified = True

            if (
                active_process is not None
                and active_process.poll() is None
                and active_since is not None
                and not checkpoint_done
                and parts
                and time.monotonic() - active_since >= 125
            ):
                try:
                    self._create_checkpoint(
                        parts[-1],
                        checkpoint_file,
                        logs_dir / f"{base_name}.checkpoint.log",
                        seconds=120,
                    )
                    checkpoint_done = True
                    LOG.info("%s: two-minute checkpoint validated at %s", game.label, checkpoint_file)
                    self.notifier.checkpoint_ready(game, event, checkpoint_file)
                except Exception as exc:
                    LOG.warning("%s: checkpoint not ready yet; will retry: %s", game.label, exc)

            if snapshot.streaming and snapshot.content_url:
                inactive_since = None
                if active_process is None and time.monotonic() >= next_start_allowed:
                    part_path = parts_dir / f"part-{len(parts) + 1:03d}.ts"
                    log_path = logs_dir / f"{base_name}.ffmpeg.log"
                    active_process = self._start_ffmpeg(snapshot.content_url, part_path, log_path)
                    active_since = time.monotonic()
                    parts.append(part_path)
                    started_once = True
                    if last_media_growth_at is None:
                        last_media_growth_at = time.monotonic()
                    LOG.info("%s: recording started in the background", game.label)
            elif started_once:
                if inactive_since is None:
                    inactive_since = time.monotonic()
                inactive_for = time.monotonic() - inactive_since
                if inactive_for >= self.settings.stop_grace_seconds:
                    LOG.info("%s: stream ended; finalizing", game.label)
                    break

            # A provider can incorrectly keep reporting streaming=true after its
            # HLS feed has stopped. Track actual bytes as an independent end
            # signal, while keeping enough grace for a normal soccer halftime.
            current_media_bytes = sum(
                path.stat().st_size for path in parts if path.exists() and path.is_file()
            )
            if current_media_bytes > last_media_bytes:
                last_media_bytes = current_media_bytes
                last_media_growth_at = time.monotonic()
            elif (
                started_once
                and last_media_growth_at is not None
                and time.monotonic() - last_media_growth_at >= self.settings.stop_grace_seconds
            ):
                LOG.info(
                    "%s: no new video bytes for %.0f minutes; treating the stale feed as ended",
                    game.label,
                    self.settings.stop_grace_seconds / 60,
                )
                break

            if stop_event.wait(self.settings.poll_seconds):
                break

        self._stop_process(active_process)
        close = getattr(self.adapter, "close", None)
        if callable(close):
            close(event.event_id)
        parts = [path for path in parts if path.exists() and path.stat().st_size > 0]
        if stop_event.is_set():
            LOG.info("%s: monitor stopped; preserving raw parts for automatic resume", game.label)
            return RecordingResult(game.key, event.event_id, "stopped")
        if not parts:
            return RecordingResult(
                game.key,
                event.event_id,
                "failed",
                error="The event never exposed a playable stream before monitoring ended",
            )
        finalizing = getattr(self.notifier, "recording_finalizing", None)
        if callable(finalizing):
            finalizing(game, event)
        self._finalize(parts, output_file, parts_dir, logs_dir / f"{base_name}.finalize.log")
        metadata = {
            "game": asdict(game),
            "provider_event": {
                **asdict(event),
                "scheduled_at": event.scheduled_at.isoformat(),
            },
            "output_file": str(output_file),
            "completed_at": datetime.now().astimezone().isoformat(),
        }
        metadata["game"]["game_date"] = game.game_date.isoformat()
        metadata["game"]["kickoff"] = game.kickoff.isoformat()
        (output_dir / f"{base_name}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.notifier.recording_completed(game, event, output_file)
        return RecordingResult(game.key, event.event_id, "completed", str(output_file))

    @staticmethod
    def _provider_name(event: HudlEvent) -> str:
        return "FloCollege" if event.provider == "flocollege" else event.provider.title()

    def _start_ffmpeg(self, stream_url: str, part_path: Path, log_path: Path) -> subprocess.Popen[bytes]:
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-y",
            "-rw_timeout",
            "30000000",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "10",
            "-i",
            stream_url,
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-f",
            "mpegts",
            str(part_path),
        ]
        with log_path.open("ab") as log_file:
            return subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _finalize(self, parts: list[Path], output_file: Path, parts_dir: Path, log_path: Path) -> None:
        concat_file = parts_dir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in parts),
            encoding="utf-8",
        )
        temporary_output = output_file.with_suffix(".partial.mp4")
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-y",
            "-fflags",
            "+discardcorrupt+genpts",
            "-err_detect",
            "ignore_err",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-map",
            "0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temporary_output),
        ]
        with log_path.open("ab") as log_file:
            completed = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT, timeout=30 * 60, check=False)
        if completed.returncode != 0 or not temporary_output.exists() or temporary_output.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg could not finalize the recording; raw parts remain in {parts_dir}")
        try:
            self._validate_media_file(temporary_output, minimum_duration=1)
        except RuntimeError as exc:
            raise RuntimeError(f"{exc}; raw parts remain in {parts_dir}") from exc
        temporary_output.replace(output_file)
        # Retain the source transport streams as a recovery copy.  Storage is
        # intentionally traded for safety so a validated MP4 is never the only
        # surviving copy of a game.
        LOG.info("Validated MP4 at %s; retaining raw parts in %s", output_file, parts_dir)
        concat_file.unlink(missing_ok=True)

    def _create_checkpoint(self, part: Path, output_file: Path, log_path: Path, seconds: int) -> None:
        temporary_output = output_file.with_suffix(".partial.mp4")
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-y",
            "-i",
            str(part),
            "-t",
            str(seconds),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temporary_output),
        ]
        with log_path.open("ab") as log_file:
            completed = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT, timeout=5 * 60, check=False)
        if completed.returncode != 0 or not temporary_output.exists() or temporary_output.stat().st_size == 0:
            temporary_output.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg could not create a checkpoint from the active transport stream")
        try:
            duration = self._validate_media_file(temporary_output, minimum_duration=seconds * 0.9)
        except RuntimeError as exc:
            temporary_output.unlink(missing_ok=True)
            raise RuntimeError(f"Checkpoint validation failed: {exc}") from exc
        temporary_output.replace(output_file)

    def _validate_media_file(self, path: Path, minimum_duration: float) -> float:
        probe = subprocess.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if probe.returncode != 0:
            raise RuntimeError("ffprobe could not read the recording")
        try:
            details = json.loads(probe.stdout)
            duration = float(details["format"]["duration"])
            size = int(details["format"]["size"])
            stream_types = {stream.get("codec_type") for stream in details.get("streams", [])}
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Recording metadata could not be validated") from exc
        if duration < minimum_duration:
            raise RuntimeError(f"Recording is only {duration:.1f} seconds long")
        if size <= 0:
            raise RuntimeError("Recording file is empty")
        if not {"video", "audio"}.issubset(stream_types):
            raise RuntimeError("Recording does not contain both video and audio")
        return duration
