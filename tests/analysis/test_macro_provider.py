"""Unit tests for FRED Macroeconomic Feature Provider (TASK-M7-STREAM-B).

Verifies REQ-STR-005 contract, 24h SQLite caching, and graceful degradation:
1. Protocol conformance (MacroFeatureProvider)
2. 24h caching suppresses redundant API calls
3. Graceful degradation on API timeout
4. Graceful degradation on HTTP 429 rate limit
5. First run offline fallback (conservative baseline)
6. Historical macro query ascending ordering
"""
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportUnknownLambdaType=false
# pyright: reportMissingImports=false

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.analysis_engine.python.interfaces import MacroFeatureProvider
from engine.analysis_engine.python.types import MacroFeatures
from instruments.xauusd.macro_features.provider import (
    DEFAULT_BASELINE_DXY,
    DEFAULT_BASELINE_TIPS_10Y,
    FredMacroFeatureProvider,
)


def _make_mock_series(base_val: float, count: int = 25) -> pd.Series:
    """Helper creating a synthetic pandas series indexed by UTC dates."""
    dates = pd.date_range("2026-01-01", periods=count, freq="D", tz="UTC")
    values = [base_val + (i * 0.01) for i in range(count)]
    return pd.Series(values, index=dates)


def test_macro_provider_protocol_conformance(tmp_path: Path) -> None:
    """Verify that FredMacroFeatureProvider satisfies MacroFeatureProvider protocol."""
    db_file = str(tmp_path / "macro_protocol.db")
    with FredMacroFeatureProvider(db_path=db_file) as provider:
        assert isinstance(provider, MacroFeatureProvider)
        assert callable(getattr(provider, "get_latest_macro_features", None))
        assert callable(getattr(provider, "get_historical_macro_features", None))


def test_24h_caching_suppresses_redundant_api_calls(tmp_path: Path) -> None:
    """Verify that two calls within 24h trigger external fetch only once."""
    db_file = str(tmp_path / "macro_cache.db")
    mock_client = MagicMock()
    mock_client.get_series.side_effect = lambda series_id: (
        _make_mock_series(1.85) if series_id == "DFII10" else _make_mock_series(104.5)
    )

    with FredMacroFeatureProvider(db_path=db_file, fred_client=mock_client) as provider:
        # First call: empty cache -> external fetch
        res1 = provider.get_latest_macro_features()
        assert res1.tips_10y_yield == pytest.approx(1.85 + (24 * 0.01))
        assert res1.dxy_index == pytest.approx(104.5 + (24 * 0.01))
        initial_calls = mock_client.get_series.call_count
        assert initial_calls >= 2

        # Second call: within 24h TTL -> returns cached SQLite record without network call
        res2 = provider.get_latest_macro_features()
        assert res2.tips_10y_yield == res1.tips_10y_yield
        assert res2.dxy_index == res1.dxy_index
        assert res2.timestamp_utc == res1.timestamp_utc
        assert mock_client.get_series.call_count == initial_calls


def test_graceful_degradation_on_api_timeout(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify network timeout falls back safely to last cached SQLite record."""
    db_file = str(tmp_path / "macro_timeout.db")
    old_fetch_time = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    old_record = MacroFeatures(
        timestamp_utc="2026-11-05T00:00:00Z",
        tips_10y_yield=1.92,
        dxy_index=104.15,
        cpi_yoy=3.2,
        real_yield_change_20d=0.04,
        dxy_change_20d=0.75,
    )

    mock_client = MagicMock()
    mock_client.get_series.side_effect = TimeoutError("Connection to api.stlouisfed.org timed out")

    with FredMacroFeatureProvider(db_path=db_file, fred_client=mock_client) as provider:
        provider.save_macro_features(old_record, last_fetched_utc=old_fetch_time)

        with caplog.at_level(logging.WARNING):
            result = provider.get_latest_macro_features()

        assert result.tips_10y_yield == 1.92
        assert result.dxy_index == 104.15
        assert result.timestamp_utc == "2026-11-05T00:00:00Z"
        assert "FRED API fetch failed" in caplog.text
        assert "Falling back to last cached SQLite record" in caplog.text


def test_graceful_degradation_on_http_429_rate_limit(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify HTTP 429 rate limit falls back to SQLite cache with warning log."""
    db_file = str(tmp_path / "macro_rate_limit.db")
    old_fetch_time = (datetime.now(UTC) - timedelta(hours=36)).isoformat()
    old_record = MacroFeatures(
        timestamp_utc="2026-11-06T00:00:00Z",
        tips_10y_yield=2.01,
        dxy_index=105.30,
        cpi_yoy=2.9,
        real_yield_change_20d=-0.02,
        dxy_change_20d=0.40,
    )

    mock_client = MagicMock()
    mock_client.get_series.side_effect = RuntimeError("HTTP 429 Client Error: Too Many Requests")

    with FredMacroFeatureProvider(db_path=db_file, fred_client=mock_client) as provider:
        provider.save_macro_features(old_record, last_fetched_utc=old_fetch_time)

        with caplog.at_level(logging.WARNING):
            result = provider.get_latest_macro_features()

        assert result.tips_10y_yield == 2.01
        assert result.dxy_index == 105.30
        assert "FRED API fetch failed" in caplog.text
        assert "Falling back to last cached SQLite record" in caplog.text


def test_first_run_offline_fallback(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify startup without network and empty cache returns conservative baseline."""
    db_file = str(tmp_path / "macro_offline_empty.db")
    mock_client = MagicMock()
    mock_client.get_series.side_effect = ConnectionError("DNS resolution failed: no route to host")

    with FredMacroFeatureProvider(db_path=db_file, fred_client=mock_client) as provider:
        with caplog.at_level(logging.WARNING):
            result = provider.get_latest_macro_features()

        assert result.tips_10y_yield == DEFAULT_BASELINE_TIPS_10Y
        assert result.dxy_index == DEFAULT_BASELINE_DXY
        assert result.real_yield_change_20d == 0.0
        assert result.dxy_change_20d == 0.0
        assert result.timestamp_utc is not None
        assert "FRED API fetch failed" in caplog.text
        assert "Returning baseline macro features" in caplog.text


def test_historical_macro_query_ordering(tmp_path: Path) -> None:
    """Verify that get_historical_macro_features returns records in ascending chronological order."""
    db_file = str(tmp_path / "macro_history.db")
    records = [
        MacroFeatures(timestamp_utc="2026-01-05T00:00:00Z", tips_10y_yield=1.90, dxy_index=103.8),
        MacroFeatures(timestamp_utc="2026-01-01T00:00:00Z", tips_10y_yield=1.80, dxy_index=103.2),
        MacroFeatures(timestamp_utc="2026-01-08T00:00:00Z", tips_10y_yield=2.00, dxy_index=104.1),
        MacroFeatures(timestamp_utc="2026-01-03T00:00:00Z", tips_10y_yield=1.85, dxy_index=103.5),
        MacroFeatures(timestamp_utc="2026-01-20T00:00:00Z", tips_10y_yield=2.15, dxy_index=105.0),
    ]

    with FredMacroFeatureProvider(db_path=db_file) as provider:
        for r in records:
            provider.save_macro_features(r)

        # Query range from 2026-01-01 to 2026-01-10
        history = provider.get_historical_macro_features(
            start_utc="2026-01-01T00:00:00Z",
            end_utc="2026-01-10T00:00:00Z",
        )

        assert len(history) == 4
        expected_timestamps = [
            "2026-01-01T00:00:00Z",
            "2026-01-03T00:00:00Z",
            "2026-01-05T00:00:00Z",
            "2026-01-08T00:00:00Z",
        ]
        actual_timestamps = [h.timestamp_utc for h in history]
        assert actual_timestamps == expected_timestamps
        assert history[0].tips_10y_yield == 1.80
        assert history[-1].tips_10y_yield == 2.00
