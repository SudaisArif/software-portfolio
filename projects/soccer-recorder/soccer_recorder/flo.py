from __future__ import annotations

import base64
import json
import logging
import os
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from .hudl import ProviderError, UnsupportedProvider, _aware_datetime
from .keychain import KeychainError, delete_keychain_secret, load_keychain_secret, save_keychain_secret
from .models import Game, HudlEvent, StreamSnapshot


LOG = logging.getLogger(__name__)
FLO_KEYCHAIN_SERVICE = "com.soccerrecorder.flocollege"
FLO_PASSWORD_KEYCHAIN_SERVICE = "com.soccerrecorder.flosports-password"
FLO_API = "https://api.flocollege.com/api"
FLO_LIVE_API = "https://live-api-3.flosports.tv"
FLO_SITE_ID = 45
FINAL_STATUSES = {"ads-post", "archived", "complete", "completed", "concluded", "deleted", "ended", "finished"}
PRE_AIR_STATUSES = {"new", "pre-air", "preair", "scheduled", "upcoming"}


class FloHttpError(ProviderError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class FloHttpClient:
    """Small JSON client for Flo's documented web-player requests."""

    def __init__(self, timeout: int = 25, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = retries
        default_paths = ssl.get_default_verify_paths()
        candidates = (
            default_paths.cafile,
            "/etc/ssl/cert.pem",
            "/private/etc/ssl/cert.pem",
            "/opt/homebrew/etc/openssl@3/cert.pem",
        )
        ca_file = next((value for value in candidates if value and Path(value).is_file()), None)
        self.ssl_context = ssl.create_default_context(cafile=ca_file)

    def request_json(
        self,
        method: str,
        url: str,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Soccer-Recorder/0.2 (+authorized team video operations)",
            "X-301-Location": "web",
            "x-flo-app": "flosports-webapp",
            "Origin": "https://www.flocollege.com",
            "Referer": "https://www.flocollege.com/",
        }
        request_headers.update(headers or {})
        last_error: Exception | None = None
        attempts = self.retries if method.upper() == "GET" else 1
        for attempt in range(attempts):
            try:
                request = Request(url, data=payload, headers=request_headers, method=method.upper())
                with urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
                    raw = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                parsed = json.loads(raw) if raw else {}
                if not isinstance(parsed, dict):
                    raise ProviderError("FloCollege returned an unexpected response")
                return parsed
            except HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    error_payload = json.loads(raw)
                except json.JSONDecodeError:
                    error_payload = {}
                message = _error_message(error_payload) or exc.reason or f"HTTP {exc.code}"
                raise FloHttpError(exc.code, f"FloCollege: {message}") from exc
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"Could not contact FloCollege: {last_error}")


def _error_message(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("message", "detail", "error_description"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("error")
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    return _error_message(nested)


def _default_support_dir() -> Path:
    override = os.environ.get("SOCCER_RECORDER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / "SoccerRecorder"


class FloSessionStore:
    """Keeps Flo tokens and credentials in Keychain; only the email is on disk."""

    def __init__(
        self,
        root: Path | None = None,
        service: str = FLO_KEYCHAIN_SERVICE,
        password_service: str = FLO_PASSWORD_KEYCHAIN_SERVICE,
    ) -> None:
        self.root = root or _default_support_dir()
        self.config_path = self.root / "flocollege-account.json"
        self.service = service
        self.password_service = password_service

    @property
    def email(self) -> str | None:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            value = str(data.get("email") or "").strip()
            return value or None
        except (FileNotFoundError, json.JSONDecodeError, TypeError, OSError):
            return None

    @property
    def configured(self) -> bool:
        return self.load() is not None

    @property
    def password_configured(self) -> bool:
        return self.load_password() is not None

    def load(self) -> dict[str, Any] | None:
        email = self.email
        if not email:
            return None
        try:
            serialized = load_keychain_secret(email, self.service)
            data = json.loads(serialized) if serialized else None
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def save(self, email: str, session: dict[str, Any]) -> None:
        old_email = self.email
        safe_session = {
            "email": email,
            "token": session.get("token"),
            "refresh_token": session.get("refresh_token"),
            "refresh_token_exp": session.get("refresh_token_exp"),
        }
        if not safe_session["token"] or not safe_session["refresh_token"]:
            raise ProviderError("FloCollege sign-in did not return a reusable session")
        self.root.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(safe_session, separators=(",", ":"))
        try:
            save_keychain_secret(email, self.service, serialized)
        except KeychainError as exc:
            raise ProviderError("macOS Keychain could not save the FloCollege session") from exc
        if old_email and old_email != email:
            delete_keychain_secret(old_email, self.service)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"email": email}, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)

    def load_password(self) -> str | None:
        email = self.email
        return load_keychain_secret(email, self.password_service) if email else None

    def save_password(self, email: str, password: str) -> None:
        if not password:
            raise ProviderError("FloSports password cannot be empty")
        try:
            save_keychain_secret(email, self.password_service, password)
        except KeychainError as exc:
            raise ProviderError("macOS Keychain could not save the FloSports password") from exc

    def delete_password(self, email: str) -> None:
        delete_keychain_secret(email, self.password_service)

    def clear(self) -> None:
        email = self.email
        if email:
            delete_keychain_secret(email, self.service)
            self.delete_password(email)
        self.config_path.unlink(missing_ok=True)


@dataclass(slots=True)
class _StreamAccess:
    stream_id: str
    url: str
    token_id: str | None
    last_heartbeat: float


class FloCollegeAdapter:
    """Resolver and authenticated live-state monitor for FloCollege/FloFC."""

    provider = "flocollege"
    provider_name = "FloCollege"
    supports_login = True

    def __init__(
        self,
        http: FloHttpClient | None = None,
        session_store: FloSessionStore | None = None,
    ) -> None:
        self.http = http or FloHttpClient()
        self.session_store = session_store or FloSessionStore()
        self._stream_access: dict[str, _StreamAccess] = {}

    @property
    def signed_in_email(self) -> str | None:
        email = self.session_store.email
        return email if email and (self.session_store.configured or self.session_store.password_configured) else None

    def login(self, email: str, password: str) -> str:
        email = email.strip()
        if not email or "@" not in email:
            raise ValueError("Enter the email address used for the FloCollege account")
        if not password:
            raise ValueError("Enter the FloCollege password")
        try:
            session = self.http.request_json(
                "POST",
                f"{FLO_API}/tokens",
                {"email": email, "password": password},
            )
        except FloHttpError as exc:
            if exc.status in {400, 401, 403, 422}:
                raise ProviderError("FloCollege sign-in failed. Check the email, password, and account access.") from exc
            raise
        previous_email = self.session_store.email
        self.session_store.save_password(email, password)
        self.session_store.save(email, session)
        if previous_email and previous_email != email:
            self.session_store.delete_password(previous_email)
        return email

    def validate_session(self) -> str:
        session = self._ensure_access_token()
        email = str(session.get("email") or self.session_store.email or "").strip()
        return email or "signed-in account"

    def resolve(self, game: Game) -> HudlEvent:
        event_id = self._event_id_from_url(game.livestream_url)
        if not event_id:
            raise UnsupportedProvider(
                "Paste a FloCollege event link containing /live/ followed by its event number"
            )
        data = self._public_event(event_id)
        scheduled = _aware_datetime(str(data.get("start_at") or data.get("start_date_time")), game.timezone)
        status = self._normal_status(str(data.get("status_v2") or data.get("status") or "Unknown"))
        return HudlEvent(
            event_id=event_id,
            title=str(data.get("title") or game.label),
            scheduled_at=scheduled,
            status=status,
            require_login=bool(data.get("premium")) and not bool(data.get("disable_login")),
            available=data.get("deleted_at") in (None, ""),
            provider=self.provider,
        )

    def snapshot(self, event_id: str) -> StreamSnapshot:
        payload = self.http.request_json(
            "GET",
            f"{FLO_LIVE_API}/events/{event_id}"
            "?embed=stream&fields=premium,startAtNext,dvrEnabled,eventStatusMessage,id,name,slug,"
            "startDate,endDate,adTech,status,enableTattoo,startAt,endAt",
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError(f"FloCollege returned incomplete live metadata for event {event_id}")
        scheduled = _aware_datetime(str(data.get("startAt") or data.get("startAtNext")))
        status = self._normal_status(str(data.get("status") or "Unknown"))
        status_key = status.casefold()
        if status_key in FINAL_STATUSES:
            self.close(event_id)
            return StreamSnapshot(event_id, str(data.get("name") or ""), scheduled, status, False, None)
        if status_key in PRE_AIR_STATUSES:
            return StreamSnapshot(
                event_id,
                str(data.get("name") or ""),
                scheduled,
                status,
                False,
                None,
                str(data.get("eventStatusMessage") or "Waiting for the FloCollege feed"),
            )

        streams = data.get("streams")
        if not isinstance(streams, list):
            streams = []
        candidates = [stream for stream in streams if isinstance(stream, dict) and stream.get("isActive", True)]
        candidates.sort(key=lambda stream: (not bool(stream.get("isDefault1")), int(stream.get("sortOrder") or 0)))
        if not candidates:
            return StreamSnapshot(event_id, str(data.get("name") or ""), scheduled, status, False, None)
        stream_id = str(candidates[0].get("id") or "")
        if not stream_id:
            raise ProviderError(f"FloCollege event {event_id} has no usable stream identifier")
        access = self._stream_access.get(event_id)
        if access and access.stream_id == stream_id:
            if access.token_id and time.monotonic() - access.last_heartbeat >= 50:
                self._heartbeat(access)
            return StreamSnapshot(event_id, str(data.get("name") or ""), scheduled, status, True, access.url)
        access = self._request_stream_access(stream_id)
        self._stream_access[event_id] = access
        return StreamSnapshot(event_id, str(data.get("name") or ""), scheduled, status, True, access.url)

    def close(self, event_id: str) -> None:
        access = self._stream_access.pop(event_id, None)
        if not access or not access.token_id:
            return
        try:
            session = self._ensure_access_token()
            self.http.request_json(
                "DELETE",
                f"{FLO_LIVE_API}/tokens/{access.token_id}",
                headers=self._auth_headers(str(session["token"])),
            )
        except Exception as exc:
            LOG.warning("Could not close FloCollege playback token: %s", exc)

    def refresh_stream(self, event_id: str) -> None:
        """Discard a failed short-lived playlist so the next poll gets a fresh one."""
        self.close(event_id)

    def _heartbeat(self, access: _StreamAccess) -> None:
        session = self._ensure_access_token()
        try:
            self.http.request_json(
                "POST",
                f"{FLO_LIVE_API}/tokens/{access.token_id}/heartbeat",
                {},
                self._auth_headers(str(session["token"])),
            )
            access.last_heartbeat = time.monotonic()
        except FloHttpError as exc:
            if exc.status in {401, 403, 409, 411, 422}:
                raise ProviderError(self._playback_error(exc.status, str(exc))) from exc
            LOG.warning("FloCollege heartbeat failed temporarily: %s", exc)

    def _request_stream_access(self, stream_id: str) -> _StreamAccess:
        session = self._ensure_access_token()
        try:
            payload = self.http.request_json(
                "POST",
                f"{FLO_LIVE_API}/streams/{stream_id}/tokens",
                {"adTracking": {"appName": "flosports-web"}},
                self._auth_headers(str(session["token"])),
            )
        except FloHttpError as exc:
            raise ProviderError(self._playback_error(exc.status, str(exc))) from exc
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError("FloCollege returned incomplete playback access")
        serialized = json.dumps(data).casefold()
        if any(marker in serialized for marker in ("widevine", "fairplay", "playready", "license_server")):
            raise ProviderError("This FloCollege feed uses protected DRM and cannot be recorded by this app")
        ad_tech = str(data.get("adTech") or "").casefold()
        stream_url = data.get("uri") if ad_tech == "ssai" else data.get("cleanUri") or data.get("uri")
        if not isinstance(stream_url, str) or urlparse(stream_url).scheme not in {"http", "https"}:
            raise ProviderError("FloCollege did not provide a playable HLS stream")
        token = data.get("token")
        token_id = str(token.get("id")) if isinstance(token, dict) and token.get("id") is not None else None
        access = _StreamAccess(stream_id, stream_url, token_id, 0)
        if token_id:
            self._heartbeat(access)
        return access

    def _ensure_access_token(self, force_refresh: bool = False) -> dict[str, Any]:
        session = self.session_store.load()
        if not session:
            restored = self._sign_in_with_saved_password()
            if restored:
                return restored
            raise ProviderError("FloSports sign-in required. Open the app and choose FloSports Sign In.")
        token = str(session.get("token") or "")
        if token and not force_refresh and _jwt_expires_at(token) > time.time() + 120:
            return session
        refresh_token = str(session.get("refresh_token") or "")
        if not refresh_token:
            raise ProviderError("The saved FloCollege login has expired. Sign in again in the app.")
        headers = self._auth_headers(token) if token else None
        try:
            refreshed = self.http.request_json(
                "POST",
                f"{FLO_API}/refresh-tokens",
                {"token": refresh_token},
                headers,
            )
        except FloHttpError as exc:
            if exc.status in {400, 401, 403}:
                restored = self._sign_in_with_saved_password()
                if restored:
                    return restored
                raise ProviderError("The saved FloSports login has expired. Sign in again in the app.") from exc
            raise
        merged = {**session, **refreshed}
        email = str(merged.get("email") or self.session_store.email or "")
        self.session_store.save(email, merged)
        return merged

    def _sign_in_with_saved_password(self) -> dict[str, Any] | None:
        email = self.session_store.email
        password = self.session_store.load_password()
        if not email or not password:
            return None
        try:
            session = self.http.request_json(
                "POST",
                f"{FLO_API}/tokens",
                {"email": email, "password": password},
            )
        except FloHttpError as exc:
            if exc.status in {400, 401, 403, 422}:
                return None
            raise
        self.session_store.save(email, session)
        return session

    def _public_event(self, event_id: str) -> dict[str, Any]:
        payload = self.http.request_json(
            "GET",
            f"{FLO_API}/experiences/web/legacy-core/live-events/{event_id}"
            f"?site_id={FLO_SITE_ID}&version=1.33.2",
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError(f"FloCollege event {event_id} was not found")
        return data

    @staticmethod
    def _auth_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _normal_status(status: str) -> str:
        key = status.strip().casefold().replace("_", "-")
        if key in {"new", "preair", "pre-air"}:
            return "Pre-Air"
        if key in {"ads-post", "complete", "completed", "concluded", "ended", "finished"}:
            return "Concluded"
        if key == "live":
            return "Live"
        return status.strip() or "Unknown"

    @staticmethod
    def _playback_error(status: int, fallback: str) -> str:
        return {
            401: "FloCollege login is no longer valid. Sign in again in the app.",
            402: "This FloCollege account does not have access to the event.",
            403: "FloCollege denied access. Confirm the account subscription and event access.",
            409: "FloCollege rejected another simultaneous playback session for this account.",
            411: "FloCollege has blocked playback for this account.",
            422: "FloCollege reports that the stream has completed.",
            451: "This FloCollege event is not available in the current region.",
        }.get(status, fallback)

    @staticmethod
    def _event_id_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        candidates = [parsed.path]
        query = parse_qs(parsed.query)
        for key in ("redirect", "next", "go"):
            candidates.extend(unquote(value) for value in query.get(key, []))
        for candidate in candidates:
            match = re.search(r"/live/(\d+)", candidate, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None


def _jwt_expires_at(token: str) -> float:
    try:
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
        return float(payload.get("exp") or 0)
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        return 0
