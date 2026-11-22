"""Unit tests for MQL5 Economic Calendar snapshot loader.

Module: tests.runtime.test_news_sources
Covers: REQ-RSK-001, REQ-RUNTIME-005, REQ-RUNTIME-006
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from engine.runtime.news_sources import load_calendar_snapshot


def _snap(
    tmp_path: Path,
    events: list[dict[str, Any]],
    source: str = "MQL5_CALENDAR",
    schema_version: Any = 1,
    source_timezone: Any = "TRADE_SERVER",
) -> Path:
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "source": source,
        "exported_at_utc": "2026-11-20T08:00:00Z",
        "events": events,
    }
    if source_timezone is not None:
        payload["source_timezone"] = source_timezone
    p = tmp_path / "calendar_snapshot.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_calendar_snapshot_valid_two_events(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events = [
        {
            "name": "NFP",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T13:30:00Z",
        },
        {
            "name": "FOMC",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T18:00:00Z",
        },
    ]
    with caplog.at_level(logging.INFO):
        loaded = load_calendar_snapshot(_snap(tmp_path, events))
    assert loaded == [
        datetime(2026, 11, 20, 13, 30, tzinfo=UTC),
        datetime(2026, 11, 20, 18, 0, tzinfo=UTC),
    ]
    assert "NEWS_TIMEZONE_CONVERTED source_timezone=TRADE_SERVER" in caplog.text
    assert "NEWS_SOURCE=MQL5_SNAPSHOT" in caplog.text


def test_load_calendar_snapshot_rejects_medium_low_impact(tmp_path: Path) -> None:
    events = [
        {
            "name": "High",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T13:30:00Z",
        },
        {
            "name": "Med",
            "currency": "USD",
            "impact": "MEDIUM",
            "timestamp_utc": "2026-11-20T14:00:00Z",
        },
        {
            "name": "Low",
            "currency": "USD",
            "impact": "LOW",
            "timestamp_utc": "2026-11-20T15:00:00Z",
        },
    ]
    assert load_calendar_snapshot(_snap(tmp_path, events)) == [
        datetime(2026, 11, 20, 13, 30, tzinfo=UTC)
    ]


def test_load_calendar_snapshot_rejects_non_usd_currency(tmp_path: Path) -> None:
    events = [
        {
            "name": "ECB",
            "currency": "EUR",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T12:45:00Z",
        },
        {
            "name": "CPI",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T13:30:00Z",
        },
    ]
    assert load_calendar_snapshot(_snap(tmp_path, events)) == [
        datetime(2026, 11, 20, 13, 30, tzinfo=UTC)
    ]


def test_load_calendar_snapshot_missing_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        assert load_calendar_snapshot(tmp_path / "missing.json") == []
    assert "NEWS_SOURCE=NONE" in caplog.text


def test_load_calendar_snapshot_empty_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert load_calendar_snapshot(empty) == []
    assert "NEWS_SOURCE=NONE" in caplog.text


def test_load_calendar_snapshot_invalid_schema_or_corrupted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{bad-json", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert load_calendar_snapshot(bad) == []
        assert load_calendar_snapshot(_snap(tmp_path, [], source="FOREX_FACTORY")) == []
    assert "NEWS_SOURCE=NONE" in caplog.text


def test_load_calendar_snapshot_rejects_missing_timestamp(tmp_path: Path) -> None:
    events = [
        {"name": "No TS", "currency": "USD", "impact": "HIGH"},
        {
            "name": "Valid",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T14:30:00Z",
        },
    ]
    assert load_calendar_snapshot(_snap(tmp_path, events)) == [
        datetime(2026, 11, 20, 14, 30, tzinfo=UTC)
    ]


def test_load_calendar_snapshot_none_path(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        assert load_calendar_snapshot(None) == []
    assert "NEWS_SOURCE=NONE" in caplog.text


def test_load_calendar_snapshot_rejects_missing_source_timezone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Old snapshot without source_timezone must be rejected."""
    events = [
        {
            "name": "NFP",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T13:30:00Z",
        }
    ]
    with caplog.at_level(logging.WARNING):
        p = _snap(tmp_path, events, source_timezone=None)
        assert load_calendar_snapshot(p) == []
    assert "NEWS_SOURCE=NONE" in caplog.text
    assert "reason=invalid_or_missing_source_timezone" in caplog.text


@pytest.mark.parametrize("bad_tz", ["UTC", "SERVER", "GMT", "", None, 123])
def test_load_calendar_snapshot_rejects_invalid_source_timezone(
    tmp_path: Path, bad_tz: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Only source_timezone='TRADE_SERVER' is accepted."""
    events = [
        {
            "name": "NFP",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T13:30:00Z",
        }
    ]
    with caplog.at_level(logging.WARNING):
        p = _snap(tmp_path, events, source_timezone=bad_tz)
        assert load_calendar_snapshot(p) == []
    assert "NEWS_SOURCE=NONE" in caplog.text


@pytest.mark.parametrize("bad_schema", [2, 0, -1, "1", "1.0", 1.0, None, True, False])
def test_load_calendar_snapshot_rejects_invalid_schema_version(
    tmp_path: Path, bad_schema: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Only schema_version == 1 (int) is accepted."""
    events = [
        {
            "name": "NFP",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": "2026-11-20T13:30:00Z",
        }
    ]
    with caplog.at_level(logging.WARNING):
        p = _snap(tmp_path, events, schema_version=bad_schema)
        assert load_calendar_snapshot(p) == []
    assert "NEWS_SOURCE=NONE" in caplog.text
    assert "reason=invalid_schema_version" in caplog.text


def test_mql5_export_offset_conversion_plus_7_hours(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An offset of +7 hours (TimeTradeServer() - TimeGMT() == 25200s) shifts trade server time to UTC."""
    # Trade server time: 2026-11-20 20:30:00
    server_time = datetime(2026, 11, 20, 20, 30, 0, tzinfo=UTC)
    offset_seconds = 7 * 3600  # +7 jam (25200 s)
    timestamp_utc_sec = int(server_time.timestamp()) - offset_seconds
    dt_utc = datetime.fromtimestamp(timestamp_utc_sec, tz=UTC)

    # Exporter writes ISO string in UTC
    formatted_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert formatted_utc == "2026-11-20T13:30:00Z"

    events = [
        {
            "name": "Core CPI",
            "currency": "USD",
            "impact": "HIGH",
            "timestamp_utc": formatted_utc,
        }
    ]
    with caplog.at_level(logging.INFO):
        loaded = load_calendar_snapshot(_snap(tmp_path, events))

    assert loaded == [datetime(2026, 11, 20, 13, 30, tzinfo=UTC)]
    assert "NEWS_TIMEZONE_CONVERTED source_timezone=TRADE_SERVER" in caplog.text


def test_export_calendar_mql5_source_contract() -> None:
    """Source-contract test for ea/Scripts/ExportCalendar.mq5.

    Static verification of MQL5 exporter source code contracts without claiming
    MQL5 compilation. Asserts presence of TimeTradeServer(), TimeGMT(),
    source_timezone TRADE_SERVER, and server-GMT offset event conversion.
    """
    mql5_path = (
        Path(__file__).resolve().parents[2] / "ea" / "Scripts" / "ExportCalendar.mq5"
    )
    assert mql5_path.is_file(), f"MQL5 source file not found at {mql5_path}"

    source = mql5_path.read_text(encoding="utf-8")

    assert "TimeTradeServer()" in source, (
        "ExportCalendar.mq5 must call TimeTradeServer()"
    )
    assert "TimeGMT()" in source, "ExportCalendar.mq5 must call TimeGMT()"
    assert "SOURCE_TIMEZONE" in source, "ExportCalendar.mq5 must define SOURCE_TIMEZONE"
    assert '"TRADE_SERVER"' in source, "ExportCalendar.mq5 must specify 'TRADE_SERVER'"
    assert "source_timezone" in source, (
        "ExportCalendar.mq5 must export source_timezone in JSON output"
    )
    assert "now_server - now_gmt" in source, (
        "ExportCalendar.mq5 must calculate offset as now_server - now_gmt"
    )
    assert "values[i].time - offset_seconds" in source, (
        "ExportCalendar.mq5 must adjust event timestamp by subtracting offset_seconds"
    )
    assert "ev.currency" not in source, (
        "MqlCalendarEvent has no currency field; use filtered InpCurrency"
    )
    assert "InpCurrency" in source, (
        "ExportCalendar.mq5 must use the filtered InpCurrency value"
    )


def test_golden_fixture_offset_plus_7_hours_jan_2026(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Golden inline fixture test: 2026-01-01 08:30:00 on offset +7 -> 2026-01-01T01:30:00Z."""
    # Trade server time: 2026-01-01 08:30:00
    server_time = datetime(2026, 1, 1, 8, 30, 0, tzinfo=UTC)
    offset_seconds = 7 * 3600  # +7 hours (25200 s)
    timestamp_utc_sec = int(server_time.timestamp()) - offset_seconds
    dt_utc = datetime.fromtimestamp(timestamp_utc_sec, tz=UTC)

    formatted_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert formatted_utc == "2026-01-01T01:30:00Z"

    # Inline JSON snapshot matching MQL5 ExportCalendar output
    snapshot_json = """{
  "schema_version": 1,
  "source": "MQL5_CALENDAR",
  "source_timezone": "TRADE_SERVER",
  "exported_at_utc": "2026-01-01T01:00:00Z",
  "events": [
    {
      "id": 501,
      "event_id": 9001,
      "name": "US Non-Farm Payrolls",
      "currency": "USD",
      "impact": "HIGH",
      "timestamp_utc": "2026-01-01T01:30:00Z"
    }
  ]
}"""
    snapshot_file = tmp_path / "calendar_snapshot.json"
    snapshot_file.write_text(snapshot_json, encoding="utf-8")

    with caplog.at_level(logging.INFO):
        loaded = load_calendar_snapshot(snapshot_file)

    assert loaded == [datetime(2026, 1, 1, 1, 30, tzinfo=UTC)]
    assert "NEWS_TIMEZONE_CONVERTED source_timezone=TRADE_SERVER" in caplog.text
    assert "NEWS_SOURCE=MQL5_SNAPSHOT" in caplog.text
