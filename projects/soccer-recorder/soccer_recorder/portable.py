from __future__ import annotations

import fcntl
import codecs
import json
import logging
import os
import plistlib
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .hudl import ProviderError, UnsupportedProvider
from .models import Game, HudlEvent
from .notifications import EmailNotifier
from .providers import adapter_for_url, provider_key_for_url
from .readiness import macbook_lid_open, power_adapter_connected, sleep_prevention_active
from .recorder import GameRecorder, RecorderSettings, RecordingResult


LOG = logging.getLogger(__name__)
AGENT_LABEL = "com.soccerrecorder.worker"
KEYCHAIN_SERVICE = "com.soccerrecorder.gmail"


def preload_frozen_runtime() -> None:
    """Load lazy stdlib pieces before recording threads use the frozen archive."""
    import encodings.idna  # noqa: F401
    import email.contentmanager  # noqa: F401
    import email.generator  # noqa: F401
    import email.headerregistry  # noqa: F401
    import email.policy  # noqa: F401
    import stringprep  # noqa: F401
    import unicodedata  # noqa: F401

    # DNS uses the IDNA codec even for ordinary ASCII hostnames. Looking it up
    # here prevents simultaneous first-use imports in packaged worker threads.
    codecs.lookup("idna")
    codecs.lookup("punycode")


preload_frozen_runtime()


def support_dir() -> Path:
    override = os.environ.get("SOCCER_RECORDER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / "SoccerRecorder"


def default_output_dir() -> Path:
    return Path.home() / "Movies" / "Soccer Recordings"


def local_timezone_name() -> str:
    try:
        resolved = Path("/etc/localtime").resolve()
        marker = "/zoneinfo/"
        if marker in str(resolved):
            return str(resolved).split(marker, 1)[1]
    except OSError:
        pass
    return "America/New_York"


def iso_now() -> str:
    return datetime.now().astimezone().isoformat()


class JobStore:
    """Small cross-process JSON store shared by the app and worker."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or support_dir()
        self.path = self.root / "jobs.json"
        self.lock_path = self.root / "jobs.lock"
        self.root.mkdir(parents=True, exist_ok=True)

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("jobs"), list):
                return data
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            pass
        return {"jobs": []}

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def jobs(self) -> list[dict[str, Any]]:
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            return [dict(job) for job in self._read_unlocked()["jobs"]]

    def add(self, job: dict[str, Any]) -> None:
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read_unlocked()
            data["jobs"].append(job)
            self._write_unlocked(data)

    def add_many(self, jobs: list[dict[str, Any]]) -> None:
        if not jobs:
            return
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read_unlocked()
            data["jobs"].extend(jobs)
            self._write_unlocked(data)

    def update(self, job_id: str, **changes: Any) -> dict[str, Any] | None:
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read_unlocked()
            updated = None
            for job in data["jobs"]:
                if job.get("id") == job_id:
                    job.update(changes)
                    job["updated_at"] = iso_now()
                    updated = dict(job)
                    break
            if updated is not None:
                self._write_unlocked(data)
            return updated

    def get(self, job_id: str) -> dict[str, Any] | None:
        return next((job for job in self.jobs() if job.get("id") == job_id), None)

    def delete(self, job_id: str) -> dict[str, Any] | None:
        """Remove one scheduled job without touching any recording files."""
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read_unlocked()
            for index, job in enumerate(data["jobs"]):
                if job.get("id") == job_id:
                    removed = dict(data["jobs"].pop(index))
                    self._write_unlocked(data)
                    return removed
        return None


class NotificationHub:
    def __init__(self, email_config_path: Path | None = None) -> None:
        self.email_config_path = email_config_path or support_dir() / "email-notifications.json"

    @staticmethod
    def local(title: str, message: str) -> None:
        script = (
            "on run argv\n"
            "display notification (item 2 of argv) with title (item 1 of argv)\n"
            "end run"
        )
        try:
            subprocess.run(
                ["/usr/bin/osascript", "-e", script, title[:120], message[:240]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            LOG.exception("Could not display macOS notification")

    def email(self) -> EmailNotifier:
        return EmailNotifier.from_file(self.email_config_path)

    def healthy(self, label: str, event_id: str, total_bytes: int, provider: str = "provider") -> None:
        captured = human_size(total_bytes)
        title = f"Recording healthy: {label}"
        body = f"The recording is active and growing. Captured so far: {captured}. {provider} event: {event_id}."
        self.local(title, body)
        self.email().send(title, body)

    def stalled(self, label: str, event_id: str, provider: str = "provider") -> None:
        title = f"Recording may be stalled: {label}"
        body = f"No new video data arrived recently for {provider} event {event_id}. The recorder is still monitoring."
        self.local(title, body)
        self.email().send(title, body)


class JobNotifier:
    """Connect recorder notifications to the portable UI's job state."""

    def __init__(self, job_id: str, store: JobStore, hub: NotificationHub) -> None:
        self.job_id = job_id
        self.store = store
        self.hub = hub

    def _email(self) -> EmailNotifier:
        return self.hub.email()

    def recording_started(self, game: Game, event: HudlEvent) -> None:
        self.store.update(
            self.job_id,
            status="recording",
            status_message="Video and audio stream connected",
            event_id=event.event_id,
            provider=event.provider,
            parts_key=f"{event.provider}-{event.event_id}",
            recording_started_at=iso_now(),
            heartbeat_at=iso_now(),
        )
        self.hub.local(f"Recording started: {game.label}", "Video and audio are being saved in the background.")
        self._email().recording_started(game, event)

    def recording_completed(self, game: Game, event: HudlEvent, output_file: Path) -> None:
        self.store.update(
            self.job_id,
            status="completed",
            status_message="MP4 saved and validated; raw backup retained",
            output_file=str(output_file),
            completed_at=iso_now(),
        )
        self.hub.local(f"Recording saved: {game.label}", str(output_file))
        self._email().recording_completed(game, event, output_file)

    def checkpoint_ready(self, game: Game, event: HudlEvent, checkpoint_file: Path) -> None:
        self.store.update(
            self.job_id,
            status="recording",
            status_message="Recording healthy; two-minute test passed",
            checkpoint_file=str(checkpoint_file),
        )
        self.hub.local(f"Two-minute check passed: {game.label}", "The full recording is continuing.")
        self._email().checkpoint_ready(game, event, checkpoint_file)

    def recording_finalizing(self, game: Game, event: HudlEvent) -> None:
        self.store.update(
            self.job_id,
            status="finalizing",
            status_message="Stream ended; validating and saving the final MP4",
        )

    def recording_failed(self, game: Game, event_id: str | None, error: str) -> None:
        self.store.update(self.job_id, status="failed", status_message=error, error=error)
        self.hub.local(f"Recording needs attention: {game.label}", error)
        self._email().recording_failed(game, event_id, error)


def human_size(byte_count: int) -> str:
    value = float(byte_count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def event_from_snapshot(adapter: object, event_id: str, label: str) -> HudlEvent:
    snapshot = adapter.snapshot(event_id)
    return HudlEvent(
        event_id=event_id,
        title=snapshot.title or label,
        scheduled_at=snapshot.scheduled_at,
        status=snapshot.status,
        require_login=bool(getattr(adapter, "supports_login", False)),
        provider=str(getattr(adapter, "provider", "hudl")),
    )


class PortableWorker:
    def __init__(self, store: JobStore | None = None) -> None:
        self.store = store or JobStore()
        self.stop_event = threading.Event()
        self.hub = NotificationHub(self.store.root / "email-notifications.json")
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="recording")
        self.active: dict[str, tuple[Future[RecordingResult], threading.Event]] = {}
        self.safety_warning_sent = False
        self.last_safety_check = 0.0

    def run(self) -> None:
        self._install_signal_handlers()
        LOG.info("Portable recorder worker started")
        try:
            while not self.stop_event.is_set():
                jobs = {str(job["id"]): job for job in self.store.jobs()}
                self._handle_active(jobs)
                self._launch_due_jobs(jobs)
                self._check_unattended_safety(jobs.values())
                self.stop_event.wait(10)
        finally:
            for _future, cancel_event in self.active.values():
                cancel_event.set()
            self.executor.shutdown(wait=True, cancel_futures=False)
            LOG.info("Portable recorder worker stopped")

    def _handle_active(self, jobs: dict[str, dict[str, Any]]) -> None:
        for job_id, (future, cancel_event) in list(self.active.items()):
            job = jobs.get(job_id)
            if job is None or job.get("status") == "cancelled":
                cancel_event.set()
            if future.done():
                try:
                    result = future.result()
                    if result.status == "stopped" and job and job.get("status") != "cancelled":
                        self.store.update(job_id, status="scheduled", status_message="Worker stopped; ready to resume")
                except Exception as exc:
                    LOG.exception("Unhandled worker error for job %s", job_id)
                    self.store.update(job_id, status="failed", status_message=str(exc), error=str(exc))
                del self.active[job_id]
                continue
            if job and job.get("status") == "recording":
                self._heartbeat(job)

    def _launch_due_jobs(self, jobs: dict[str, dict[str, Any]]) -> None:
        now = datetime.now().astimezone()
        for job_id, job in jobs.items():
            if job_id in self.active or job.get("status") not in {"scheduled", "monitoring"}:
                continue
            try:
                kickoff = datetime.fromisoformat(str(job["kickoff_at"]))
                early = timedelta(minutes=int(job.get("start_early_minutes", 15)))
            except (KeyError, TypeError, ValueError):
                self.store.update(job_id, status="failed", status_message="Invalid kickoff date or time")
                continue
            if now < kickoff - early:
                continue
            if now > kickoff + timedelta(hours=6):
                self.store.update(job_id, status="missed", status_message="Kickoff was more than six hours ago")
                continue
            cancel_event = threading.Event()
            self.store.update(job_id, status="monitoring", status_message="Resolving link and waiting for the live feed")
            future = self.executor.submit(self._run_job, job_id, cancel_event)
            self.active[job_id] = (future, cancel_event)

    def _run_job(self, job_id: str, cancel_event: threading.Event) -> RecordingResult:
        job = self.store.get(job_id)
        if job is None:
            return RecordingResult(job_id, None, "stopped", error="Job was removed")
        kickoff = datetime.fromisoformat(str(job["kickoff_at"]))
        timezone_name = str(job.get("timezone") or local_timezone_name())
        local_kickoff = kickoff.astimezone(ZoneInfo(timezone_name))
        game = Game(
            row=0,
            game_date=local_kickoff.date(),
            home_team=str(job["home_team"]),
            away_team=str(job["away_team"]),
            kickoff=local_kickoff.time().replace(tzinfo=None),
            livestream_url=str(job["url"]),
            timezone=timezone_name,
        )
        adapter = adapter_for_url(game.livestream_url)
        notifier = JobNotifier(job_id, self.store, self.hub)
        event: HudlEvent | None = None
        try:
            saved_event_id = str(job.get("event_id") or "")
            resolve_deadline = kickoff + timedelta(minutes=90)
            while event is None:
                try:
                    event = (
                        event_from_snapshot(adapter, saved_event_id, game.label)
                        if saved_event_id
                        else adapter.resolve(game)
                    )
                except UnsupportedProvider:
                    raise
                except ProviderError as exc:
                    retryable = any(
                        phrase in str(exc)
                        for phrase in (
                            "No upcoming Hudl broadcasts found",
                            "Could not confidently match a Hudl event",
                            "Could not fetch",
                        )
                    )
                    if not retryable or datetime.now().astimezone() >= resolve_deadline:
                        raise
                    LOG.warning("%s: event not published yet; retrying: %s", game.label, exc)
                    self.store.update(
                        job_id,
                        status="monitoring",
                        status_message="Official event is not published yet; retrying automatically",
                    )
                    if cancel_event.wait(30):
                        return RecordingResult(job_id, None, "stopped")
            self.store.update(
                job_id,
                event_id=event.event_id,
                provider=event.provider,
                parts_key=f"{event.provider}-{event.event_id}",
                provider_kickoff=event.scheduled_at.isoformat(),
                status="monitoring",
                status_message=f"Watching {getattr(adapter, 'provider_name', event.provider.title())} event {event.event_id} for the live feed",
            )
            settings = RecorderSettings(
                output_dir=Path(str(job["output_dir"])),
                poll_seconds=10,
                start_early_minutes=int(job.get("start_early_minutes", 15)),
                monitor_immediately=bool(job.get("start_now", False)),
            )
            recorder = GameRecorder(adapter, settings, notifier)
            result = recorder.record(game, cancel_event, resolved_event=event)
            if result.status == "already-recorded":
                self.store.update(
                    job_id,
                    status="completed",
                    status_message="Validated MP4 already exists",
                    output_file=result.output_file,
                    completed_at=iso_now(),
                )
            return result
        except Exception as exc:
            LOG.exception("Could not run portable recording job %s", job_id)
            notifier.recording_failed(game, event.event_id if event else None, str(exc))
            return RecordingResult(job_id, event.event_id if event else None, "failed", error=str(exc))

    def _heartbeat(self, job: dict[str, Any]) -> None:
        event_id = str(job.get("event_id") or "")
        if not event_id:
            return
        interval_minutes = self.hub.email().health_interval_minutes
        try:
            previous = datetime.fromisoformat(str(job.get("heartbeat_at") or job["recording_started_at"]))
        except (KeyError, TypeError, ValueError):
            previous = datetime.now().astimezone() - timedelta(minutes=interval_minutes + 1)
        if datetime.now().astimezone() - previous < timedelta(minutes=interval_minutes):
            return
        parts_key = str(job.get("parts_key") or event_id)
        parts_dir = Path(str(job["output_dir"])) / ".parts" / parts_key
        parts = [path for path in parts_dir.glob("part-*.ts") if path.is_file()]
        if not parts:
            return
        newest = max(path.stat().st_mtime for path in parts)
        label = f"{job['home_team']} vs. {job['away_team']}"
        provider_key = str(job.get("provider") or "hudl")
        provider = {"flocollege": "FloCollege", "boxcast": "BoxCast"}.get(provider_key, provider_key.title())
        if time.time() - newest <= 120:
            self.hub.healthy(label, event_id, sum(path.stat().st_size for path in parts), provider)
        else:
            self.hub.stalled(label, event_id, provider)
        self.store.update(str(job["id"]), heartbeat_at=iso_now())

    def _check_unattended_safety(self, jobs: Any) -> None:
        now = time.monotonic()
        if now - self.last_safety_check < 60:
            return
        self.last_safety_check = now
        pending = any(job.get("status") in {"scheduled", "monitoring", "recording"} for job in jobs)
        if not pending:
            self.safety_warning_sent = False
            return
        problems: list[str] = []
        if power_adapter_connected() is False:
            problems.append("The Mac is running on battery. Connect its power adapter.")
        if macbook_lid_open() is False:
            problems.append("The MacBook lid is closed. Open it to avoid suspended recording.")
        if not sleep_prevention_active():
            problems.append("The Soccer Recorder sleep-prevention assertion is not active.")
        if problems and not self.safety_warning_sent:
            title = "Soccer Recorder readiness warning"
            body = " ".join(problems)
            self.hub.local(title, body)
            self.hub.email().send(title, body)
            LOG.warning("Unattended readiness warning: %s", body)
            self.safety_warning_sent = True
        elif not problems and self.safety_warning_sent:
            title = "Soccer Recorder readiness restored"
            body = "Power and sleep prevention are ready for unattended recording. Keep the MacBook lid open."
            self.hub.local(title, body)
            self.hub.email().send(title, body)
            LOG.info("Unattended readiness restored")
            self.safety_warning_sent = False

    def _install_signal_handlers(self) -> None:
        def stop(_signum: int, _frame: object) -> None:
            self.stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)


def configure_worker_logging() -> None:
    root = support_dir()
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
        handlers=[logging.FileHandler(root / "recorder.log", encoding="utf-8")],
    )


def worker_main() -> int:
    configure_worker_logging()
    PortableWorker().run()
    return 0


def worker_command(entry_script: Path | None = None) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    if entry_script is None:
        raise ValueError("entry_script is required outside a packaged app")
    return [sys.executable, str(entry_script.resolve()), "--worker"]


def agent_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


def worker_is_running() -> bool:
    completed = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{AGENT_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and "state = running" in completed.stdout


def install_worker(command: list[str]) -> tuple[bool, str]:
    """Install and start the per-user background worker."""
    if worker_is_running():
        return True, "Background recorder is running"
    root = support_dir()
    root.mkdir(parents=True, exist_ok=True)
    plist_path = agent_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": AGENT_LABEL,
        "ProgramArguments": ["/usr/bin/caffeinate", "-ims", *command],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "WorkingDirectory": str(root),
        "StandardOutPath": str(root / "worker.out.log"),
        "StandardErrorPath": str(root / "worker.err.log"),
    }
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle)
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["/bin/launchctl", "bootout", f"{domain}/{AGENT_LABEL}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    completed = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return False, completed.stderr.strip() or "macOS could not start the background recorder"
    return True, "Background recorder installed and running"
