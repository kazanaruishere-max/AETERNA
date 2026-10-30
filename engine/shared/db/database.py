"""SQLite WAL Database Storage & IPC State Ledger.

Implements the official DDL schema with:
- Canonical DDL loaded directly from root db/schema.sql
- WAL mode, synchronous=NORMAL, busy_timeout=5000
- Foreign keys enforced on every connection
- CHECK constraints on enums and numerical ranges
- Auto-seeding of baseline model ('v1.0.0-rulebased') on first initialization
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Sequence

from engine.models import (
    BlockedSignalRecord,
    CandleRecord,
    CandleSource,
    ModelRegistryRecord,
    SystemStateRecord,
    Timeframe,
    TradeRecord,
)

CANONICAL_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "db" / "schema.sql"

BASELINE_MODEL_SEED = ModelRegistryRecord(
    model_version="v1.0.0-rulebased",
    training_date_utc="2026-10-30T00:00:00Z",
    data_range="historical-baseline",
    hyperparameters=json.dumps({"type": "rule_based_adx_atr", "lookback": 14}),
    backtest_metrics=json.dumps({"status": "baseline_uncalibrated"}),
    status="active",
    deployed_at_utc="2026-10-30T00:00:00Z",
)


def load_canonical_ddl(schema_path: str | Path | None = None) -> str:
    """Read the canonical DDL schema from db/schema.sql."""
    target_path = Path(schema_path) if schema_path else CANONICAL_SCHEMA_PATH
    if not target_path.exists():
        raise FileNotFoundError(f"Canonical schema file not found at: {target_path}")
    return target_path.read_text(encoding="utf-8")


class DatabaseManager:
    """Manages SQLite connections with WAL mode and repository operations."""

    def __init__(
        self,
        db_path: str | Path = "data/trading.db",
        schema_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path(schema_path) if schema_path else CANONICAL_SCHEMA_PATH
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a connection with WAL mode and foreign keys enforced."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode for explicit transaction control
        )
        conn.row_factory = sqlite3.Row
        try:
            # PRAGMAs must be executed per-connection
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initialize database schema from canonical db/schema.sql and seed baseline model."""
        ddl_script = load_canonical_ddl(self.schema_path)
        with self.get_connection() as conn:
            conn.executescript(ddl_script)

            # Auto-seed baseline model if not already present
            cursor = conn.execute(
                "SELECT 1 FROM model_registry WHERE model_version = ?",
                (BASELINE_MODEL_SEED.model_version,),
            )
            if cursor.fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO model_registry (
                        model_version, training_date_utc, data_range,
                        hyperparameters, backtest_metrics, deployed_at_utc, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        BASELINE_MODEL_SEED.model_version,
                        BASELINE_MODEL_SEED.training_date_utc,
                        BASELINE_MODEL_SEED.data_range,
                        BASELINE_MODEL_SEED.hyperparameters,
                        BASELINE_MODEL_SEED.backtest_metrics,
                        BASELINE_MODEL_SEED.deployed_at_utc,
                        BASELINE_MODEL_SEED.status,
                    ),
                )

    def insert_candle(self, candle: CandleRecord) -> None:
        """Insert or replace a single OHLCV market candle."""
        self.insert_candles([candle])

    def insert_candles(self, candles: Sequence[CandleRecord]) -> None:
        """Batch insert market candles using INSERT OR REPLACE on composite PK."""
        if not candles:
            return
        query = """
        INSERT OR REPLACE INTO market_candles (
            pair, timeframe, timestamp_utc, source, open, high, low, close, tick_volume
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        payload = [
            (
                c.pair,
                c.timeframe,
                c.timestamp_utc,
                c.source,
                c.open,
                c.high,
                c.low,
                c.close,
                c.tick_volume,
            )
            for c in candles
        ]
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.executemany(query, payload)
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def get_candles(
        self,
        pair: str,
        timeframe: Timeframe,
        source: CandleSource,
        limit: int = 100,
    ) -> list[CandleRecord]:
        """Retrieve recent candles ordered chronologically."""
        query = """
        SELECT pair, timeframe, timestamp_utc, source, open, high, low, close, tick_volume
        FROM market_candles
        WHERE pair = ? AND timeframe = ? AND source = ?
        ORDER BY timestamp_utc DESC
        LIMIT ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, (pair, timeframe, source, limit))
            rows = cursor.fetchall()
            # Return in chronological order (oldest to newest)
            return [
                CandleRecord(
                    pair=row["pair"],
                    timeframe=row["timeframe"],
                    timestamp_utc=row["timestamp_utc"],
                    source=row["source"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    tick_volume=row["tick_volume"],
                )
                for row in reversed(rows)
            ]

    def insert_trade(self, trade: TradeRecord) -> None:
        """Insert a newly opened trade into the trades ledger."""
        query = """
        INSERT INTO trades (
            trade_id, timestamp_entry_utc, timestamp_exit_utc, pair, direction,
            data_tag, state_machine_state, regime_detected, strategy_selected,
            confidence_score, hypothesis, entry_price, exit_price, sl, tp,
            lot_size, exit_reason, pnl_usd, pnl_pips, spread_at_entry,
            slippage_realized, model_version_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            conn.execute(
                query,
                (
                    trade.trade_id,
                    trade.timestamp_entry_utc,
                    trade.timestamp_exit_utc,
                    trade.pair,
                    trade.direction,
                    trade.data_tag,
                    trade.state_machine_state,
                    trade.regime_detected,
                    trade.strategy_selected,
                    trade.confidence_score,
                    trade.hypothesis,
                    trade.entry_price,
                    trade.exit_price,
                    trade.sl,
                    trade.tp,
                    trade.lot_size,
                    trade.exit_reason,
                    trade.pnl_usd,
                    trade.pnl_pips,
                    trade.spread_at_entry,
                    trade.slippage_realized,
                    trade.model_version_id,
                ),
            )

    def insert_blocked_signal(self, signal: BlockedSignalRecord) -> None:
        """Insert an audit record for a blocked trading signal."""
        query = """
        INSERT INTO blocked_signals (
            timestamp_utc, pair, direction, strategy_selected, reason_blocked,
            confidence_at_time, would_be_entry_price, current_spread, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            conn.execute(
                query,
                (
                    signal.timestamp_utc,
                    signal.pair,
                    signal.direction,
                    signal.strategy_selected,
                    signal.reason_blocked,
                    signal.confidence_at_time,
                    signal.would_be_entry_price,
                    signal.current_spread,
                    signal.details,
                ),
            )

    def set_system_state(self, state: SystemStateRecord) -> None:
        """Update or insert the single-row system state record."""
        query = """
        INSERT INTO system_state (
            id, state, current_spread, spread_baseline, spread_z_score,
            active_positions_count, equity_usd, daily_pnl_usd, trades_today_count,
            last_news_event, last_updated_utc
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            state = excluded.state,
            current_spread = excluded.current_spread,
            spread_baseline = excluded.spread_baseline,
            spread_z_score = excluded.spread_z_score,
            active_positions_count = excluded.active_positions_count,
            equity_usd = excluded.equity_usd,
            daily_pnl_usd = excluded.daily_pnl_usd,
            trades_today_count = excluded.trades_today_count,
            last_news_event = excluded.last_news_event,
            last_updated_utc = excluded.last_updated_utc
        """
        with self.get_connection() as conn:
            conn.execute(
                query,
                (
                    state.state,
                    state.current_spread,
                    state.spread_baseline,
                    state.spread_z_score,
                    state.active_positions_count,
                    state.equity_usd,
                    state.daily_pnl_usd,
                    state.trades_today_count,
                    state.last_news_event,
                    state.last_updated_utc,
                ),
            )

    def get_system_state(self) -> SystemStateRecord | None:
        """Retrieve the current IPC system state record."""
        query = "SELECT * FROM system_state WHERE id = 1"
        with self.get_connection() as conn:
            cursor = conn.execute(query)
            row = cursor.fetchone()
            if row is None:
                return None
            return SystemStateRecord(
                state=row["state"],
                current_spread=row["current_spread"],
                spread_baseline=row["spread_baseline"],
                spread_z_score=row["spread_z_score"],
                active_positions_count=row["active_positions_count"],
                equity_usd=row["equity_usd"],
                daily_pnl_usd=row["daily_pnl_usd"],
                trades_today_count=row["trades_today_count"],
                last_news_event=row["last_news_event"],
                last_updated_utc=row["last_updated_utc"],
            )
