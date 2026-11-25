from __future__ import annotations

import html
import json
import re
from datetime import datetime
from urllib.parse import quote, urlparse

from .hudl import HttpClient, ProviderError, UnsupportedProvider, _aware_datetime, _normal_words
from .models import Game, HudlEvent, StreamSnapshot


class BoxCastAdapter:
    """Resolver and live-state monitor for public BoxCast broadcasts."""

    provider = "boxcast"
    provider_name = "BoxCast"

    def __init__(self, http: HttpClient | None = None) -> None:
        self.http = http or HttpClient()

    def resolve(self, game: Game) -> HudlEvent:
        event_id = self._event_id_from_url(game.livestream_url)
        if event_id:
            return self._event(event_id)

        page = self.http.get_text(game.livestream_url)
        match = re.search(r"loadChannel\(\s*['\"]([^'\"]+)", html.unescape(page), flags=re.IGNORECASE)
        if not match:
            raise UnsupportedProvider(f"Not a recognized BoxCast page: {game.livestream_url}")
        channel_id = match.group(1)
        events: list[dict[str, object]] = []
        for timeframe in ("current", "future"):
            url = (
                f"https://api.boxcast.com/channels/{quote(channel_id, safe='')}/broadcasts"
                f"?q=timeframe%3A{timeframe}&l=100&s=starts_at"
            )
            payload = json.loads(self.http.get_text(url))
            if isinstance(payload, list):
                events.extend(item for item in payload if isinstance(item, dict))
        if not events:
            raise ProviderError(f"No current or upcoming BoxCast broadcasts found for {game.label}")
        return self._best_match(game, events)

    def snapshot(self, event_id: str) -> StreamSnapshot:
        detail = self._detail(event_id)
        view = json.loads(self.http.get_text(f"https://api.boxcast.com/broadcasts/{event_id}/view"))
        timeframe = str(detail.get("timeframe") or "").casefold()
        view_status = str(view.get("status") or timeframe or "Unknown")
        status = "Archived" if timeframe in {"past", "archived"} else view_status.title()
        playlist = str(view.get("playlist") or "").strip() or None
        return StreamSnapshot(
            event_id=event_id,
            title=str(detail.get("name") or ""),
            scheduled_at=_aware_datetime(str(detail["starts_at"])),
            status=status,
            streaming=view_status.casefold() in {"live", "streaming", "current"} and bool(playlist),
            content_url=playlist,
            message=str(view.get("reason") or "") or None,
        )

    def _event(self, event_id: str) -> HudlEvent:
        detail = self._detail(event_id)
        return HudlEvent(
            event_id=event_id,
            title=str(detail.get("name") or "BoxCast broadcast"),
            scheduled_at=_aware_datetime(str(detail["starts_at"])),
            status=str(detail.get("timeframe") or "Upcoming").title(),
            expected_duration_seconds=self._expected_duration(detail),
            require_login=bool(detail.get("is_private") or detail.get("is_ticketed")),
            available=not bool(detail.get("is_private") or detail.get("is_ticketed")),
            provider=self.provider,
        )

    def _detail(self, event_id: str) -> dict[str, object]:
        payload = json.loads(self.http.get_text(f"https://api.boxcast.com/broadcasts/{event_id}"))
        if not isinstance(payload, dict) or not payload.get("starts_at"):
            raise ProviderError(f"BoxCast returned incomplete metadata for event {event_id}")
        return payload

    @staticmethod
    def _event_id_from_url(url: str) -> str | None:
        path = urlparse(url).path.rstrip("/")
        match = re.search(r"(?:/broadcasts/|[-/])([a-z0-9]{20})$", path, flags=re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _expected_duration(detail: dict[str, object]) -> int | None:
        try:
            start = _aware_datetime(str(detail["starts_at"]))
            stop = _aware_datetime(str(detail["stops_at"]))
        except (KeyError, TypeError, ValueError):
            return None
        return max(0, int((stop - start).total_seconds()))

    @staticmethod
    def _best_match(game: Game, events: list[dict[str, object]]) -> HudlEvent:
        target = datetime.combine(game.game_date, game.kickoff)
        home_words = _normal_words(game.home_team)
        away_words = _normal_words(game.away_team)

        def score(item: dict[str, object]) -> tuple[int, float]:
            words = _normal_words(str(item.get("name") or ""))
            teams = len(home_words & words) + len(away_words & words)
            event_time = _aware_datetime(str(item["starts_at"])).replace(tzinfo=None)
            return teams, -abs((event_time - target).total_seconds())

        selected = max(events, key=score)
        if score(selected)[0] < 2:
            raise ProviderError(f"Could not confidently match a BoxCast event for {game.label}")
        event_id = str(selected["id"])
        return HudlEvent(
            event_id=event_id,
            title=str(selected.get("name") or game.label),
            scheduled_at=_aware_datetime(str(selected["starts_at"])),
            status=str(selected.get("timeframe") or "Upcoming").title(),
            expected_duration_seconds=BoxCastAdapter._expected_duration(selected),
            require_login=bool(selected.get("is_private") or selected.get("is_ticketed")),
            available=not bool(selected.get("is_private") or selected.get("is_ticketed")),
            provider="boxcast",
        )
