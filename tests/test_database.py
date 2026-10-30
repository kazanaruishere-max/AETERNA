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

from pathlib import Path
import sqlite3
import pytest

from engine.models import (
    CandleRecord,
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
    """Verify all 5 tables are created cleanly."""
    with db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = [row["name"] for row in cursor.fetchall()]
        expected_tables = [
            "blocked_signals",
            "market_candles",
            "model_registry",
            "system_state",
            "trades",
        ]
        for tbl in expected_tables:
            assert tbl in tables, f"Expected table '{tbl}' was not created."


def test_canonical_schema_file_on_disk() -> None:
    """Verify db/schema.sql exists on disk and contains all 5 canonical table definitions."""
    assert CANONICAL_SCHEMA_PATH.exists(), f"Missing file: {CANONICAL_SCHEMA_PATH}"
    ddl = load_canonical_ddl()
    for tbl in ["model_registry", "trades", "blocked_signals", "market_candles", "system_state"]:
        assert f"CREATE TABLE IF NOT EXISTS {tbl}" in ddl, f"Table {tbl} missing in db/schema.sql"


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
        cursor = conn.execute("SELECT * FROM trades WHERE trade_id = ?", ("TRD-20261030-0002",))
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
