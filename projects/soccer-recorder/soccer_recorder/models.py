from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass(frozen=True, slots=True)
class Game:
    row: int
    game_date: date
    home_team: str
    away_team: str
    kickoff: time
    livestream_url: str
    timezone: str = "America/New_York"

    @property
    def label(self) -> str:
        return f"{self.home_team} vs. {self.away_team}"

    @property
    def key(self) -> str:
        return "|".join(
            (
                self.game_date.isoformat(),
                self.kickoff.strftime("%H:%M"),
                self.home_team.casefold().strip(),
                self.away_team.casefold().strip(),
            )
        )


@dataclass(frozen=True, slots=True)
class HudlEvent:
    event_id: str
    title: str
    scheduled_at: datetime
    status: str
    site_title: str = ""
    expected_duration_seconds: int | None = None
    require_login: bool = False
    available: bool = True
    provider: str = "hudl"


@dataclass(frozen=True, slots=True)
class StreamSnapshot:
    event_id: str
    title: str
    scheduled_at: datetime
    status: str
    streaming: bool
    content_url: str | None
    message: str | None = None
