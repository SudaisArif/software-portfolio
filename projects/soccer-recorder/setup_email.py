#!/usr/bin/env python3
"""Configure Gmail notifications without storing the app password in project files."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from soccer_recorder.notifications import EmailConfig, EmailNotifier


DEFAULT_EMAIL = "coach@example.com"
KEYCHAIN_SERVICE = "com.cmu.soccer-recorder.gmail"


def main() -> int:
    root = Path(__file__).resolve().parent
    runtime = Path.home() / "Library" / "Application Support" / "CMUSoccerRecorder"
    runtime.mkdir(parents=True, exist_ok=True)

    email = DEFAULT_EMAIL
    print(f"Gmail sender and notification recipient: {email}")
    print("Paste a NEW 16-character Google app password when macOS Keychain prompts.")
    print("Paste the same app password at both password prompts.")
    print("The password will not be displayed or written to a project file.")
    subprocess.run(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-a",
            email,
            "-s",
            KEYCHAIN_SERVICE,
            "-l",
            "CMU Soccer Recorder Gmail",
            "-w",
        ],
        check=True,
    )

    config: dict[str, str | int] = {
        "sender": email,
        "recipient": DEFAULT_EMAIL,
        "keychain_service": KEYCHAIN_SERVICE,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
    }
    notifier = EmailNotifier(EmailConfig(**config))
    if not notifier.send(
        "CMU Soccer Recorder email test",
        "Email notifications are configured. You will receive messages when recording starts, completes, or fails.",
    ):
        raise SystemExit("The test email failed. Check the app password and try again.")

    temporary = runtime / "email-notifications.json.tmp"
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary.replace(runtime / "email-notifications.json")

    shutil.copytree(root / "soccer_recorder", runtime / "soccer_recorder", dirs_exist_ok=True)
    shutil.copy2(root / "record_games.py", runtime / "record_games.py")

    subprocess.run(
        ["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.cmu.soccer-recorder"],
        check=True,
    )
    print(f"Email notifications enabled and tested for {DEFAULT_EMAIL}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
