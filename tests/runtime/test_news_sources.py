"""Unit tests for MQL5 Economic Calendar snapshot loader.

Module: tests.runtime.test_news_sources
Covers: REQ-RSK-001, REQ-RUNTIME-005
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
    tmp_path: Path, events: list[dict[str, Any]], source: str = "MQL5_CALENDAR"
) -> Path:
    payload = {
        "schema_version": 1,
        "source": source,
        "exported_at_utc": "2026-11-20T08:00:00Z",
        "events": events,
    }
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
