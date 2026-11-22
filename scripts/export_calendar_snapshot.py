"""Export USD HIGH MQL5 calendar events into the AETERNA snapshot contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import requests

CALENDAR_URL = "https://www.mql5.com/en/economic-calendar"
DATA_URL = "https://www.mql5.com/en/economic-calendar/content"
OUTPUT_PATH = Path("data/calendar_snapshot.json")
HIGH_IMPORTANCE = 8
USD_CURRENCY = 1


def _iso_no_z(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def fetch_events(session: requests.Session) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    payload = {
        "date_mode": "1",
        "from": _iso_no_z(now - timedelta(days=1)),
        "to": _iso_no_z(now + timedelta(days=7)),
        "importance": str(HIGH_IMPORTANCE),
        "currencies": str(USD_CURRENCY),
    }
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": CALENDAR_URL,
    }
    response = session.post(DATA_URL, data=payload, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise TypeError("MQL5 calendar response is not a list")
    return cast(list[dict[str, Any]], data)


def build_snapshot(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for raw in raw_events:
        currency = str(raw.get("CurrencyCode") or "").upper()
        importance = str(raw.get("Importance") or "").lower()
        release_ms = raw.get("ReleaseDate")
        if currency != "USD" or importance != "high" or release_ms is None:
            continue
        released = datetime.fromtimestamp(int(release_ms) / 1000, tz=UTC)
        events.append(
            {
                "id": raw.get("Id"),
                "event_id": raw.get("EventType"),
                "name": raw.get("EventName"),
                "currency": "USD",
                "impact": "HIGH",
                "timestamp_utc": released.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    events.sort(key=lambda event: str(event["timestamp_utc"]))
    return {
        "schema_version": 1,
        "source": "MQL5_CALENDAR",
        "source_timezone": "TRADE_SERVER",
        "export_method": "MQL5_WEB_CALENDAR_CONTENT_UTC",
        "exported_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events": events,
    }


def main() -> int:
    session = requests.Session()
    session.get(CALENDAR_URL, timeout=30)
    snapshot = build_snapshot(fetch_events(session))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CALENDAR_EVENTS={len(snapshot['events'])}")
    print(f"OUTPUT={OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
