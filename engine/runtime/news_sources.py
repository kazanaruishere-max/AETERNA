"""MQL5 Economic Calendar snapshot loader.

Module: engine.runtime.news_sources
Responsibility: Load and validate economic calendar snapshots exported by MQL5,
    filtering for USD HIGH impact events and converting to UTC datetimes.
Owner: aeterna-architect
Tier: Tier A
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

logger = logging.getLogger("aeterna.runtime.news_sources")

_EXPECTED_SOURCE = "MQL5_CALENDAR"
_REQUIRED_CURRENCY = "USD"
_REQUIRED_IMPACT = "HIGH"


def load_calendar_snapshot(path: str | Path | None) -> list[datetime]:
    """Load, validate, and extract UTC event timestamps from an MQL5 calendar JSON snapshot."""
    if path is None:
        logger.info("NEWS_SOURCE=NONE reason=path_none")
        return []
    file_path = Path(path)
    if not file_path.is_file():
        logger.info("NEWS_SOURCE=NONE reason=file_missing path=%s", file_path)
        return []
    try:
        content = file_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("NEWS_SOURCE=NONE reason=read_error error=%s", exc)
        return []
    if not content:
        logger.info("NEWS_SOURCE=NONE reason=file_empty path=%s", file_path)
        return []
    try:
        raw_data: object = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("NEWS_SOURCE=NONE reason=json_decode_error error=%s", exc)
        return []
    if not isinstance(raw_data, dict):
        logger.warning("NEWS_SOURCE=NONE reason=invalid_root_type")
        return []

    payload = cast(dict[str, object], raw_data)
    source_val = payload.get("source")
    if not isinstance(source_val, str) or source_val != _EXPECTED_SOURCE:
        logger.warning(
            "NEWS_SOURCE=NONE reason=invalid_source source=%s", str(source_val)
        )
        return []
    events_raw = payload.get("events")
    if not isinstance(events_raw, list):
        logger.warning("NEWS_SOURCE=NONE reason=events_not_a_list")
        return []

    valid_events: list[datetime] = []
    for item in cast(list[object], events_raw):
        if not isinstance(item, dict):
            continue
        ev = cast(dict[str, object], item)
        currency = str(ev.get("currency") or "").strip().upper()
        impact = str(ev.get("impact") or "").strip().upper()
        if currency != _REQUIRED_CURRENCY or impact != _REQUIRED_IMPACT:
            continue
        raw_ts = ev.get("timestamp_utc") or ev.get("timestamp") or ev.get("time")
        if not raw_ts:
            continue
        dt = _parse_utc_datetime(raw_ts)
        if dt is not None:
            valid_events.append(dt)

    valid_events.sort()
    logger.info("NEWS_SOURCE=MQL5_SNAPSHOT event_count=%d", len(valid_events))
    return valid_events


def _parse_utc_datetime(raw: object) -> datetime | None:
    """Parse raw timestamp into timezone-aware UTC datetime."""
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw.astimezone(UTC)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    if isinstance(raw, str) and raw.strip():
        val = raw.strip()
        val = val[:-1] + "+00:00" if val.endswith("Z") else val
        try:
            dt = datetime.fromisoformat(val)
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        except ValueError:
            return None
    return None
