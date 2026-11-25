from __future__ import annotations

import html
import json
import logging
import re
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from .models import Game, HudlEvent, StreamSnapshot


LOG = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    pass


class UnsupportedProvider(ProviderError):
    pass


class HttpClient:
    def __init__(self, timeout: int = 20, retries: int = 3) -> None:
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

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": "CMU-Soccer-Recorder/0.1 (+team video operations)",
                        "Accept": "application/json, application/xml, text/html, */*",
                    },
                )
                with urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
                    return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"Could not fetch {url}: {last_error}")


def _aware_datetime(value: str, fallback_timezone: str = "America/New_York") -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(fallback_timezone))
    return parsed


def _normal_words(value: str) -> set[str]:
    ignored = {"the", "college", "university", "mens", "men", "soccer", "vs", "at", "of"}
    return {word for word in re.findall(r"[a-z0-9]+", value.casefold()) if word not in ignored}


class HudlAdapter:
    """Resolver and live-state monitor for Hudl TV / BlueFrame portals."""

    VCLOUD_DOMAIN = "vcloud.hudl.com"

    def __init__(self, http: HttpClient | None = None) -> None:
        self.http = http or HttpClient()

    def resolve(self, game: Game) -> HudlEvent:
        event_id = self._event_id_from_url(game.livestream_url)
        if event_id:
            snapshot = self.snapshot(event_id)
            return HudlEvent(
                event_id=event_id,
                title=snapshot.title or game.label,
                scheduled_at=snapshot.scheduled_at,
                status=snapshot.status,
            )

        page = self.http.get_text(game.livestream_url)
        if "blueframe-app" not in page.casefold() and "blueframetech" not in page.casefold():
            raise UnsupportedProvider(f"Not a recognized Hudl TV / BlueFrame page: {game.livestream_url}")
        tag_match = re.search(r"<blueframe-app\b[^>]*>", page, flags=re.IGNORECASE)
        if not tag_match:
            raise ProviderError(f"Hudl player configuration not found on {game.livestream_url}")
        tag = html.unescape(tag_match.group(0))
        config_match = re.search(r"portalconfig=[\"']([^\"']+)", tag, flags=re.IGNORECASE)
        if not config_match:
            raise ProviderError(f"Hudl portal configuration URL not found on {game.livestream_url}")
        config_url = urljoin(game.livestream_url, config_match.group(1))
        if config_url.startswith("http://"):
            config_url = "https://" + config_url.removeprefix("http://")
        config = json.loads(self.http.get_text(config_url))
        vcloud = config.get("vCloud", {})
        domain = vcloud.get("domain", self.VCLOUD_DOMAIN)
        site_ids = [str(value) for value in vcloud.get("siteIds", [])]
        if not site_ids:
            raise ProviderError(f"Hudl portal lists no site IDs: {game.livestream_url}")
        events = self._upcoming_events(domain, site_ids, game)
        return self._best_match(game, events)

    def snapshot(self, event_id: str) -> StreamSnapshot:
        url = f"https://{self.VCLOUD_DOMAIN}/api/broadcast/vmap/{event_id}?autoplay=1&minify_js=1"
        raw = self.http.get_text(url)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ProviderError(f"Hudl returned invalid playback metadata for event {event_id}") from exc
        broadcast = root.find(".//Broadcast")
        content = root.find(".//Content")
        messages = root.find(".//Messages")
        if broadcast is None or content is None:
            raise ProviderError(f"Hudl playback metadata is incomplete for event {event_id}")
        status = broadcast.attrib.get("status", "Unknown")
        scheduled = _aware_datetime(broadcast.attrib["date"])
        content_url = (content.text or "").strip() or None
        streaming = content.attrib.get("streaming", "false").casefold() == "true" and bool(content_url)
        message = None
        if messages is not None:
            message = messages.attrib.get(status.casefold())
        return StreamSnapshot(
            event_id=event_id,
            title=broadcast.attrib.get("title", ""),
            scheduled_at=scheduled,
            status=status,
            streaming=streaming,
            content_url=content_url,
            message=message,
        )

    @staticmethod
    def _event_id_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key, values in query.items():
            if key.casefold() == "b" and values and values[0].isdigit():
                return values[0]
        match = re.search(r"/broadcast/(?:embed/)?(\d+)", parsed.path, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _upcoming_events(self, domain: str, site_ids: list[str], game: Game) -> list[dict[str, object]]:
        local_zone = ZoneInfo(game.timezone)
        start = datetime.combine(game.game_date - timedelta(days=1), datetime.min.time(), local_zone)
        end = datetime.combine(game.game_date + timedelta(days=2), datetime.min.time(), local_zone)
        params = {
            "site_id": ",".join(site_ids),
            "viewer_status": "3",
            "sort_by": "date",
            "sort_dir": "asc",
            "per_page": "100",
            "page": "1",
            "after": format_datetime(start.astimezone(timezone.utc), usegmt=True),
            "before": format_datetime(end.astimezone(timezone.utc), usegmt=True),
            "callback": "cmuRecorder",
        }
        url = f"https://{domain}/api/viewer/broadcast?{urlencode(params)}"
        payload = self.http.get_text(url).strip()
        match = re.fullmatch(r"[A-Za-z0-9_$.]+\((.*)\);?", payload, flags=re.DOTALL)
        if match:
            payload = match.group(1)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProviderError("Hudl returned invalid event-search data") from exc
        return list(data.get("broadcasts", []))

    @staticmethod
    def _best_match(game: Game, events: list[dict[str, object]]) -> HudlEvent:
        if not events:
            raise ProviderError(f"No upcoming Hudl broadcasts found near {game.game_date} for {game.label}")
        local_zone = ZoneInfo(game.timezone)
        workbook_time = datetime.combine(game.game_date, game.kickoff, local_zone)
        home_words = _normal_words(game.home_team)
        away_words = _normal_words(game.away_team)

        def score(event: dict[str, object]) -> tuple[float, float]:
            text_words = _normal_words(f"{event.get('site_title', '')} {event.get('title', '')}")
            team_score = len(home_words & text_words) + len(away_words & text_words)
            section_bonus = 2 if "men's soccer" in str(event.get("section_title", "")).casefold() else 0
            event_time = _aware_datetime(str(event["date"])).astimezone(local_zone)
            delta_hours = abs((event_time - workbook_time).total_seconds()) / 3600
            return (team_score + section_bonus - min(delta_hours, 24) / 24, -delta_hours)

        selected = max(events, key=score)
        selected_score = score(selected)[0]
        if selected_score < 2:
            raise ProviderError(f"Could not confidently match a Hudl event for {game.label}")
        return HudlEvent(
            event_id=str(selected["id"]),
            title=str(selected.get("title") or game.label),
            scheduled_at=_aware_datetime(str(selected["date"])),
            status=str(selected.get("status", "Unknown")),
            site_title=str(selected.get("site_title", "")),
            expected_duration_seconds=(
                int(str(selected["expected_duration"])) if selected.get("expected_duration") not in (None, "") else None
            ),
            require_login=str(selected.get("require_login", "no")).casefold() not in {"no", "false", "0"},
            available=bool(selected.get("available", True)),
        )
