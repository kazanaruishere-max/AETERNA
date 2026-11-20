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

_EXPECTED_SCHEMA_VERSION = 1
_EXPECTED_SOURCE = "MQL5_CALENDAR"
_EXPECTED_SOURCE_TIMEZONE = "TRADE_SERVER"
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
    schema_ver = payload.get("schema_version")
    if (
        not isinstance(schema_ver, int)
        or isinstance(schema_ver, bool)
        or schema_ver != _EXPECTED_SCHEMA_VERSION
    ):
        logger.warning(
            "NEWS_SOURCE=NONE reason=invalid_schema_version schema_version=%s",
            str(schema_ver),
        )
        return []

    source_val = payload.get("source")
    if not isinstance(source_val, str) or source_val != _EXPECTED_SOURCE:
        logger.warning(
            "NEWS_SOURCE=NONE reason=invalid_source source=%s", str(source_val)
        )
        return []

    source_tz = payload.get("source_timezone")
    if not isinstance(source_tz, str) or source_tz != _EXPECTED_SOURCE_TIMEZONE:
        logger.warning(
            "NEWS_SOURCE=NONE reason=invalid_or_missing_source_timezone source_timezone=%s",
            str(source_tz),
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
        try:
            dt = _parse_utc_datetime(raw_ts)
            valid_events.append(dt)
        except (ValueError, TypeError) as exc:
            logger.warning("NEWS_EVENT_PARSE_REJECTED reason=%s", exc)
            continue

    valid_events.sort()
    logger.info("NEWS_TIMEZONE_CONVERTED source_timezone=%s", source_tz)
    logger.info("NEWS_SOURCE=MQL5_SNAPSHOT event_count=%d", len(valid_events))
    return valid_events


def _parse_utc_datetime(raw: object) -> datetime:
    """Parse raw timestamp into timezone-aware UTC datetime, failing fast on invalid format."""
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw.astimezone(UTC)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    if isinstance(raw, str):
        val = raw.strip()
        if not val:
            raise ValueError("Empty timestamp string")
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        dt = datetime.fromisoformat(val)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    raise TypeError(f"Unsupported timestamp type: {type(raw)}")
