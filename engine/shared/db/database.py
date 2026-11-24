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
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path

from engine.models import (
    BarCursorRecord,
    BlockedSignalRecord,
    CandleRecord,
    CandleSource,
    ModelRegistryRecord,
    NewsTelemetryRecord,
    RecordOrigin,
    ReplayRunRecord,
    ReplayStatus,
    SignalObservationRecord,
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

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection) -> None:
        """Idempotently migrate existing tables to include restart-gap replay columns/indexes."""
        # 1. signal_observations: origin DEFAULT 'LIVE', replay_id
        table_obs = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_observations';"
        ).fetchone()
        if table_obs is not None:
            cols = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(signal_observations);"
                ).fetchall()
            }
            if "origin" not in cols:
                conn.execute(
                    "ALTER TABLE signal_observations ADD COLUMN origin TEXT NOT NULL DEFAULT 'LIVE' CHECK (origin IN ('LIVE', 'REPLAY'));"
                )
            if "replay_id" not in cols:
                conn.execute(
                    "ALTER TABLE signal_observations ADD COLUMN replay_id TEXT;"
                )

        # 2. blocked_signals: origin DEFAULT 'LIVE', replay_id, idx_blocked_signals_dedup
        table_blocked = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='blocked_signals';"
        ).fetchone()
        if table_blocked is not None:
            cols = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(blocked_signals);"
                ).fetchall()
            }
            if "origin" not in cols:
                conn.execute(
                    "ALTER TABLE blocked_signals ADD COLUMN origin TEXT NOT NULL DEFAULT 'LIVE' CHECK (origin IN ('LIVE', 'REPLAY'));"
                )
            if "replay_id" not in cols:
                conn.execute(
                    "ALTER TABLE blocked_signals ADD COLUMN replay_id TEXT;"
                )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_blocked_signals_dedup "
                "ON blocked_signals(pair, timestamp_utc, strategy_selected, reason_blocked, origin);"
            )

        # 3. bar_cursors: config_hash
        table_cursors = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bar_cursors';"
        ).fetchone()
        if table_cursors is not None:
            cols = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(bar_cursors);"
                ).fetchall()
            }
            if "config_hash" not in cols:
                conn.execute(
                    "ALTER TABLE bar_cursors ADD COLUMN config_hash TEXT;"
                )

    def init_db(self) -> None:
        """Initialize database schema from canonical db/schema.sql and seed baseline model."""
        ddl_script = load_canonical_ddl(self.schema_path)
        with self.get_connection() as conn:
            # Pre-DDL migration ensures legacy tables have required columns before index creation
            self._migrate_schema(conn)
            conn.executescript(ddl_script)
            # Post-DDL migration ensures any newly created or existing tables have all columns/indexes
            self._migrate_schema(conn)

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
            confidence_at_time, would_be_entry_price, current_spread, details,
            origin, replay_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    signal.origin,
                    signal.replay_id,
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

    def get_bar_cursor(self, symbol: str, timeframe: str) -> BarCursorRecord | None:
        """Retrieve the last closed bar cursor for a symbol/timeframe."""
        query = """
        SELECT symbol, timeframe, last_closed_bar_ts, updated_at_ms, config_hash
        FROM bar_cursors
        WHERE symbol = ? AND timeframe = ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, (symbol, timeframe))
            row = cursor.fetchone()
            if row is None:
                return None
            return BarCursorRecord(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                last_closed_bar_ts=row["last_closed_bar_ts"],
                updated_at_ms=row["updated_at_ms"],
                config_hash=row["config_hash"],
            )

    def advance_bar_cursor(self, cursor: BarCursorRecord) -> None:
        """Upsert bar cursor via INSERT OR REPLACE (restart-safe)."""
        query = """
        INSERT OR REPLACE INTO bar_cursors (
            symbol, timeframe, last_closed_bar_ts, updated_at_ms, config_hash
        ) VALUES (?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            conn.execute(
                query,
                (
                    cursor.symbol,
                    cursor.timeframe,
                    cursor.last_closed_bar_ts,
                    cursor.updated_at_ms,
                    cursor.config_hash,
                ),
            )

    def insert_signal_observation(self, signal: SignalObservationRecord) -> bool:
        """Insert signal observation; returns False on duplicate (symbol, bar_ts, strategy_id)."""
        query = """
        INSERT INTO signal_observations (
            signal_id, symbol, bar_ts, strategy_id, order_type, state,
            entry_px, sl_px, tp_px, lot_virtual,
            partial_skipped_min_lot, r_realized_net, exit_reason,
            origin, replay_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self.get_connection() as conn:
                conn.execute(
                    query,
                    (
                        signal.signal_id,
                        signal.symbol,
                        signal.bar_ts,
                        signal.strategy_id,
                        signal.order_type,
                        signal.state,
                        signal.entry_px,
                        signal.sl_px,
                        signal.tp_px,
                        signal.lot_virtual,
                        signal.partial_skipped_min_lot,
                        signal.r_realized_net,
                        signal.exit_reason,
                        signal.origin,
                        signal.replay_id,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def update_signal_observation(
        self,
        signal_id: str,
        state: str,
        r_realized_net: float = 0.0,
        exit_reason: str | None = None,
    ) -> bool:
        """Update virtual signal state and realized R; returns True if a row changed."""
        query = """
        UPDATE signal_observations
        SET state = ?, r_realized_net = ?, exit_reason = ?
        WHERE signal_id = ?
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                query,
                (
                    state,
                    r_realized_net,
                    exit_reason,
                    signal_id,
                ),
            )
            changed = cursor.rowcount > 0
        return changed

    @staticmethod
    def _row_to_signal_observation(row: sqlite3.Row) -> SignalObservationRecord:
        """Map a sqlite3.Row to a SignalObservationRecord domain dataclass."""
        return SignalObservationRecord(
            signal_id=row["signal_id"],
            symbol=row["symbol"],
            bar_ts=row["bar_ts"],
            strategy_id=row["strategy_id"],
            order_type=row["order_type"],
            state=row["state"],
            entry_px=row["entry_px"],
            sl_px=row["sl_px"],
            tp_px=row["tp_px"],
            lot_virtual=row["lot_virtual"],
            partial_skipped_min_lot=row["partial_skipped_min_lot"],
            r_realized_net=row["r_realized_net"],
            exit_reason=row["exit_reason"],
            origin=row["origin"],
            replay_id=row["replay_id"],
        )

    @staticmethod
    def _row_to_blocked_signal(row: sqlite3.Row) -> BlockedSignalRecord:
        """Map a sqlite3.Row to a BlockedSignalRecord domain dataclass."""
        return BlockedSignalRecord(
            id=row["id"],
            timestamp_utc=row["timestamp_utc"],
            pair=row["pair"],
            direction=row["direction"],
            strategy_selected=row["strategy_selected"],
            reason_blocked=row["reason_blocked"],
            confidence_at_time=row["confidence_at_time"],
            would_be_entry_price=row["would_be_entry_price"],
            current_spread=row["current_spread"],
            details=row["details"],
            origin=row["origin"],
            replay_id=row["replay_id"],
        )

    @staticmethod
    def _row_to_replay_run(row: sqlite3.Row) -> ReplayRunRecord:
        """Map a sqlite3.Row to a ReplayRunRecord domain dataclass."""
        return ReplayRunRecord(
            replay_id=row["replay_id"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            last_cursor_ts=row["last_cursor_ts"],
            first_missed_bar_ts=row["first_missed_bar_ts"],
            last_missed_bar_ts=row["last_missed_bar_ts"],
            missed_count=row["missed_count"],
            started_at_utc=row["started_at_utc"],
            finished_at_utc=row["finished_at_utc"],
            status=row["status"],
            replay_mode=row["replay_mode"],
            config_hash=row["config_hash"],
            strategy_id=row["strategy_id"],
            model_id=row["model_id"],
            observations_created=row["observations_created"],
            blocked_created=row["blocked_created"],
            error_text=row["error_text"],
        )

    def get_open_signal_observations(
        self, symbol: str
    ) -> list[SignalObservationRecord]:
        """Read active virtual observations for a symbol in deterministic order."""
        query = """
        SELECT signal_id, symbol, bar_ts, strategy_id, order_type, state,
               entry_px, sl_px, tp_px, lot_virtual, partial_skipped_min_lot,
               r_realized_net, exit_reason, origin, replay_id
        FROM signal_observations
        WHERE symbol = ? AND state IN (?, ?, ?, ?)
        ORDER BY bar_ts ASC, signal_id ASC
        """
        with self.get_connection() as conn:
            rows = conn.execute(
                query,
                (symbol, "OPEN", "PARTIAL_SKIPPED_MIN_LOT", "RUNNING", "BE_ARMED"),
            ).fetchall()
        return [self._row_to_signal_observation(row) for row in rows]

    def insert_news_telemetry(self, telemetry: NewsTelemetryRecord) -> None:
        """Upsert news telemetry via INSERT OR REPLACE."""
        query = """
        INSERT OR REPLACE INTO news_telemetry (
            event_id, symbol, release_ts, actual_val, consensus_val,
            peak_spread_pts, max_z_score, range_1m, range_5m,
            range_15m, range_60m
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            conn.execute(
                query,
                (
                    telemetry.event_id,
                    telemetry.symbol,
                    telemetry.release_ts,
                    telemetry.actual_val,
                    telemetry.consensus_val,
                    telemetry.peak_spread_pts,
                    telemetry.max_z_score,
                    telemetry.range_1m,
                    telemetry.range_5m,
                    telemetry.range_15m,
                    telemetry.range_60m,
                ),
            )

    def create_replay_run(self, record: ReplayRunRecord) -> None:
        """Insert a new replay run tracking record."""
        query = """
        INSERT INTO replay_runs (
            replay_id, symbol, timeframe, last_cursor_ts,
            first_missed_bar_ts, last_missed_bar_ts, missed_count,
            started_at_utc, finished_at_utc, status, replay_mode,
            config_hash, strategy_id, model_id, observations_created,
            blocked_created, error_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            conn.execute(
                query,
                (
                    record.replay_id,
                    record.symbol,
                    record.timeframe,
                    record.last_cursor_ts,
                    record.first_missed_bar_ts,
                    record.last_missed_bar_ts,
                    record.missed_count,
                    record.started_at_utc,
                    record.finished_at_utc,
                    record.status,
                    record.replay_mode,
                    record.config_hash,
                    record.strategy_id,
                    record.model_id,
                    record.observations_created,
                    record.blocked_created,
                    record.error_text,
                ),
            )

    def get_replay_run(self, replay_id: str) -> ReplayRunRecord | None:
        """Retrieve a replay run by its ID."""
        query = "SELECT * FROM replay_runs WHERE replay_id = ?"
        with self.get_connection() as conn:
            cursor = conn.execute(query, (replay_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_replay_run(row)

    def update_replay_run_status(
        self,
        replay_id: str,
        status: ReplayStatus,
        finished_at_utc: str | None = None,
        error_text: str | None = None,
        observations_created: int | None = None,
        blocked_created: int | None = None,
    ) -> None:
        """Update replay run status, timestamp, metrics, and error text."""
        clauses = ["status = ?"]
        params: list[object] = [status]

        if finished_at_utc is not None:
            clauses.append("finished_at_utc = ?")
            params.append(finished_at_utc)
        if error_text is not None:
            clauses.append("error_text = ?")
            params.append(error_text)
        if observations_created is not None:
            clauses.append("observations_created = ?")
            params.append(observations_created)
        if blocked_created is not None:
            clauses.append("blocked_created = ?")
            params.append(blocked_created)

        params.append(replay_id)
        query = f"UPDATE replay_runs SET {', '.join(clauses)} WHERE replay_id = ?"
        with self.get_connection() as conn:
            conn.execute(query, params)

    def list_replay_runs_by_status(
        self, status: ReplayStatus
    ) -> list[ReplayRunRecord]:
        """List replay runs matching a given status in chronological order."""
        query = """
        SELECT * FROM replay_runs
        WHERE status = ?
        ORDER BY started_at_utc ASC, replay_id ASC
        """
        with self.get_connection() as conn:
            rows = conn.execute(query, (status,)).fetchall()
            return [self._row_to_replay_run(r) for r in rows]

    def insert_replay_observation(self, record: SignalObservationRecord) -> bool:
        """Insert a replay observation with origin='REPLAY'; returns False on duplicate."""
        query = """
        INSERT INTO signal_observations (
            signal_id, symbol, bar_ts, strategy_id, order_type, state,
            entry_px, sl_px, tp_px, lot_virtual,
            partial_skipped_min_lot, r_realized_net, exit_reason,
            origin, replay_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self.get_connection() as conn:
                conn.execute(
                    query,
                    (
                        record.signal_id,
                        record.symbol,
                        record.bar_ts,
                        record.strategy_id,
                        record.order_type,
                        record.state,
                        record.entry_px,
                        record.sl_px,
                        record.tp_px,
                        record.lot_virtual,
                        record.partial_skipped_min_lot,
                        record.r_realized_net,
                        record.exit_reason,
                        "REPLAY",
                        record.replay_id,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def insert_replay_blocked_signal(self, record: BlockedSignalRecord) -> bool:
        """Insert a replay blocked signal with origin='REPLAY'; returns False on duplicate."""
        query = """
        INSERT INTO blocked_signals (
            timestamp_utc, pair, direction, strategy_selected, reason_blocked,
            confidence_at_time, would_be_entry_price, current_spread, details,
            origin, replay_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self.get_connection() as conn:
                conn.execute(
                    query,
                    (
                        record.timestamp_utc,
                        record.pair,
                        record.direction,
                        record.strategy_selected,
                        record.reason_blocked,
                        record.confidence_at_time,
                        record.would_be_entry_price,
                        record.current_spread,
                        record.details,
                        "REPLAY",
                        record.replay_id,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def get_observations_by_origin(
        self, origin: RecordOrigin
    ) -> list[SignalObservationRecord]:
        """Retrieve signal observations filtered by origin ('LIVE' or 'REPLAY')."""
        query = """
        SELECT signal_id, symbol, bar_ts, strategy_id, order_type, state,
               entry_px, sl_px, tp_px, lot_virtual, partial_skipped_min_lot,
               r_realized_net, exit_reason, origin, replay_id
        FROM signal_observations
        WHERE origin = ?
        ORDER BY bar_ts ASC, signal_id ASC
        """
        with self.get_connection() as conn:
            rows = conn.execute(query, (origin,)).fetchall()
            return [self._row_to_signal_observation(row) for row in rows]

    def get_blocked_signals_by_origin(
        self, origin: RecordOrigin
    ) -> list[BlockedSignalRecord]:
        """Retrieve blocked signals filtered by origin ('LIVE' or 'REPLAY')."""
        query = """
        SELECT id, timestamp_utc, pair, direction, strategy_selected,
               reason_blocked, confidence_at_time, would_be_entry_price,
               current_spread, details, origin, replay_id
        FROM blocked_signals
        WHERE origin = ?
        ORDER BY timestamp_utc ASC, id ASC
        """
        with self.get_connection() as conn:
            rows = conn.execute(query, (origin,)).fetchall()
            return [self._row_to_blocked_signal(row) for row in rows]

    def advance_bar_cursor_with_config_hash(
        self,
        symbol: str,
        timeframe: Timeframe,
        last_closed_bar_ts: int,
        config_hash: str,
        updated_at_ms: int | None = None,
    ) -> None:
        """Advance bar cursor with config_hash fingerprint."""
        now_ms = (
            updated_at_ms
            if updated_at_ms is not None
            else int(time.time() * 1000)
        )
        cursor = BarCursorRecord(
            symbol=symbol,
            timeframe=timeframe,
            last_closed_bar_ts=last_closed_bar_ts,
            updated_at_ms=now_ms,
            config_hash=config_hash,
        )
        self.advance_bar_cursor(cursor)
