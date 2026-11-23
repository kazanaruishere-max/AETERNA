"""Unit tests for SQLite WAL Database Schema, Constraints, and Seeding.

Verifies:
1. DDL executes cleanly on an empty SQLite database.
2. Foreign Key constraints reject invalid model_version_id.
3. CHECK constraints reject invalid enums (direction, data_tag, status, state, exit_reason).
4. Numerical CHECK constraints reject confidence_score out of range or lot_size < 0.01.
5. Baseline model 'v1.0.0-rulebased' auto-seeded on first run.
6. Composite PK (pair, timeframe, timestamp_utc, source) allows Exness and OANDA
   candles at the exact same timestamp without collision or overwrite.
"""

import dataclasses
from pathlib import Path
import sqlite3
import pytest

from engine.models import (
    BarCursorRecord,
    BlockedSignalRecord,
    CandleRecord,
    NewsTelemetryRecord,
    ReplayRunRecord,
    SignalObservationRecord,
    SystemStateRecord,
    TradeRecord,
)
from engine.shared.db import (
    CANONICAL_SCHEMA_PATH,
    DatabaseManager,
    load_canonical_ddl,
)


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    """Fixture providing a temporary clean SQLite database."""
    db_file = tmp_path / "test_trading.db"
    manager = DatabaseManager(db_file)
    manager.init_db()
    return manager


def test_ddl_execution_and_tables_created(db: DatabaseManager) -> None:
    """Verify all 9 tables are created cleanly."""
    with db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = [row["name"] for row in cursor.fetchall()]
        expected_tables = [
            "bar_cursors",
            "blocked_signals",
            "market_candles",
            "model_registry",
            "news_telemetry",
            "replay_runs",
            "signal_observations",
            "system_state",
            "trades",
        ]
        for tbl in expected_tables:
            assert tbl in tables, f"Expected table '{tbl}' was not created."


def test_canonical_schema_file_on_disk() -> None:
    """Verify db/schema.sql contains all 9 canonical table definitions."""
    assert CANONICAL_SCHEMA_PATH.exists(), f"Missing file: {CANONICAL_SCHEMA_PATH}"
    ddl = load_canonical_ddl()
    for tbl in [
        "model_registry",
        "trades",
        "blocked_signals",
        "market_candles",
        "system_state",
        "bar_cursors",
        "signal_observations",
        "news_telemetry",
        "replay_runs",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {tbl}" in ddl, (
            f"Table {tbl} missing in db/schema.sql"
        )


def test_baseline_model_auto_seeded(db: DatabaseManager) -> None:
    """Verify v1.0.0-rulebased is seeded automatically into model_registry."""
    with db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM model_registry WHERE model_version = 'v1.0.0-rulebased'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["status"] == "active"
        assert "rule_based_adx_atr" in row["hyperparameters"]


def test_foreign_key_constraint_rejects_unregistered_model(db: DatabaseManager) -> None:
    """Verify inserting a trade with nonexistent model_version_id raises IntegrityError."""
    invalid_trade = TradeRecord(
        trade_id="TRD-20261030-0001",
        timestamp_entry_utc="2026-10-30T10:00:00Z",
        pair="XAUUSD",
        direction="LONG",
        data_tag="forward_test",
        state_machine_state="NORMAL",
        regime_detected="TRENDING_BULLISH",
        strategy_selected="volatility_breakout",
        confidence_score=75.0,
        hypothesis="Test breakout",
        entry_price=2750.50,
        sl=2740.00,
        tp=2770.00,
        lot_size=0.02,
        spread_at_entry=1.8,
        model_version_id="nonexistent-model-v999",  # NOT in model_registry
    )

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        db.insert_trade(invalid_trade)


def test_foreign_key_accepts_registered_model(db: DatabaseManager) -> None:
    """Verify inserting a trade with a valid model_version_id succeeds."""
    valid_trade = TradeRecord(
        trade_id="TRD-20261030-0002",
        timestamp_entry_utc="2026-10-30T10:00:00Z",
        pair="XAUUSD",
        direction="LONG",
        data_tag="forward_test",
        state_machine_state="NORMAL",
        regime_detected="TRENDING_BULLISH",
        strategy_selected="volatility_breakout",
        confidence_score=80.0,
        hypothesis="Test breakout",
        entry_price=2750.50,
        sl=2740.00,
        tp=2770.00,
        lot_size=0.02,
        spread_at_entry=1.8,
        model_version_id="v1.0.0-rulebased",  # Auto-seeded baseline
    )
    db.insert_trade(valid_trade)

    with db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM trades WHERE trade_id = ?", ("TRD-20261030-0002",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["pair"] == "XAUUSD"
        assert row["direction"] == "LONG"


@pytest.mark.parametrize(
    "invalid_direction",
    ["SIDEWAYS", "BUY", "SELL", "UP", "DOWN", ""],
)
def test_check_constraint_rejects_invalid_direction(
    db: DatabaseManager, invalid_direction: str
) -> None:
    """Verify CHECK constraint on direction IN ('LONG', 'SHORT')."""
    with db.get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO trades (
                    trade_id, timestamp_entry_utc, pair, direction, data_tag,
                    state_machine_state, regime_detected, strategy_selected,
                    confidence_score, hypothesis, entry_price, sl, tp,
                    lot_size, spread_at_entry, model_version_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"TRD-ERR-{invalid_direction}",
                    "2026-10-30T10:00:00Z",
                    "XAUUSD",
                    invalid_direction,
                    "forward_test",
                    "NORMAL",
                    "TRENDING",
                    "strat1",
                    70.0,
                    "hypo",
                    2750.0,
                    2740.0,
                    2770.0,
                    0.01,
                    1.5,
                    "v1.0.0-rulebased",
                ),
            )


def test_numerical_check_constraints(db: DatabaseManager) -> None:
    """Verify confidence_score [0, 100] and lot_size >= 0.01 checks."""
    # Test confidence_score > 100
    with db.get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO trades (
                    trade_id, timestamp_entry_utc, pair, direction, data_tag,
                    state_machine_state, regime_detected, strategy_selected,
                    confidence_score, hypothesis, entry_price, sl, tp,
                    lot_size, spread_at_entry, model_version_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TRD-BAD-CONF",
                    "2026-10-30T10:00:00Z",
                    "XAUUSD",
                    "LONG",
                    "forward_test",
                    "NORMAL",
                    "TRENDING",
                    "strat1",
                    105.0,  # Invalid: > 100
                    "hypo",
                    2750.0,
                    2740.0,
                    2770.0,
                    0.01,
                    1.5,
                    "v1.0.0-rulebased",
                ),
            )

        # Test lot_size < 0.01
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO trades (
                    trade_id, timestamp_entry_utc, pair, direction, data_tag,
                    state_machine_state, regime_detected, strategy_selected,
                    confidence_score, hypothesis, entry_price, sl, tp,
                    lot_size, spread_at_entry, model_version_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TRD-BAD-LOT",
                    "2026-10-30T10:00:00Z",
                    "XAUUSD",
                    "LONG",
                    "forward_test",
                    "NORMAL",
                    "TRENDING",
                    "strat1",
                    80.0,
                    "hypo",
                    2750.0,
                    2740.0,
                    2770.0,
                    0.005,  # Invalid: < 0.01
                    1.5,
                    "v1.0.0-rulebased",
                ),
            )


def test_market_candles_composite_pk_with_source(db: DatabaseManager) -> None:
    """Verify composite PK (pair, timeframe, timestamp_utc, source) allows Exness and OANDA

    to co-exist at the identical timestamp without collision or overwrite.
    """
    ts = "2026-10-30T14:30:00Z"

    candle_exness = CandleRecord(
        pair="XAUUSD",
        timeframe="M15",
        timestamp_utc=ts,
        source="exness_mt5",
        open=2740.10,
        high=2745.00,
        low=2739.50,
        close=2743.80,
        tick_volume=1250,
    )

    candle_oanda = CandleRecord(
        pair="XAUUSD",
        timeframe="M15",
        timestamp_utc=ts,
        source="oanda_v20",
        open=2740.25,
        high=2745.15,
        low=2739.60,
        close=2743.95,
        tick_volume=820,
    )

    # Insert both candles
    db.insert_candle(candle_exness)
    db.insert_candle(candle_oanda)

    # Both must be present in database independently
    exness_candles = db.get_candles("XAUUSD", "M15", "exness_mt5", limit=10)
    oanda_candles = db.get_candles("XAUUSD", "M15", "oanda_v20", limit=10)

    assert len(exness_candles) == 1
    assert len(oanda_candles) == 1
    assert exness_candles[0].source == "exness_mt5"
    assert exness_candles[0].close == 2743.80
    assert oanda_candles[0].source == "oanda_v20"
    assert oanda_candles[0].close == 2743.95


def test_system_state_singleton_and_update(db: DatabaseManager) -> None:
    """Verify system_state singleton enforcement (id=1) and update mechanics."""
    initial_state = SystemStateRecord(
        state="NORMAL",
        current_spread=1.8,
        spread_baseline=1.75,
        spread_z_score=0.25,
        active_positions_count=0,
        equity_usd=1000.0,
        daily_pnl_usd=0.0,
        trades_today_count=0,
        last_updated_utc="2026-10-30T07:00:00Z",
    )
    db.set_system_state(initial_state)

    retrieved = db.get_system_state()
    assert retrieved is not None
    assert retrieved.state == "NORMAL"
    assert retrieved.current_spread == 1.8
    assert retrieved.equity_usd == 1000.0

    # Update state to PAUSED during simulated news event
    updated_state = SystemStateRecord(
        state="PAUSED",
        current_spread=4.5,
        spread_baseline=1.80,
        spread_z_score=3.2,
        active_positions_count=0,
        equity_usd=1000.0,
        daily_pnl_usd=0.0,
        trades_today_count=0,
        last_news_event="US Non-Farm Payrolls",
        last_updated_utc="2026-10-30T12:30:00Z",
    )
    db.set_system_state(updated_state)

    state_after = db.get_system_state()
    assert state_after is not None
    assert state_after.state == "PAUSED"
    assert state_after.spread_z_score == 3.2
    assert state_after.last_news_event == "US Non-Farm Payrolls"

    # Verify CHECK constraint prevents id != 1
    with db.get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO system_state (
                    id, state, current_spread, spread_baseline, spread_z_score,
                    active_positions_count, equity_usd, daily_pnl_usd, trades_today_count,
                    last_updated_utc
                ) VALUES (2, 'NORMAL', 1.5, 1.5, 0.0, 0, 1000.0, 0.0, 0, '2026-10-30T00:00:00Z')
                """
            )


def test_bar_cursor_lifecycle_and_idempotency(db: DatabaseManager) -> None:
    """Verify cursor insert, advance, PK (symbol, timeframe) integrity, and restart persistence."""
    symbol = "XAUUSD"
    assert db.get_bar_cursor(symbol, "M15") is None

    initial = BarCursorRecord(
        symbol=symbol,
        timeframe="M15",
        last_closed_bar_ts=1_700_000_000,
        updated_at_ms=1_700_000_000_000,
    )
    db.advance_bar_cursor(initial)
    assert db.get_bar_cursor(symbol, "M15") == initial

    advanced = BarCursorRecord(
        symbol=symbol,
        timeframe="M15",
        last_closed_bar_ts=1_700_000_900,
        updated_at_ms=1_700_001_000_000,
    )
    db.advance_bar_cursor(advanced)
    assert db.get_bar_cursor(symbol, "M15") == advanced

    # PK (symbol, timeframe): re-advancing the same key replaces, never duplicates.
    db.advance_bar_cursor(advanced)
    with db.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM bar_cursors;").fetchone()
    assert row is not None
    assert row["total"] == 1

    # Restart mid-bar: a fresh manager reads the persisted cursor.
    restarted = DatabaseManager(db.db_path)
    restarted.init_db()
    assert restarted.get_bar_cursor(symbol, "M15") == advanced


def test_signal_observation_unique_constraint_rejects_duplicates(
    db: DatabaseManager,
) -> None:
    """Verify duplicate (symbol, bar_ts, strategy_id) returns False without a second row."""
    signal = SignalObservationRecord(
        signal_id="SIG-M15-0001",
        symbol="XAUUSD",
        bar_ts=1_745_000_000,
        strategy_id="volatility_breakout_m15",
        order_type="MARKET",
        state="PENDING_VIRTUAL",
        entry_px=2750.00,
        sl_px=2730.00,
        tp_px=2775.00,
        lot_virtual=0.02,
    )
    assert db.insert_signal_observation(signal) is True

    duplicate = dataclasses.replace(signal, signal_id="SIG-M15-0002")
    assert db.insert_signal_observation(duplicate) is False

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM signal_observations;"
        ).fetchone()
    assert row is not None
    assert row["total"] == 1


def test_signal_observation_update_lifecycle(db: DatabaseManager) -> None:
    """Verify PENDING_VIRTUAL -> OPEN_VIRTUAL -> CLOSED_PROFIT with realized R update."""
    signal = SignalObservationRecord(
        signal_id="SIG-LIFECYCLE-001",
        symbol="XAUUSD",
        bar_ts=1_745_000_900,
        strategy_id="volatility_breakout_m15",
        order_type="MARKET",
        state="PENDING_VIRTUAL",
        entry_px=2750.00,
        sl_px=2730.00,
        tp_px=2775.00,
        lot_virtual=0.02,
    )
    assert db.insert_signal_observation(signal) is True
    assert db.update_signal_observation(signal.signal_id, state="OPEN_VIRTUAL") is True
    assert (
        db.update_signal_observation(
            signal.signal_id,
            state="CLOSED_PROFIT",
            r_realized_net=1.25,
            exit_reason="tp_hit",
        )
        is True
    )

    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT state, r_realized_net, exit_reason
            FROM signal_observations
            WHERE signal_id = ?
            """,
            (signal.signal_id,),
        ).fetchone()
    assert row is not None
    assert row["state"] == "CLOSED_PROFIT"
    assert row["r_realized_net"] == 1.25
    assert row["exit_reason"] == "tp_hit"

    assert (
        db.update_signal_observation("SIG-NONEXISTENT", state="OPEN_VIRTUAL") is False
    )


def test_news_telemetry_persistence_roundtrip(db: DatabaseManager) -> None:
    """Verify news telemetry persistence and read-back roundtrip."""
    telemetry = NewsTelemetryRecord(
        event_id="FRED-CPI-2026-10-30",
        symbol="XAUUSD",
        release_ts=1_745_956_000,
        actual_val=0.12,
        consensus_val=0.05,
        peak_spread_pts=2.50,
        max_z_score=3.40,
        range_1m=0.80,
        range_5m=1.50,
        range_15m=2.20,
        range_60m=3.00,
    )
    db.insert_news_telemetry(telemetry)

    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT event_id, symbol, release_ts, actual_val, consensus_val,
                   peak_spread_pts, max_z_score, range_1m, range_5m,
                   range_15m, range_60m
            FROM news_telemetry
            WHERE event_id = ? AND symbol = ? AND release_ts = ?
            """,
            (telemetry.event_id, telemetry.symbol, telemetry.release_ts),
        ).fetchone()
    assert row is not None
    assert row["event_id"] == telemetry.event_id
    assert row["actual_val"] == telemetry.actual_val
    assert row["consensus_val"] == telemetry.consensus_val
    assert row["peak_spread_pts"] == telemetry.peak_spread_pts
    assert row["max_z_score"] == telemetry.max_z_score
    assert row["range_1m"] == telemetry.range_1m
    assert row["range_5m"] == telemetry.range_5m
    assert row["range_15m"] == telemetry.range_15m
    assert row["range_60m"] == telemetry.range_60m


def test_new_domain_models_are_frozen_immutable() -> None:
    """Verify new domain dataclasses are frozen (attribute assignment raises)."""
    cursor_record = BarCursorRecord(
        symbol="XAUUSD",
        timeframe="M15",
        last_closed_bar_ts=1,
        updated_at_ms=1,
    )
    signal_record = SignalObservationRecord(
        signal_id="SIG-FROZEN-001",
        symbol="XAUUSD",
        bar_ts=1,
        strategy_id="strategy",
        order_type="MARKET",
        state="PENDING_VIRTUAL",
        entry_px=2700.00,
        sl_px=2690.00,
        tp_px=2720.00,
        lot_virtual=0.01,
    )
    news_record = NewsTelemetryRecord(
        event_id="EVT-FROZEN-001",
        symbol="XAUUSD",
        release_ts=1,
        peak_spread_pts=1.0,
        max_z_score=1.0,
    )
    replay_record = ReplayRunRecord(
        replay_id="REP-FROZEN-001",
        symbol="XAUUSD",
        timeframe="M15",
        last_cursor_ts=1,
        first_missed_bar_ts=2,
        last_missed_bar_ts=3,
        missed_count=1,
        started_at_utc="2026-11-23T00:00:00Z",
        status="PENDING",
        replay_mode="STRATEGY_ONLY",
        config_hash="cfg",
        strategy_id="strat",
        model_id="model",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(cursor_record, "last_closed_bar_ts", 2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(signal_record, "state", "OPEN_VIRTUAL")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(news_record, "max_z_score", 2.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(replay_record, "status", "COMPLETED")


def test_replay_runs_schema_and_check_constraints(db: DatabaseManager) -> None:
    """Verify replay_runs table schema and CHECK constraints on status and replay_mode."""
    with db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='replay_runs';"
        )
        assert cursor.fetchone() is not None, "Table replay_runs missing."

        conn.execute(
            """
            INSERT INTO replay_runs (
                replay_id, symbol, timeframe, last_cursor_ts,
                first_missed_bar_ts, last_missed_bar_ts, missed_count,
                started_at_utc, status, replay_mode, config_hash,
                strategy_id, model_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "REP-20261123-0001",
                "XAUUSD",
                "M15",
                1795407300,
                1795408200,
                1795410000,
                3,
                "2026-11-23T05:26:48Z",
                "RUNNING",
                "STRATEGY_ONLY",
                "sha256-test-cfg",
                "volatility_breakout_m15",
                "kronos_h4_v1",
            ),
        )
        row = conn.execute(
            "SELECT * FROM replay_runs WHERE replay_id = ?",
            ("REP-20261123-0001",),
        ).fetchone()
        assert row is not None
        assert row["observations_created"] == 0
        assert row["blocked_created"] == 0
        assert row["error_text"] is None
        assert row["finished_at_utc"] is None

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO replay_runs (
                    replay_id, symbol, timeframe, last_cursor_ts,
                    first_missed_bar_ts, last_missed_bar_ts, missed_count,
                    started_at_utc, status, replay_mode, config_hash,
                    strategy_id, model_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "REP-ERR-STATUS",
                    "XAUUSD",
                    "M15",
                    1795407300,
                    1795408200,
                    1795410000,
                    3,
                    "2026-11-23T05:26:48Z",
                    "INVALID_STATUS",
                    "STRATEGY_ONLY",
                    "sha256-test-cfg",
                    "strat",
                    "model",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO replay_runs (
                    replay_id, symbol, timeframe, last_cursor_ts,
                    first_missed_bar_ts, last_missed_bar_ts, missed_count,
                    started_at_utc, status, replay_mode, config_hash,
                    strategy_id, model_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "REP-ERR-MODE",
                    "XAUUSD",
                    "M15",
                    1795407300,
                    1795408200,
                    1795410000,
                    3,
                    "2026-11-23T05:26:48Z",
                    "RUNNING",
                    "INVALID_MODE",
                    "sha256-test-cfg",
                    "strat",
                    "model",
                ),
            )


def test_origin_default_live_and_constraint(db: DatabaseManager) -> None:
    """Verify origin defaults to 'LIVE' and CHECK rejects unauthorized origins."""
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO signal_observations (
                signal_id, symbol, bar_ts, strategy_id, order_type,
                state, entry_px, sl_px, tp_px, lot_virtual
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SIG-ORIG-01",
                "XAUUSD",
                1700000000,
                "strat",
                "BUY",
                "PENDING",
                2700.0,
                2690.0,
                2720.0,
                0.01,
            ),
        )
        row = conn.execute(
            "SELECT origin FROM signal_observations WHERE signal_id = 'SIG-ORIG-01'"
        ).fetchone()
        assert row is not None and row["origin"] == "LIVE"

        conn.execute(
            """
            INSERT INTO blocked_signals (
                timestamp_utc, pair, direction, strategy_selected,
                reason_blocked, confidence_at_time, would_be_entry_price, current_spread
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-11-23T00:00:00Z",
                "XAUUSD",
                "LONG",
                "strat",
                "risk_gate_daily_loss",
                80.0,
                2700.0,
                1.5,
            ),
        )
        row_b = conn.execute(
            "SELECT origin FROM blocked_signals WHERE timestamp_utc = '2026-11-23T00:00:00Z'"
        ).fetchone()
        assert row_b is not None and row_b["origin"] == "LIVE"

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO signal_observations (
                    signal_id, symbol, bar_ts, strategy_id, order_type,
                    state, entry_px, sl_px, tp_px, lot_virtual, origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "SIG-BAD-ORIG",
                    "XAUUSD",
                    1700000900,
                    "strat",
                    "BUY",
                    "PENDING",
                    2700.0,
                    2690.0,
                    2720.0,
                    0.01,
                    "BACKTEST",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                """
                INSERT INTO blocked_signals (
                    timestamp_utc, pair, direction, strategy_selected,
                    reason_blocked, confidence_at_time, would_be_entry_price, current_spread, origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-11-23T00:15:00Z",
                    "XAUUSD",
                    "LONG",
                    "strat",
                    "risk_gate_daily_loss",
                    80.0,
                    2700.0,
                    1.5,
                    "UNKNOWN",
                ),
            )


def test_replay_id_nullable(db: DatabaseManager) -> None:
    """Verify replay_id column is nullable across signal_observations and blocked_signals."""
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO signal_observations (
                signal_id, symbol, bar_ts, strategy_id, order_type,
                state, entry_px, sl_px, tp_px, lot_virtual, replay_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SIG-REPID-NULL",
                "XAUUSD",
                1700001000,
                "strat",
                "BUY",
                "PENDING",
                2700.0,
                2690.0,
                2720.0,
                0.01,
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO signal_observations (
                signal_id, symbol, bar_ts, strategy_id, order_type,
                state, entry_px, sl_px, tp_px, lot_virtual, origin, replay_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SIG-REPID-VAL",
                "XAUUSD",
                1700002000,
                "strat",
                "BUY",
                "PENDING",
                2700.0,
                2690.0,
                2720.0,
                0.01,
                "REPLAY",
                "REP-001",
            ),
        )
        conn.execute(
            """
            INSERT INTO blocked_signals (
                timestamp_utc, pair, direction, strategy_selected,
                reason_blocked, confidence_at_time, would_be_entry_price, current_spread, replay_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-11-23T01:00:00Z",
                "XAUUSD",
                "LONG",
                "strat",
                "risk_gate_daily_loss",
                80.0,
                2700.0,
                1.5,
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO blocked_signals (
                timestamp_utc, pair, direction, strategy_selected,
                reason_blocked, confidence_at_time, would_be_entry_price, current_spread, origin, replay_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-11-23T01:15:00Z",
                "XAUUSD",
                "LONG",
                "strat",
                "risk_gate_daily_loss",
                80.0,
                2700.0,
                1.5,
                "REPLAY",
                "REP-001",
            ),
        )
        r1 = conn.execute(
            "SELECT replay_id FROM signal_observations WHERE signal_id = 'SIG-REPID-NULL'"
        ).fetchone()
        r2 = conn.execute(
            "SELECT replay_id FROM signal_observations WHERE signal_id = 'SIG-REPID-VAL'"
        ).fetchone()
        r3 = conn.execute(
            "SELECT replay_id FROM blocked_signals WHERE timestamp_utc = '2026-11-23T01:00:00Z'"
        ).fetchone()
        r4 = conn.execute(
            "SELECT replay_id FROM blocked_signals WHERE timestamp_utc = '2026-11-23T01:15:00Z'"
        ).fetchone()
        assert r1 is not None and r1["replay_id"] is None
        assert r2 is not None and r2["replay_id"] == "REP-001"
        assert r3 is not None and r3["replay_id"] is None
        assert r4 is not None and r4["replay_id"] == "REP-001"


def test_bar_cursors_config_hash_nullable(db: DatabaseManager) -> None:
    """Verify config_hash column in bar_cursors is nullable and persists values."""
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO bar_cursors (symbol, timeframe, last_closed_bar_ts, updated_at_ms, config_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("XAUUSD", "M15", 1700000000, 1700000000000, None),
        )
        row_null = conn.execute(
            "SELECT config_hash FROM bar_cursors WHERE symbol='XAUUSD' AND timeframe='M15'"
        ).fetchone()
        assert row_null is not None and row_null["config_hash"] is None

        conn.execute(
            """
            INSERT OR REPLACE INTO bar_cursors (symbol, timeframe, last_closed_bar_ts, updated_at_ms, config_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("XAUUSD", "H1", 1700000000, 1700000000000, "sha256-deadbeef"),
        )
        row_val = conn.execute(
            "SELECT config_hash FROM bar_cursors WHERE symbol='XAUUSD' AND timeframe='H1'"
        ).fetchone()
        assert row_val is not None and row_val["config_hash"] == "sha256-deadbeef"


def test_blocked_signals_unique_dedup_index(db: DatabaseManager) -> None:
    """Verify OD-04 unique index idx_blocked_signals_dedup exists and deduplicates."""
    with db.get_connection() as conn:
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_blocked_signals_dedup';"
        ).fetchone()
        assert idx is not None, (
            "Index idx_blocked_signals_dedup does not exist in sqlite_master."
        )

        insert_sql = """
        INSERT INTO blocked_signals (
            timestamp_utc, pair, direction, strategy_selected,
            reason_blocked, confidence_at_time, would_be_entry_price,
            current_spread, origin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn.execute(
            insert_sql,
            (
                "2026-11-23T04:30:00Z",
                "XAUUSD",
                "LONG",
                "strat_vb",
                "risk_gate_daily_loss",
                75.0,
                2750.0,
                1.5,
                "REPLAY",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            conn.execute(
                insert_sql,
                (
                    "2026-11-23T04:30:00Z",
                    "XAUUSD",
                    "LONG",
                    "strat_vb",
                    "risk_gate_daily_loss",
                    80.0,
                    2751.0,
                    1.6,
                    "REPLAY",
                ),
            )

        # Same tuple with origin='LIVE' succeeds because origin is part of unique index
        conn.execute(
            insert_sql,
            (
                "2026-11-23T04:30:00Z",
                "XAUUSD",
                "LONG",
                "strat_vb",
                "risk_gate_daily_loss",
                75.0,
                2750.0,
                1.5,
                "LIVE",
            ),
        )
        rows = conn.execute("SELECT COUNT(*) AS total FROM blocked_signals;").fetchone()
        assert rows is not None and rows["total"] == 2


def test_dataclass_defaults_backward_compatible() -> None:
    """Verify model dataclasses retain backward compatibility for callers without new fields."""
    cursor = BarCursorRecord(
        symbol="XAUUSD",
        timeframe="M15",
        last_closed_bar_ts=1700000000,
        updated_at_ms=1700000000000,
    )
    assert cursor.config_hash is None

    obs = SignalObservationRecord(
        signal_id="SIG-BC-001",
        symbol="XAUUSD",
        bar_ts=1700000000,
        strategy_id="strat",
        order_type="MARKET",
        state="PENDING",
        entry_px=2750.0,
        sl_px=2740.0,
        tp_px=2770.0,
        lot_virtual=0.01,
    )
    assert obs.origin == "LIVE"
    assert obs.replay_id is None

    blocked = BlockedSignalRecord(
        timestamp_utc="2026-11-23T00:00:00Z",
        pair="XAUUSD",
        direction="LONG",
        strategy_selected="strat",
        reason_blocked="risk_gate_daily_loss",
        confidence_at_time=80.0,
        would_be_entry_price=2750.0,
        current_spread=1.5,
    )
    assert blocked.origin == "LIVE"
    assert blocked.replay_id is None

    replay = ReplayRunRecord(
        replay_id="REP-001",
        symbol="XAUUSD",
        timeframe="M15",
        last_cursor_ts=1700000000,
        first_missed_bar_ts=1700000900,
        last_missed_bar_ts=1700001800,
        missed_count=2,
        started_at_utc="2026-11-23T01:00:00Z",
        status="RUNNING",
        replay_mode="STRATEGY_ONLY",
        config_hash="sha256-hash",
        strategy_id="strat",
        model_id="model",
    )
    assert replay.finished_at_utc is None
    assert replay.observations_created == 0
    assert replay.blocked_created == 0
    assert replay.error_text is None
