from __future__ import annotations

import json
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from .models import Game, HudlEvent
from .keychain import load_keychain_secret


LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmailConfig:
    sender: str
    recipient: str
    keychain_service: str = "com.cmu.soccer-recorder.gmail"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    health_interval_minutes: int = 15


class EmailNotifier:
    """Best-effort Gmail notifications backed by a macOS Keychain secret."""

    def __init__(self, config: EmailConfig | None = None) -> None:
        self.config = config
        self.last_error = ""

    @classmethod
    def from_file(cls, path: Path) -> "EmailNotifier":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(EmailConfig(**data))
        except FileNotFoundError:
            LOG.info("Email notifications are not configured")
            return cls()
        except (json.JSONDecodeError, TypeError) as exc:
            LOG.error("Ignoring invalid email notification config at %s: %s", path, exc)
            return cls()

    @property
    def enabled(self) -> bool:
        return self.config is not None

    @property
    def health_interval_minutes(self) -> int:
        """Return a safe interval for periodic recording-health messages."""
        if self.config is None:
            return 15
        try:
            interval = int(self.config.health_interval_minutes)
        except (TypeError, ValueError):
            return 15
        return max(1, min(interval, 180))

    def send(self, subject: str, body: str) -> bool:
        self.last_error = ""
        if self.config is None:
            self.last_error = "Email notifications are not configured."
            return False
        try:
            password = load_keychain_secret(self.config.sender, self.config.keychain_service) or ""
            password = re.sub(r"\s+", "", password)
            if not password:
                raise RuntimeError("The Gmail app password in Keychain is empty")
            message = EmailMessage()
            message["From"] = self.config.sender
            message["To"] = self.config.recipient
            message["Subject"] = subject
            message.set_content(body)
            context = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
            with smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                context=context,
                timeout=30,
            ) as smtp:
                smtp.login(self.config.sender, password)
                smtp.send_message(message)
            LOG.info("Email notification sent to %s: %s", self.config.recipient, subject)
            return True
        except Exception as exc:
            self.last_error = self._describe_error(exc)
            LOG.error("Email notification failed: %s", exc)
            return False

    def _describe_error(self, exc: Exception) -> str:
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            return (
                "Gmail rejected the sign-in (error 535). Make sure the Gmail address is the same "
                "account that created the App Password, then create a new App Password and enter it "
                "instead of the normal Gmail password."
            )
        if isinstance(exc, smtplib.SMTPDataError):
            detail = exc.smtp_error.decode("utf-8", errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
            if "limit" in detail.lower() or "quota" in detail.lower():
                return "Gmail's sending limit is temporarily reached. Wait up to 24 hours and test again."
            return f"Gmail accepted the sign-in but rejected the test message (error {exc.smtp_code}): {detail}"
        if isinstance(exc, ssl.SSLCertVerificationError):
            return "The Mac could not verify Gmail's security certificate. Check macOS date/time and install system updates."
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return "The Mac could not connect securely to Gmail. Check the internet connection, VPN, firewall, and date/time."
        detail = str(exc).strip()
        return detail or type(exc).__name__

    def recording_started(self, game: Game, event: HudlEvent) -> None:
        provider = "FloCollege" if event.provider == "flocollege" else event.provider.title()
        self.send(
            f"Soccer recording started: {game.label}",
            "\n".join(
                (
                    f"The background recorder has confirmed that FFmpeg is receiving the live {provider} feed.",
                    "",
                    f"Game: {game.label}",
                    f"{provider} event: {event.event_id}",
                    f"Provider kickoff: {event.scheduled_at.astimezone().strftime('%Y-%m-%d %I:%M %p %Z')}",
                )
            ),
        )

    def recording_completed(self, game: Game, event: HudlEvent, output_file: Path) -> None:
        self.send(
            f"Soccer recording completed: {game.label}",
            f"The recording finished and passed MP4 validation.\n\nGame: {game.label}\nFile: {output_file}",
        )

    def checkpoint_ready(self, game: Game, event: HudlEvent, checkpoint_file: Path) -> None:
        provider = "FloCollege" if event.provider == "flocollege" else event.provider.title()
        self.send(
            f"Two-minute recording check passed: {game.label}",
            "\n".join(
                (
                    "The recorder has captured and validated the first two minutes while the full recording continues.",
                    "",
                    f"Game: {game.label}",
                    f"{provider} event: {event.event_id}",
                    f"Checkpoint file: {checkpoint_file}",
                )
            ),
        )

    def recording_failed(self, game: Game, event_id: str | None, error: str) -> None:
        self.send(
            f"Soccer recording FAILED: {game.label}",
            f"The background recorder needs attention.\n\nGame: {game.label}\nEvent: {event_id or 'unknown'}\nError: {error}",
        )
