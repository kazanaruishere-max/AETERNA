"""
Module: engine.analysis_engine.python.loader
Responsibility: SQLite candle loader for M1 market candles via DatabaseManager.
Owner: aeterna-backtest
Tier: B
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from engine.analysis_engine.python.types import CandleDict
from engine.shared.db.database import DatabaseManager


def _build_candles_query(
    start_time_utc: str | None,
    end_time_utc: str | None,
) -> tuple[str, list[str]]:
    """Construct SQL query and parameters for market_candles selection."""
    conditions = ["pair = ?", "timeframe = ?", "source = ?"]
    extra_params: list[str] = []

    if start_time_utc is not None:
        conditions.append("timestamp_utc >= ?")
        extra_params.append(start_time_utc)

    if end_time_utc is not None:
        conditions.append("timestamp_utc <= ?")
        extra_params.append(end_time_utc)

    where_clause = " AND ".join(conditions)
    sql = (
        "SELECT timestamp_utc, open, high, low, close, tick_volume "
        f"FROM market_candles WHERE {where_clause} "
        "ORDER BY timestamp_utc ASC;"
    )
    return sql, extra_params


def _parse_candle_rows(rows: Sequence[sqlite3.Row]) -> list[CandleDict]:
    """Convert SQLite row records into typed CandleDict records."""
    return [
        {
            "timestamp_utc": str(row["timestamp_utc"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "tick_volume": int(row["tick_volume"]),
        }
        for row in rows
    ]


def load_candles_from_db(
    db_manager: DatabaseManager | None = None,
    pair: str = "XAUUSD",
    timeframe: str = "M1",
    source: str = "exness_mt5",
    start_time_utc: str | None = None,
    end_time_utc: str | None = None,
) -> list[CandleDict]:
    """Load chronological M1 market candles from SQLite database using pair column.

    Includes defensive handling for sqlite3.OperationalError (database locked/busy).
    """
    manager = db_manager or DatabaseManager()
    sql, extra_params = _build_candles_query(start_time_utc, end_time_utc)
    params = [pair, timeframe, source, *extra_params]

    try:
        with manager.get_connection() as conn:
            cursor = conn.execute(sql, tuple(params))
            rows = cursor.fetchall()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            f"SQLite operational error while querying market_candles (locked/busy): {exc}"
        ) from exc

    if not rows:
        raise ValueError("No candles found for specified criteria")

    return _parse_candle_rows(rows)
