#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from soccer_recorder.flo import FloCollegeAdapter
from soccer_recorder.hudl import HudlAdapter
from soccer_recorder.keychain import KeychainError, load_keychain_secret, save_keychain_secret
from soccer_recorder.models import Game
from soccer_recorder.notifications import EmailConfig, EmailNotifier
from soccer_recorder.portable import (
    KEYCHAIN_SERVICE,
    JobStore,
    default_output_dir,
    install_worker,
    iso_now,
    preload_frozen_runtime,
    support_dir,
    worker_command,
    worker_is_running,
    worker_main,
)
from soccer_recorder.providers import adapter_for_url, provider_key_for_url
from soccer_recorder.readiness import MacReadiness, check_mac_readiness
from soccer_recorder.recorder import GameRecorder, RecorderSettings
from soccer_recorder.xlsx_schedule import XlsxScheduleReader, download_google_sheet


APP_TITLE = "Soccer Recorder"
MAROON = "#8C1D40"
GREEN = "#18794E"
INK = "#17212B"
MUTED = "#617080"
SURFACE = "#F4F6F8"
PITTSBURGH_TIMEZONE = "America/New_York"
MONITOR_EARLY_MINUTES = 5


class RecorderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.store = JobStore()
        self.timezone = PITTSBURGH_TIMEZONE
        self.output_dir = tk.StringVar(value=str(default_output_dir()))
        self.highlighted_only = tk.BooleanVar(value=True)
        self.url = tk.StringVar()
        self.home_team = tk.StringVar()
        self.away_team = tk.StringVar()
        now = datetime.now(ZoneInfo(self.timezone))
        self.game_date = tk.StringVar(value=now.strftime("%Y-%m-%d"))
        self.game_time = tk.StringVar(value=now.strftime("%H:%M"))
        self.worker_status = tk.StringVar(value="Checking background recorder…")
        self.form_status = tk.StringVar(value="Paste a Hudl/BlueFrame, FloCollege, or BoxCast event link to begin.")
        signed_in = FloCollegeAdapter().signed_in_email
        self.flo_status = tk.StringVar(
            value=f"FloSports: signed in as {signed_in}" if signed_in else "FloSports: not signed in"
        )
        self.testing = False
        self._build_window()
        self._refresh()

    def _build_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("980x790")
        self.root.minsize(880, 700)
        self.root.configure(bg=SURFACE)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=SURFACE)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=SURFACE, foreground=INK, font=("Helvetica Neue", 13))
        style.configure("Title.TLabel", font=("Helvetica Neue", 27, "bold"), foreground=INK)
        style.configure("Subtitle.TLabel", font=("Helvetica Neue", 13), foreground=MUTED)
        style.configure("Card.TLabel", background="white", foreground=INK, font=("Helvetica Neue", 12))
        style.configure("Field.TLabel", background="white", foreground=MUTED, font=("Helvetica Neue", 11, "bold"))
        style.configure("Accent.TButton", font=("Helvetica Neue", 12, "bold"), foreground="white", background=MAROON)
        style.map("Accent.TButton", background=[("active", "#6F1733")])
        style.configure("Good.TLabel", background=SURFACE, foreground=GREEN, font=("Helvetica Neue", 11, "bold"))
        style.configure("Warning.TLabel", background=SURFACE, foreground="#A14A00", font=("Helvetica Neue", 11, "bold"))
        style.configure("Treeview", rowheight=30, font=("Helvetica Neue", 11), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Helvetica Neue", 11, "bold"))

        outer = ttk.Frame(self.root, padding=(24, 20))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="Soccer Recorder", style="Title.TLabel").pack(side="left")
        self.worker_status_label = ttk.Label(header, textvariable=self.worker_status, style="Good.TLabel")
        self.worker_status_label.pack(side="right", pady=8)
        ttk.Label(
            outer,
            text="Manual or spreadsheet scheduling · all times are Pittsburgh time · monitoring starts 5 minutes early.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(0, 14))

        card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        card.pack(fill="x")
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="STREAM URL", style="Field.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(card, textvariable=self.url, font=("Helvetica Neue", 12)).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(5, 13)
        )
        ttk.Label(card, text="HOME TEAM", style="Field.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Label(card, text="AWAY TEAM", style="Field.TLabel").grid(row=2, column=1, sticky="w", padx=(12, 0))
        ttk.Entry(card, textvariable=self.home_team).grid(row=3, column=0, sticky="ew", pady=(5, 13))
        ttk.Entry(card, textvariable=self.away_team).grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=(5, 13))

        timing = ttk.Frame(card, style="Card.TFrame")
        timing.grid(row=4, column=0, columnspan=2, sticky="ew")
        for index in range(4):
            timing.columnconfigure(index, weight=1 if index < 3 else 0)
        ttk.Label(timing, text="DATE (YYYY-MM-DD)", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(timing, text="KICKOFF (24-HOUR)", style="Field.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(timing, text="MONITOR EARLY", style="Field.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Entry(timing, textvariable=self.game_date, width=15).grid(row=1, column=0, sticky="ew", pady=(5, 13))
        ttk.Entry(timing, textvariable=self.game_time, width=10).grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(5, 13))
        ttk.Label(timing, text="5 minutes (fixed)", style="Card.TLabel").grid(
            row=1, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=(5, 13)
        )

        ttk.Label(card, text="SAVE RECORDINGS TO", style="Field.TLabel").grid(row=5, column=0, columnspan=2, sticky="w")
        output_row = ttk.Frame(card, style="Card.TFrame")
        output_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(5, 14))
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_dir, state="readonly").grid(row=0, column=0, sticky="ew")
        ttk.Button(output_row, text="Choose…", command=self._choose_output).grid(row=0, column=1, padx=(8, 0))

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=7, column=0, columnspan=2, sticky="ew")
        ttk.Button(actions, text="Schedule Recording", style="Accent.TButton", command=self._schedule).pack(side="left")
        ttk.Button(actions, text="Start Monitoring Now", command=self._start_now).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Test 20 Seconds", command=self._test_recording).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Email Settings", command=self._email_settings).pack(side="right")
        ttk.Button(actions, text="FloSports Sign In…", command=self._flo_sign_in).pack(side="right", padx=(0, 8))

        batch = ttk.Frame(card, style="Card.TFrame")
        batch.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Label(batch, text="BATCH SCHEDULE", style="Field.TLabel").pack(side="left")
        ttk.Button(batch, text="Import Excel…", command=self._import_excel).pack(side="left", padx=(12, 0))
        ttk.Button(batch, text="Import Google Sheet…", command=self._import_google_sheet).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(batch, text="Highlighted only", variable=self.highlighted_only).pack(side="left", padx=(12, 0))
        ttk.Label(batch, text="Checked: green rows only · Unchecked: all complete rows", style="Card.TLabel").pack(
            side="left", padx=(12, 0)
        )

        ttk.Label(card, textvariable=self.flo_status, style="Field.TLabel").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        ttk.Label(outer, textvariable=self.form_status, style="Subtitle.TLabel").pack(anchor="w", pady=(10, 16))

        list_header = ttk.Frame(outer)
        list_header.pack(fill="x")
        ttk.Label(list_header, text="Scheduled and recent games", font=("Helvetica Neue", 16, "bold")).pack(side="left")
        ttk.Button(list_header, text="Open Recordings", command=self._open_recordings).pack(side="right")
        ttk.Button(list_header, text="Check Readiness", command=self._show_readiness).pack(side="right", padx=(0, 6))
        ttk.Button(list_header, text="Retry", command=self._retry_selected).pack(side="right", padx=(0, 6))
        ttk.Button(list_header, text="Cancel", command=self._cancel_selected).pack(side="right", padx=(0, 6))
        ttk.Button(list_header, text="Remove", command=self._delete_selected).pack(side="right", padx=(0, 6))

        columns = ("game", "kickoff", "status", "details")
        self.tree = ttk.Treeview(outer, columns=columns, show="headings", height=8)
        self.tree.heading("game", text="Game")
        self.tree.heading("kickoff", text="Kickoff")
        self.tree.heading("status", text="Status")
        self.tree.heading("details", text="Details")
        self.tree.column("game", width=235)
        self.tree.column("kickoff", width=155)
        self.tree.column("status", width=105)
        self.tree.column("details", width=360)
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        self.tree.bind("<Double-1>", self._open_selected)
        self.tree.bind("<BackSpace>", self._delete_selected)
        self.tree.bind("<Delete>", self._delete_selected)
        ttk.Label(
            outer,
            text="Hudl/BlueFrame, authorized FloCollege, and public BoxCast streams. Keep the Mac powered, online, and the lid open.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(10, 0))

    def _parse_form(self, start_now: bool = False) -> dict[str, object]:
        url = self.url.get().strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Paste a complete http:// or https:// stream URL")
        home = self.home_team.get().strip()
        away = self.away_team.get().strip()
        if not home or not away:
            raise ValueError("Enter both team names so the recording has a useful filename")
        if start_now:
            kickoff = datetime.now(ZoneInfo(self.timezone))
            early = 0
        else:
            kickoff = datetime.strptime(
                f"{self.game_date.get().strip()} {self.game_time.get().strip()}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=ZoneInfo(self.timezone))
            early = MONITOR_EARLY_MINUTES
        output = Path(self.output_dir.get()).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        provider = provider_key_for_url(url)
        if provider == "flocollege" and not FloCollegeAdapter._event_id_from_url(url):
            raise ValueError("Paste the FloCollege event page URL containing /live/ and its event number")
        return {
            "id": str(uuid.uuid4()),
            "url": url,
            "provider": provider,
            "home_team": home,
            "away_team": away,
            "kickoff_at": kickoff.isoformat(),
            "timezone": self.timezone,
            "start_early_minutes": early,
            "start_now": start_now,
            "output_dir": str(output.resolve()),
            "status": "scheduled",
            "status_message": "Waiting for monitoring window",
            "created_at": iso_now(),
            "updated_at": iso_now(),
        }

    def _add_job(self, start_now: bool) -> None:
        try:
            job = self._parse_form(start_now)
            if job["provider"] == "flocollege":
                self._ensure_flo_login()
            self.store.add(job)
            ok, detail = install_worker(worker_command(Path(__file__)))
            if not ok:
                self.store.update(str(job["id"]), status="failed", status_message=detail)
                raise RuntimeError(detail)
            self.form_status.set(f"{job['home_team']} vs. {job['away_team']} scheduled. {detail}.")
            self._refresh_jobs()
            self.root.after(4000, self._alert_if_not_ready)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self.root)

    def _schedule(self) -> None:
        self._add_job(False)

    def _start_now(self) -> None:
        self._add_job(True)

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir.get(), parent=self.root)
        if selected:
            self.output_dir.set(selected)

    def _import_excel(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose an Excel schedule",
            filetypes=(("Excel workbooks", "*.xlsx"),),
            parent=self.root,
        )
        if not selected:
            return
        try:
            self._schedule_workbook(Path(selected), Path(selected).name)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self.root)

    def _import_google_sheet(self) -> None:
        sheet_url = simpledialog.askstring(
            "Import Google Sheet",
            "Paste the Google Sheets sharing link:\n\nThe Sheet must be shared as 'Anyone with the link'.",
            parent=self.root,
        )
        if not sheet_url:
            return
        self.form_status.set("Downloading the Google Sheet as an Excel workbook…")
        self.root.update_idletasks()
        try:
            with tempfile.TemporaryDirectory(prefix="soccer-recorder-sheet-") as directory:
                workbook = download_google_sheet(sheet_url, Path(directory) / "schedule.xlsx")
                self._schedule_workbook(workbook, "Google Sheet")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self.root)

    def _schedule_workbook(self, workbook: Path, source_name: str) -> None:
        reader = XlsxScheduleReader(workbook, timezone=PITTSBURGH_TIMEZONE)
        selected_only = bool(self.highlighted_only.get())
        games = reader.read_games(selected_only=selected_only)
        selection_note = "green-highlighted" if selected_only else "complete"
        if not games:
            if reader.link_issues:
                issue_lines = [
                    f"• Row {row}: {reason}\n  {url or '(no link)'}"
                    for row, url, reason in reader.link_issues[:8]
                ]
                messagebox.showerror(
                    APP_TITLE,
                    f"No {selection_note} games can be scheduled because their links are invalid.\n\n"
                    + "\n".join(issue_lines),
                    parent=self.root,
                )
                return
            if selected_only:
                raise RuntimeError(
                    "No complete green-highlighted rows were found. Uncheck 'Highlighted only' to import all complete rows."
                )
            raise RuntimeError("No complete schedule rows were found in the spreadsheet")

        jobs, skipped, invalid_links = self._jobs_for_games(games, source_name)
        invalid_links = [*reader.link_issues, *invalid_links]
        if invalid_links:
            issue_lines = [
                f"• Row {row}: {reason}\n  {url or '(no link)'}"
                for row, url, reason in invalid_links[:8]
            ]
            if len(invalid_links) > 8:
                issue_lines.append(f"• …and {len(invalid_links) - 8} more invalid link(s)")
            if not jobs:
                messagebox.showerror(
                    APP_TITLE,
                    "No games can be scheduled because the matching spreadsheet rows have invalid links.\n\n"
                    + "\n".join(issue_lines),
                    parent=self.root,
                )
                return
            skip_bad_links = messagebox.askyesno(
                "Skip invalid links?",
                "The following spreadsheet link(s) cannot be scheduled:\n\n"
                + "\n".join(issue_lines)
                + f"\n\nSkip only these {len(invalid_links)} row(s) and continue with the other {len(jobs)} game(s)?\n"
                "The original spreadsheet will not be changed.",
                parent=self.root,
            )
            if not skip_bad_links:
                self.form_status.set("Spreadsheet import cancelled; no games were added.")
                return
        if not jobs:
            messagebox.showinfo(
                APP_TITLE,
                f"All {len(games)} matching spreadsheet rows are already scheduled.",
                parent=self.root,
            )
            return
        preview_lines = [
            f"• {job['kickoff_at'][:10]} {datetime.fromisoformat(str(job['kickoff_at'])):%I:%M %p} — "
            f"{job['home_team']} vs. {job['away_team']}"
            for job in jobs[:8]
        ]
        if len(jobs) > 8:
            preview_lines.append(f"• …and {len(jobs) - 8} more")
        skipped_notes = []
        if invalid_links:
            skipped_notes.append(f"{len(invalid_links)} invalid-link row(s) will be skipped.")
        if skipped:
            skipped_notes.append(f"{skipped} duplicate row(s) will be skipped.")
        skip_note = f"\n\n{' '.join(skipped_notes)}" if skipped_notes else ""
        confirmed = messagebox.askyesno(
            APP_TITLE,
            "\n".join(
                (
                    f"Found {len(jobs)} {selection_note} game row(s) in {source_name}.",
                    "All kickoff times will be treated as Pittsburgh time.",
                    "Monitoring will start 5 minutes before each kickoff.",
                    "",
                    *preview_lines,
                )
            )
            + skip_note
            + "\n\nSchedule all of these games?",
            parent=self.root,
        )
        if not confirmed:
            self.form_status.set("Spreadsheet import cancelled; no games were added.")
            return
        if any(job["provider"] == "flocollege" for job in jobs):
            self._ensure_flo_login()
        self.store.add_many(jobs)
        ok, detail = install_worker(worker_command(Path(__file__)))
        if not ok:
            for job in jobs:
                self.store.update(str(job["id"]), status="failed", status_message=detail)
            raise RuntimeError(detail)
        invalid_note = f" Skipped {len(invalid_links)} invalid link(s)." if invalid_links else ""
        self.form_status.set(f"Scheduled {len(jobs)} spreadsheet game(s).{invalid_note} {detail}.")
        self._refresh_jobs()
        self.root.after(4000, self._alert_if_not_ready)

    def _jobs_for_games(
        self,
        games: list[Game],
        source_name: str,
    ) -> tuple[list[dict[str, object]], int, list[tuple[int, str, str]]]:
        existing = {
            (
                str(job.get("url", "")).rstrip("/"),
                str(job.get("kickoff_at", "")),
                str(job.get("home_team", "")).casefold(),
                str(job.get("away_team", "")).casefold(),
            )
            for job in self.store.jobs()
            if job.get("status") != "cancelled"
        }
        output = Path(self.output_dir.get()).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        jobs: list[dict[str, object]] = []
        skipped = 0
        invalid_links: list[tuple[int, str, str]] = []
        for game in games:
            kickoff = datetime.combine(game.game_date, game.kickoff, ZoneInfo(PITTSBURGH_TIMEZONE))
            parsed_url = urlparse(game.livestream_url)
            if parsed_url.scheme.casefold() not in {"http", "https"} or not parsed_url.netloc:
                invalid_links.append((game.row, game.livestream_url, "Link must be a complete http:// or https:// URL"))
                continue
            provider = provider_key_for_url(game.livestream_url)
            if provider == "flocollege" and not FloCollegeAdapter._event_id_from_url(game.livestream_url):
                invalid_links.append(
                    (game.row, game.livestream_url, "FloSports link is missing its /live/ event number")
                )
                continue
            signature = (
                game.livestream_url.rstrip("/"),
                kickoff.isoformat(),
                game.home_team.casefold(),
                game.away_team.casefold(),
            )
            if signature in existing:
                skipped += 1
                continue
            existing.add(signature)
            jobs.append(
                {
                    "id": str(uuid.uuid4()),
                    "url": game.livestream_url,
                    "provider": provider,
                    "home_team": game.home_team,
                    "away_team": game.away_team,
                    "kickoff_at": kickoff.isoformat(),
                    "timezone": PITTSBURGH_TIMEZONE,
                    "start_early_minutes": MONITOR_EARLY_MINUTES,
                    "start_now": False,
                    "output_dir": str(output.resolve()),
                    "status": "scheduled",
                    "status_message": f"Imported from {source_name}, row {game.row}; waiting for monitoring window",
                    "source": source_name,
                    "source_row": game.row,
                    "created_at": iso_now(),
                    "updated_at": iso_now(),
                }
            )
        return jobs, skipped, invalid_links

    def _test_recording(self) -> None:
        if self.testing:
            return
        try:
            job = self._parse_form(True)
            if job["provider"] == "flocollege":
                self._ensure_flo_login()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self.root)
            return
        self.testing = True
        self.form_status.set("Resolving the link and recording a 20-second test…")

        def work() -> None:
            try:
                kickoff = datetime.fromisoformat(str(job["kickoff_at"]))
                game = Game(
                    row=0,
                    game_date=kickoff.date(),
                    home_team=str(job["home_team"]),
                    away_team=str(job["away_team"]),
                    kickoff=kickoff.time().replace(tzinfo=None),
                    livestream_url=str(job["url"]),
                    timezone=str(job["timezone"]),
                )
                adapter = adapter_for_url(str(job["url"]))
                event = adapter.resolve(game)
                recorder = GameRecorder(adapter, RecorderSettings(output_dir=Path(str(job["output_dir"]))))
                output = recorder.smoke_test(event.event_id, 20)
                self.root.after(0, lambda: self._test_finished(True, str(output)))
            except Exception as exc:
                self.root.after(0, lambda detail=str(exc): self._test_finished(False, detail))

        threading.Thread(target=work, name="smoke-test", daemon=True).start()

    def _ensure_flo_login(self, force_prompt: bool = False) -> str:
        adapter = FloCollegeAdapter()
        existing = adapter.session_store.email or ""
        if not force_prompt and adapter.signed_in_email:
            try:
                email = adapter.validate_session()
                self.flo_status.set(f"FloSports: signed in as {email}")
                return email
            except Exception:
                pass
        email = simpledialog.askstring(
            "FloSports Sign In",
            "FloSports account email (FloFC and FloCollege use the same account):",
            initialvalue=existing,
            parent=self.root,
        )
        if not email:
            raise RuntimeError("FloSports sign-in was cancelled; the recording was not scheduled")
        password = simpledialog.askstring(
            "FloSports Sign In",
            "FloSports password:\nSaved securely in macOS Keychain on this Mac for automatic sign-in.\n"
            "It is never placed in the app, schedule, or logs.",
            show="•",
            parent=self.root,
        )
        if not password:
            raise RuntimeError("FloSports sign-in was cancelled; the recording was not scheduled")
        self.form_status.set("Signing in to FloSports…")
        self.root.update_idletasks()
        signed_in = adapter.login(email, password)
        adapter.validate_session()
        self.flo_status.set(f"FloSports: signed in as {signed_in}")
        self.form_status.set("FloSports sign-in succeeded. The background recorder can sign in again automatically.")
        return signed_in

    def _flo_sign_in(self) -> None:
        try:
            email = self._ensure_flo_login(force_prompt=True)
            messagebox.showinfo(
                APP_TITLE,
                f"Signed in as {email}.\n\nThe password and reusable session are protected by macOS Keychain on this Mac.",
                parent=self.root,
            )
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self.root)

    def _test_finished(self, passed: bool, detail: str) -> None:
        self.testing = False
        if passed:
            self.form_status.set(f"Test passed: {detail}")
            messagebox.showinfo(APP_TITLE, f"Video and audio test passed.\n\n{detail}", parent=self.root)
        else:
            self.form_status.set("Test failed; check the link and whether the feed is currently playable.")
            messagebox.showerror(APP_TITLE, detail, parent=self.root)

    def _email_settings(self) -> None:
        config_path = support_dir() / "email-notifications.json"
        existing = ""
        existing_interval = 15
        try:
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))
            existing = str(saved_config.get("sender", ""))
            existing_interval = EmailNotifier(
                EmailConfig(
                    sender=existing,
                    recipient=str(saved_config.get("recipient", existing)),
                    health_interval_minutes=saved_config.get("health_interval_minutes", 15),
                )
            ).health_interval_minutes
        except (AttributeError, FileNotFoundError, json.JSONDecodeError, TypeError):
            pass
        email = simpledialog.askstring(
            "Email notifications",
            "Gmail address (Cancel to leave unchanged):",
            initialvalue=existing,
            parent=self.root,
        )
        if not email:
            return
        email = email.strip()
        if not email:
            return
        interval = simpledialog.askinteger(
            "Email notifications",
            "How often should a successful active recording email be sent?\n\n"
            "Enter a number of minutes from 1 to 180. Start, finish, checkpoint, and failure emails remain immediate.",
            initialvalue=existing_interval,
            minvalue=1,
            maxvalue=180,
            parent=self.root,
        )
        if interval is None:
            return
        saved_password = load_keychain_secret(email, KEYCHAIN_SERVICE) is not None
        password = simpledialog.askstring(
            "Email notifications",
            "Google 16-character app password:\nStored only in macOS Keychain.\n\n"
            + ("Leave blank to keep the password already saved in Keychain." if saved_password else "A password is required the first time."),
            show="•",
            parent=self.root,
        )
        if password is None:
            return
        if not password and not saved_password:
            messagebox.showerror(APP_TITLE, "No Gmail app password is saved for that address.", parent=self.root)
            return
        if password:
            password = "".join(password.split())
            try:
                save_keychain_secret(email, KEYCHAIN_SERVICE, password)
            except KeychainError as exc:
                messagebox.showerror(APP_TITLE, str(exc), parent=self.root)
                return
        config = EmailConfig(
            sender=email,
            recipient=email,
            keychain_service=KEYCHAIN_SERVICE,
            health_interval_minutes=interval,
        )
        notifier = EmailNotifier(config)
        if notifier.send("Soccer Recorder test", "Email notifications are configured and working."):
            config_path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
            messagebox.showinfo(
                APP_TITLE,
                f"Test email sent successfully.\n\nActive recording updates will arrive every {interval} minute(s).",
                parent=self.root,
            )
        else:
            messagebox.showerror(
                APP_TITLE,
                "The test email failed.\n\n" + (notifier.last_error or "Check the Gmail App Password."),
                parent=self.root,
            )

    def _selected_job(self) -> dict[str, object] | None:
        selection = self.tree.selection()
        return self.store.get(selection[0]) if selection else None

    def _cancel_selected(self) -> None:
        job = self._selected_job()
        if job:
            self.store.update(str(job["id"]), status="cancelled", status_message="Cancelled by user")
            self._refresh_jobs()

    def _delete_selected(self, _event: object = None) -> str:
        job = self._selected_job()
        if not job:
            return "break"
        status = str(job.get("status", "unknown"))
        if status in {"monitoring", "recording"}:
            consequence = (
                "This will stop the active task. Any video already captured will remain in the hidden .parts backup folder."
            )
        elif status == "scheduled":
            consequence = "This will remove the task, so it will not run at kickoff."
        else:
            consequence = "This removes only the row. Any saved recording files will remain untouched."
        label = f"{job.get('home_team', '')} vs. {job.get('away_team', '')}"
        if not messagebox.askyesno(
            "Remove scheduled game",
            f"Remove {label} from Soccer Recorder?\n\n{consequence}",
            parent=self.root,
        ):
            return "break"
        removed = self.store.delete(str(job["id"]))
        if removed:
            self.form_status.set(f"Removed {label} from the scheduler. Recording files were not deleted.")
            self._refresh_jobs()
        return "break"

    def _retry_selected(self) -> None:
        job = self._selected_job()
        if job:
            self.store.update(str(job["id"]), status="scheduled", status_message="Retry requested", error=None)
            install_worker(worker_command(Path(__file__)))
            self._refresh_jobs()
            self.root.after(4000, self._alert_if_not_ready)

    def _open_recordings(self) -> None:
        Path(self.output_dir.get()).expanduser().mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["/usr/bin/open", self.output_dir.get()])

    def _open_selected(self, _event: object = None) -> None:
        job = self._selected_job()
        if not job:
            return
        output = job.get("output_file") or job.get("checkpoint_file")
        if output and Path(str(output)).exists():
            subprocess.Popen(["/usr/bin/open", str(output)])
        else:
            messagebox.showinfo(APP_TITLE, str(job.get("status_message", "No recording is ready yet.")), parent=self.root)

    def _refresh_jobs(self) -> None:
        selected = self.tree.selection()
        for item in self.tree.get_children():
            self.tree.delete(item)
        jobs = sorted(self.store.jobs(), key=lambda job: str(job.get("kickoff_at", "")), reverse=True)
        for job in jobs:
            try:
                kickoff = datetime.fromisoformat(str(job["kickoff_at"])).astimezone().strftime("%b %d, %I:%M %p")
            except (KeyError, ValueError):
                kickoff = "Invalid"
            self.tree.insert(
                "",
                "end",
                iid=str(job["id"]),
                values=(
                    f"{job.get('home_team', '')} vs. {job.get('away_team', '')}",
                    kickoff,
                    str(job.get("status", "unknown")).title(),
                    str(job.get("status_message", "")),
                ),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def _refresh(self) -> None:
        self._update_readiness_status()
        self._refresh_jobs()
        self.root.after(5000, self._refresh)

    def _readiness(self) -> MacReadiness:
        return check_mac_readiness(worker_is_running())

    def _update_readiness_status(self) -> MacReadiness:
        readiness = self._readiness()
        if not readiness.worker_running:
            self.worker_status.set("○ Starts when a game is scheduled")
            self.worker_status_label.configure(style="Good.TLabel")
        elif readiness.ready:
            self.worker_status.set("● Recorder running · Sleep protected · Powered")
            self.worker_status_label.configure(style="Good.TLabel")
        else:
            if readiness.power_connected is False:
                warning = "Connect charger"
            elif not readiness.sleep_prevention_active:
                warning = "Sleep protection inactive"
            elif readiness.lid_open is False:
                warning = "Open MacBook lid"
            else:
                warning = "Check readiness"
            self.worker_status.set(f"⚠ Recorder warning · {warning}")
            self.worker_status_label.configure(style="Warning.TLabel")
        return readiness

    def _show_readiness(self) -> None:
        readiness = self._update_readiness_status()
        if readiness.ready:
            messagebox.showinfo("Mac readiness passed", readiness.details(), parent=self.root)
        else:
            messagebox.showwarning("Mac readiness warning", readiness.details(), parent=self.root)

    def _alert_if_not_ready(self) -> None:
        readiness = self._update_readiness_status()
        if not readiness.ready:
            messagebox.showwarning("Fix before leaving the Mac", readiness.details(), parent=self.root)


def main() -> int:
    preload_frozen_runtime()
    if "--worker" in sys.argv:
        return worker_main()
    if "--self-test" in sys.argv:
        test_root = support_dir() / "self-test-output"
        recorder = GameRecorder(HudlAdapter(), RecorderSettings(output_dir=test_root))
        for tool in (recorder.ffmpeg, recorder.ffprobe):
            if not tool or subprocess.run([tool, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                return 2
        JobStore().jobs()
        return 0
    if "--smoke-test-event" in sys.argv:
        try:
            event_id = sys.argv[sys.argv.index("--smoke-test-event") + 1]
        except (ValueError, IndexError):
            return 2
        recorder = GameRecorder(HudlAdapter(), RecorderSettings(output_dir=support_dir() / "self-test-output"))
        recorder.smoke_test(event_id, 8)
        return 0
    if "--self-test-flo-events" in sys.argv:
        try:
            raw_ids = sys.argv[sys.argv.index("--self-test-flo-events") + 1]
            event_ids = [value.strip() for value in raw_ids.split(",") if value.strip()]
        except (ValueError, IndexError):
            return 2
        if not event_ids:
            return 2

        def resolve_flo(event_id: str) -> str:
            now = datetime.now(ZoneInfo(PITTSBURGH_TIMEZONE))
            game = Game(
                row=0,
                game_date=now.date(),
                home_team="Flo",
                away_team="Self Test",
                kickoff=now.time().replace(tzinfo=None),
                livestream_url=f"https://www.flocollege.com/live/{event_id}",
                timezone=PITTSBURGH_TIMEZONE,
            )
            return FloCollegeAdapter().resolve(game).event_id

        with ThreadPoolExecutor(max_workers=len(event_ids)) as executor:
            resolved = list(executor.map(resolve_flo, event_ids))
        return 0 if resolved == event_ids else 3
    root = tk.Tk()
    RecorderApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
