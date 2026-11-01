"""News calendar filter with dynamic DST-aware timezone conversion.

Enforces financial invariant REQ-RSK-001:
Converts scheduled economic release dates and Eastern times to UTC via
zoneinfo.ZoneInfo("America/New_York") to ZoneInfo("UTC").
Evaluates:
- Pre-news window: [T_news - 10m, T_news)
- News blackout window: [T_news, T_news + 15m]
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

EASTERN_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")


def convert_eastern_to_utc(
    release_date: date | str,
    time_eastern: time | str,
) -> datetime:
    """Convert an Eastern Time economic release timestamp to UTC dynamically.

    Handles Eastern Daylight Time (EDT, UTC-4) vs Eastern Standard Time (EST, UTC-5)
    automatically using ZoneInfo.

    Args:
        release_date: Release date object or ISO string (YYYY-MM-DD).
        time_eastern: Release time object or ISO string (HH:MM:SS or HH:MM).

    Returns:
        Timezone-aware datetime in UTC.
    """
    if isinstance(release_date, str):
        parsed_date = date.fromisoformat(release_date)
    else:
        parsed_date = release_date

    if isinstance(time_eastern, str):
        parsed_time = time.fromisoformat(time_eastern)
    else:
        parsed_time = time_eastern

    dt_eastern = datetime(
        parsed_date.year,
        parsed_date.month,
        parsed_date.day,
        parsed_time.hour,
        parsed_time.minute,
        parsed_time.second,
        parsed_time.microsecond,
        tzinfo=EASTERN_TZ,
    )
    return dt_eastern.astimezone(UTC_TZ)


class NewsCalendarFilter:
    """Evaluates high-impact news schedule windows in UTC."""

    def __init__(
        self,
        events: Sequence[datetime] | None = None,
        pre_news_minutes: int = 10,
        blackout_minutes: int = 15,
    ) -> None:
        self.pre_news_minutes = int(pre_news_minutes)
        self.blackout_minutes = int(blackout_minutes)
        self._events: list[datetime] = []

        if events:
            for ev in events:
                self.add_event(ev)

    @property
    def scheduled_events(self) -> list[datetime]:
        """List of all scheduled news event datetimes in UTC."""
        return list(self._events)

    def add_event(self, event_utc: datetime) -> None:
        """Add a scheduled news event datetime in UTC."""
        dt = self._ensure_utc(event_utc)
        self._events.append(dt)
        self._events.sort()

    def add_eastern_event(
        self,
        release_date: date | str,
        time_eastern: time | str,
    ) -> datetime:
        """Convert Eastern release date and time to UTC and register event."""
        dt_utc = convert_eastern_to_utc(release_date, time_eastern)
        self.add_event(dt_utc)
        return dt_utc

    def clear_events(self) -> None:
        """Clear all registered news events."""
        self._events.clear()

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        """Normalize naive or aware datetime to timezone-aware UTC."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(UTC_TZ)

    def is_in_pre_news_window(self, current_utc: datetime) -> bool:
        """Check if current time is within [T_news - pre_news_minutes, T_news).

        Args:
            current_utc: Current evaluation timestamp.

        Returns:
            True if inside pre-news watch interval, False otherwise.
        """
        t = self._ensure_utc(current_utc)
        pre_delta = timedelta(minutes=self.pre_news_minutes)

        for event in self._events:
            # Half-open interval: [T_news - 10m, T_news)
            if (event - pre_delta) <= t < event:
                return True
        return False

    def is_in_news_blackout(self, current_utc: datetime) -> bool:
        """Check if current time is within [T_news, T_news + blackout_minutes].

        Args:
            current_utc: Current evaluation timestamp.

        Returns:
            True if inside blackout interval, False otherwise.
        """
        t = self._ensure_utc(current_utc)
        blackout_delta = timedelta(minutes=self.blackout_minutes)

        for event in self._events:
            # Closed interval: [T_news, T_news + 15m]
            if event <= t <= (event + blackout_delta):
                return True
        return False
