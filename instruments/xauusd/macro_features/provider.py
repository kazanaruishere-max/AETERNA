# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportMissingImports=false
# pyright: reportUntypedBaseClass=false
# pyright: reportGeneralTypeIssues=false
# pyright: reportAttributeAccessIssue=false

"""FRED macroeconomic feature provider with SQLite caching and graceful degradation.

Implements REQ-STR-005 and MacroFeatureProvider protocol.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import pandas as pd

from engine.analysis_engine.python.types import MacroFeatures

logger = logging.getLogger(__name__)

# Default baseline fallback values (conservative estimates for XAUUSD macro drivers)
DEFAULT_BASELINE_TIPS_10Y: float = 1.80
DEFAULT_BASELINE_DXY: float = 103.50
CACHE_TTL_24H_SECONDS: float = 86400.0


class FredMacroFeatureProvider:
    """Fetches and caches macroeconomic indicators (TIPS 10Y real yield & DXY index).

    Enforces 24-hour rate-limiting cache on FRED API calls and guarantees zero crash
    via SQLite cache fallback and conservative baseline defaults.
    """

    def __init__(
        self,
        api_key: str | None = None,
        db_path: str = "data/macro_cache.db",
        fred_client: Any | None = None,
        cache_ttl_seconds: float = CACHE_TTL_24H_SECONDS,
        tips_series_id: str = "DFII10",
        dxy_series_id: str = "DTWEXBGS",
        cpi_series_id: str | None = "CPIAUCSL",
    ) -> None:
        self._api_key = api_key or os.getenv("FRED_API_KEY")
        self._db_path = db_path
        self._fred_client = fred_client
        self._cache_ttl_seconds = cache_ttl_seconds
        self._tips_series_id = tips_series_id
        self._dxy_series_id = dxy_series_id
        self._cpi_series_id = cpi_series_id

        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite cache database schema."""
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS macro_features_cache (
                    timestamp_utc TEXT PRIMARY KEY,
                    tips_10y_yield REAL NOT NULL,
                    dxy_index REAL NOT NULL,
                    cpi_yoy REAL,
                    real_yield_change_20d REAL,
                    dxy_change_20d REAL,
                    last_fetched_utc TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        """Close SQLite database connection."""
        if hasattr(self, "_conn") and self._conn:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        del exc_type, exc_val, exc_tb
        self.close()
    def save_macro_features(
        self,
        features: MacroFeatures,
        last_fetched_utc: str | None = None,
    ) -> None:
        """Persist a MacroFeatures record into the SQLite cache."""
        fetched_at = last_fetched_utc or datetime.now(UTC).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO macro_features_cache (
                    timestamp_utc,
                    tips_10y_yield,
                    dxy_index,
                    cpi_yoy,
                    real_yield_change_20d,
                    dxy_change_20d,
                    last_fetched_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    features.timestamp_utc,
                    features.tips_10y_yield,
                    features.dxy_index,
                    features.cpi_yoy,
                    features.real_yield_change_20d,
                    features.dxy_change_20d,
                    fetched_at,
                ),
            )

    def _get_latest_cached_row(self) -> sqlite3.Row | tuple[Any, ...] | None:
        """Retrieve most recent cached record ordered by timestamp_utc."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT
                timestamp_utc,
                tips_10y_yield,
                dxy_index,
                cpi_yoy,
                real_yield_change_20d,
                dxy_change_20d,
                last_fetched_utc
            FROM macro_features_cache
            ORDER BY timestamp_utc DESC
            LIMIT 1
            """
        )
        return cursor.fetchone()

    def _row_to_features(self, row: sqlite3.Row | tuple[Any, ...]) -> MacroFeatures:
        """Convert a database row tuple to a MacroFeatures dataclass instance."""
        return MacroFeatures(
            timestamp_utc=str(row[0]),
            tips_10y_yield=float(row[1]),
            dxy_index=float(row[2]),
            cpi_yoy=float(row[3]) if row[3] is not None else None,
            real_yield_change_20d=float(row[4]) if row[4] is not None else None,
            dxy_change_20d=float(row[5]) if row[5] is not None else None,
        )

    def _process_series(self, series: Any) -> tuple[str, float, float | None]:
        """Extract latest timestamp, value, and 20-period delta from series data."""
        # ponytail: 20-day delta uses last 21 trading observations from Series; upgrade to true calendar-day offset if intraday sampling is added.
        if isinstance(series, pd.Series):
            clean = series.dropna()
            if clean.empty:
                raise ValueError("FRED series is empty after dropping NaNs")
            val = float(clean.iloc[-1])
            raw_ts: Any = clean.index[-1]
            if hasattr(raw_ts, "tzinfo") and raw_ts.tzinfo is None:
                ts_str = str(raw_ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
            elif hasattr(raw_ts, "isoformat"):
                ts_str = str(raw_ts.isoformat())
            else:
                ts_str = str(raw_ts)
            change_20d = float(clean.iloc[-1] - clean.iloc[-21]) if len(clean) >= 21 else 0.0
            return ts_str, val, change_20d
        elif isinstance(series, (list, tuple)):
            if len(series) == 0:
                raise ValueError("Series sequence is empty")
            val = float(series[-1])
            change_20d = float(series[-1] - series[-21]) if len(series) >= 21 else 0.0
            return datetime.now(UTC).isoformat(), val, change_20d
        elif isinstance(series, (int, float)):
            return datetime.now(UTC).isoformat(), float(series), 0.0
        else:
            raise TypeError(f"Unsupported series data type: {type(series)}")

    def _fetch_from_fred(self, now_utc: datetime) -> MacroFeatures:
        """Execute network call to FRED API and persist response into SQLite cache."""
        if self._fred_client is not None:
            client = self._fred_client
        else:
            if not self._api_key:
                raise ValueError("FRED API key not provided or set in environment variable")
            from fredapi import Fred

            client = Fred(api_key=self._api_key)

        tips_series = client.get_series(self._tips_series_id)
        dxy_series = client.get_series(self._dxy_series_id)

        cpi_series = None
        if self._cpi_series_id:
            try:
                cpi_series = client.get_series(self._cpi_series_id)
            except Exception as cpi_exc:  # noqa: BLE001
                logger.warning("Optional CPI series fetch failed: %s", cpi_exc)

        ts_str, tips_val, tips_change = self._process_series(tips_series)
        _, dxy_val, dxy_change = self._process_series(dxy_series)

        cpi_val: float | None = None
        if cpi_series is not None:
            try:
                _, cpi_val, _ = self._process_series(cpi_series)
            except Exception:  # noqa: BLE001
                cpi_val = None

        features = MacroFeatures(
            timestamp_utc=ts_str,
            tips_10y_yield=tips_val,
            dxy_index=dxy_val,
            cpi_yoy=cpi_val,
            real_yield_change_20d=tips_change,
            dxy_change_20d=dxy_change,
        )

        self.save_macro_features(features, last_fetched_utc=now_utc.isoformat())
        return features

    def get_latest_macro_features(self) -> MacroFeatures:
        """Retrieve the latest US Real Yield (TIPS 10Y) and DXY proxy readings.

        Checks SQLite cache first. If cache is fresher than 24h (86400s), returns
        cached data without network invocation. Otherwise, fetches fresh data from
        FRED API with graceful degradation on network/rate-limit errors.
        """
        now_utc = datetime.now(UTC)
        latest_row = self._get_latest_cached_row()

        if latest_row is not None:
            try:
                last_fetched_str = str(latest_row[6])
                last_fetched_dt = datetime.fromisoformat(last_fetched_str)
                if last_fetched_dt.tzinfo is None:
                    last_fetched_dt = last_fetched_dt.replace(tzinfo=UTC)

                cache_age = (now_utc - last_fetched_dt).total_seconds()
                if 0 <= cache_age < self._cache_ttl_seconds:
                    return self._row_to_features(latest_row)
            except Exception as parse_err:  # noqa: BLE001
                logger.warning("Failed to parse last_fetched_utc from cache: %s", parse_err)

        try:
            return self._fetch_from_fred(now_utc)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"FRED API fetch failed: {exc}. Falling back to last cached SQLite record.")
            if latest_row is not None:
                return self._row_to_features(latest_row)

            logger.warning("Cache is empty on first run offline. Returning baseline macro features.")
            return MacroFeatures(
                timestamp_utc=now_utc.isoformat(),
                tips_10y_yield=DEFAULT_BASELINE_TIPS_10Y,
                dxy_index=DEFAULT_BASELINE_DXY,
                cpi_yoy=None,
                real_yield_change_20d=0.0,
                dxy_change_20d=0.0,
            )

    def get_historical_macro_features(
        self,
        start_utc: str,
        end_utc: str,
    ) -> list[MacroFeatures]:
        """Query time-range of macro observations from SQLite cache in ascending order."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT
                timestamp_utc,
                tips_10y_yield,
                dxy_index,
                cpi_yoy,
                real_yield_change_20d,
                dxy_change_20d,
                last_fetched_utc
            FROM macro_features_cache
            WHERE timestamp_utc >= ? AND timestamp_utc <= ?
            ORDER BY timestamp_utc ASC
            """,
            (start_utc, end_utc),
        )
        rows = cursor.fetchall()
        return [self._row_to_features(row) for row in rows]
