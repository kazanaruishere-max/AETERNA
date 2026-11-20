"""Unit tests for production ExecutionEmergencyHandler.

Module: tests.test_emergency_handler
Responsibility: Verifies deterministic emergency handling:
1. Force close all liquidates positions via ExnessBrokerBridge and returns results.
2. Force close all logs explicit NO_OPEN_POSITIONS when position list is empty.
3. Bridge errors are logged and captured in results, never swallowed.
4. Hard emergency killswitch writes physical EMERGENCY_KILLSWITCH.lock with watchdog payload.
5. Killswitch write failure safely returns False.
6. System state transitions (PAUSED / NORMAL) are persisted in SQLite WAL database.
7. engine/main.py uses production EmergencyHandler instead of MockEmergencyHandler.
8. Killswitch writes lockfile even when DB init fails (fail-closed, cheapest test).
9. Zero fabricated equity (no 1000.0) when equity cannot be resolved.
10. Deviation from operator is forwarded to ExnessBrokerBridge.
11. sqlite3.OperationalError and sqlite3.DatabaseError do not prevent lockfile generation.
12. DB update failure during pause does not claim PAUSED is persisted.
Covers: REQ-RUNTIME-007, REQ-EXE-001, REQ-TEL-003
Owner: aeterna-verifier
Tier: Tier A
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.execution.broker_bridge import ExnessBrokerBridge, PartialCloseResult
from engine.execution.emergency_handler import EmergencyHandler
from engine.ingestion.python.exness_client import ExnessClient
from engine.models import SystemStateRecord
from engine.shared.db.database import DatabaseManager


@dataclass
class DummyMT5Position:
    ticket: int
    identifier: int
    symbol: str
    volume: float
    type: int  # 0: BUY, 1: SELL
    price_open: float = 2750.0


def _create_mock_client(connected: bool = True) -> tuple[ExnessClient, MagicMock]:
    client = MagicMock(spec=ExnessClient)
    client.connected = connected
    client.lock = MagicMock()
    client.lock.__enter__ = MagicMock(return_value=None)
    client.lock.__exit__ = MagicMock(return_value=None)
    mock_mt5 = MagicMock()
    client.mt5 = mock_mt5 if connected else None
    return client, mock_mt5


def test_force_close_all_with_open_positions() -> None:
    """Verify execute_force_close_all closes each open position via broker bridge."""
    client, mock_mt5 = _create_mock_client(connected=True)
    pos1 = DummyMT5Position(ticket=101, identifier=101, symbol="XAUUSDm", volume=0.04, type=0)
    pos2 = DummyMT5Position(ticket=102, identifier=102, symbol="XAUUSDm", volume=0.02, type=1)
    mock_mt5.positions_get.return_value = (pos1, pos2)

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = client
    mock_bridge.close_partial_position.side_effect = [
        PartialCloseResult(success=True, closed_ticket=101, new_ticket=None, closed_lot=0.04, remaining_lot=0.0, executed_price=2755.0),
        PartialCloseResult(success=True, closed_ticket=102, new_ticket=None, closed_lot=0.02, remaining_lot=0.0, executed_price=2745.0),
    ]

    handler = EmergencyHandler(bridge=mock_bridge, client=client)
    results = handler.execute_force_close_all(max_deviation_pts=50)

    assert len(results) == 2
    assert results[0].ticket == 101 and results[0].success is True and results[0].closed_lot == 0.04
    assert results[1].ticket == 102 and results[1].success is True and results[1].closed_lot == 0.02
    assert mock_bridge.close_partial_position.call_count == 2
    mock_bridge.close_partial_position.assert_any_call(
        ticket=101, position_identifier=101, symbol="XAUUSDm", direction="BUY", close_lot=0.04, deviation=50
    )
    mock_bridge.close_partial_position.assert_any_call(
        ticket=102, position_identifier=102, symbol="XAUUSDm", direction="SELL", close_lot=0.02, deviation=50
    )


def test_force_close_all_forwards_custom_deviation_to_bridge() -> None:
    """Verify custom max_deviation_pts is forwarded to bridge.close_partial_position."""
    client, mock_mt5 = _create_mock_client(connected=True)
    pos = DummyMT5Position(ticket=501, identifier=501, symbol="XAUUSDm", volume=0.05, type=0)
    mock_mt5.positions_get.return_value = (pos,)

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = client
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=True, closed_ticket=501, new_ticket=None, closed_lot=0.05, remaining_lot=0.0, executed_price=2750.0
    )

    handler = EmergencyHandler(bridge=mock_bridge, client=client)
    results = handler.execute_force_close_all(max_deviation_pts=75)

    assert len(results) == 1
    assert results[0].success is True
    mock_bridge.close_partial_position.assert_called_once_with(
        ticket=501, position_identifier=501, symbol="XAUUSDm", direction="BUY", close_lot=0.05, deviation=75
    )


def test_force_close_all_no_positions_logs_explicit_no_open_positions(caplog: pytest.LogCaptureFixture) -> None:
    """Verify empty open position list explicitly logs NO_OPEN_POSITIONS and returns []."""
    client, mock_mt5 = _create_mock_client(connected=True)
    mock_mt5.positions_get.return_value = ()

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = client
    handler = EmergencyHandler(bridge=mock_bridge, client=client)

    with caplog.at_level("INFO"):
        results = handler.execute_force_close_all(max_deviation_pts=50)

    assert results == []
    assert any("NO_OPEN_POSITIONS" in record.message for record in caplog.records)
    mock_bridge.close_partial_position.assert_not_called()


def test_force_close_all_bridge_failure_logged_not_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    """Verify broker rejection is recorded in result and logged at ERROR level without swallowing."""
    client, mock_mt5 = _create_mock_client(connected=True)
    pos = DummyMT5Position(ticket=201, identifier=201, symbol="XAUUSDm", volume=0.01, type=0)
    mock_mt5.positions_get.return_value = (pos,)

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = client
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=False,
        closed_ticket=201,
        new_ticket=None,
        closed_lot=0.0,
        remaining_lot=0.01,
        executed_price=None,
        error_code=10016,
        error_message="TRADE_RETCODE_TOO_CLOSE",
    )

    handler = EmergencyHandler(bridge=mock_bridge, client=client)

    with caplog.at_level("ERROR"):
        results = handler.execute_force_close_all(max_deviation_pts=50)

    assert len(results) == 1
    assert results[0].ticket == 201
    assert results[0].success is False
    assert "TRADE_RETCODE_TOO_CLOSE" in (results[0].error_message or "")
    assert any("Failed to force close position 201" in record.message for record in caplog.records)


def test_force_close_all_exception_handled(caplog: pytest.LogCaptureFixture) -> None:
    """Verify runtime exception during bridge call is logged and captured as failure."""
    client, mock_mt5 = _create_mock_client(connected=True)
    pos = DummyMT5Position(ticket=301, identifier=301, symbol="XAUUSDm", volume=0.01, type=1)
    mock_mt5.positions_get.return_value = (pos,)

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = client
    mock_bridge.close_partial_position.side_effect = RuntimeError("Bridge transport severed")

    handler = EmergencyHandler(bridge=mock_bridge, client=client)

    with caplog.at_level("ERROR"):
        results = handler.execute_force_close_all(max_deviation_pts=50)

    assert len(results) == 1
    assert results[0].ticket == 301
    assert results[0].success is False
    assert "Bridge transport severed" in (results[0].error_message or "")
    assert any("Exception during force close of position 301" in record.message for record in caplog.records)


def test_force_close_all_client_disconnected() -> None:
    """Verify disconnected MT5 client returns [] without throwing unhandled exception."""
    client, _ = _create_mock_client(connected=False)
    handler = EmergencyHandler(client=client)
    assert handler.execute_force_close_all() == []


def test_emergency_killswitch_writes_lockfile_with_watchdog_payload(tmp_path: Path) -> None:
    """Verify execute_emergency_killswitch creates lockfile compatible with Go watchdog payload."""
    lock_file = tmp_path / "EMERGENCY_KILLSWITCH.lock"
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.get_system_state.return_value = SystemStateRecord(
        id=1,
        state="NORMAL",
        current_spread=1.2,
        spread_baseline=1.0,
        spread_z_score=0.5,
        active_positions_count=0,
        equity_usd=1250.50,
        daily_pnl_usd=50.0,
        trades_today_count=1,
        last_updated_utc="2026-11-20T12:00:00Z",
    )

    handler = EmergencyHandler(
        db_manager=mock_db,
        lockfile_path=lock_file,
        peak_equity=1500.0,
    )

    assert not lock_file.exists()
    ok = handler.execute_emergency_killswitch()
    assert ok is True
    assert lock_file.exists()
    assert handler.is_killed is True
    assert handler.is_paused is True
    mock_db.set_system_state.assert_called_once()

    data = json.loads(lock_file.read_text(encoding="utf-8"))
    assert "timestamp_utc" in data
    assert data["trigger_reason"] == "MANUAL_TELEGRAM_KILLSWITCH"
    assert data["peak_equity"] == 1500.0
    assert data["current_equity"] == 1250.50
    assert data["equity_source"] == "DB_SYSTEM_STATE"
    # drawdown = (1500 - 1250.50) / 1500 * 100 = 16.6333 %
    assert pytest.approx(data["drawdown_pct"], rel=1e-3) == 16.6333


def test_emergency_killswitch_db_init_failure_still_writes_lockfile(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Cheapest test: inject DB init failure and assert EMERGENCY_KILLSWITCH.lock is still written."""
    lock_file = tmp_path / "EMERGENCY_KILLSWITCH.lock"
    assert not lock_file.exists()

    with patch("engine.shared.db.database.DatabaseManager.init_db", side_effect=RuntimeError("SQLite I/O failure")):
        handler = EmergencyHandler(
            db_manager=None,
            lockfile_path=lock_file,
            db_path=str(tmp_path / "corrupt.db"),
            peak_equity=0.0,
        )

        with caplog.at_level("ERROR"):
            ok = handler.execute_emergency_killswitch()

    assert ok is True
    assert lock_file.exists()
    assert handler.is_killed is True

    payload = json.loads(lock_file.read_text(encoding="utf-8"))
    assert payload["trigger_reason"] == "MANUAL_TELEGRAM_KILLSWITCH"
    assert payload["current_equity"] == 0.0
    assert payload["equity_source"] == "UNAVAILABLE"
    assert any("Failed to initialize DatabaseManager" in record.message for record in caplog.records)


def test_emergency_killswitch_no_fabricated_equity(tmp_path: Path) -> None:
    """Verify that when equity cannot be read, 1000.0 is never fabricated into payload."""
    lock_file = tmp_path / "EMERGENCY_KILLSWITCH.lock"
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.get_system_state.return_value = None  # No system state

    handler = EmergencyHandler(
        db_manager=mock_db,
        client=None,
        lockfile_path=lock_file,
        peak_equity=0.0,
    )

    ok = handler.execute_emergency_killswitch()
    assert ok is True
    raw_content = lock_file.read_text(encoding="utf-8")
    assert "1000" not in raw_content, "No fabricated 1000.0 equity allowed in payload"

    payload = json.loads(raw_content)
    assert payload["current_equity"] == 0.0
    assert payload["peak_equity"] == 0.0
    assert payload["drawdown_pct"] == 0.0
    assert payload["equity_source"] == "UNAVAILABLE"


def test_emergency_killswitch_write_failure_returns_false(tmp_path: Path) -> None:
    """Verify lockfile write error returns False and does not mark engine killed."""
    invalid_path = tmp_path / "nonexistent_dir" / "readonly_sub" / "lock.lock"
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.get_system_state.return_value = None
    handler = EmergencyHandler(lockfile_path=invalid_path, db_manager=mock_db)

    with patch("builtins.open", side_effect=OSError("Permission denied")):
        ok = handler.execute_emergency_killswitch()

    assert ok is False
    assert handler.is_killed is False


def test_set_system_state_paused_and_normal(tmp_path: Path) -> None:
    """Verify set_system_state_paused and set_system_state_normal modify SQLite WAL state."""
    db_file = tmp_path / "test_trading.db"
    db_mgr = DatabaseManager(db_path=str(db_file))
    db_mgr.init_db()

    handler = EmergencyHandler(db_manager=db_mgr, db_path=str(db_file))

    # 1. Transition to PAUSED
    ok_pause = handler.set_system_state_paused()
    assert ok_pause is True
    assert handler.is_paused is True
    state_rec = db_mgr.get_system_state()
    assert state_rec is not None
    assert state_rec.state == "PAUSED"

    # 2. Transition back to NORMAL
    ok_normal = handler.set_system_state_normal()
    assert ok_normal is True
    assert handler.is_paused is False
    state_rec2 = db_mgr.get_system_state()
    assert state_rec2 is not None
    assert state_rec2.state == "NORMAL"


def test_main_py_uses_real_emergency_handler() -> None:
    """Verify engine/main.py uses production EmergencyHandler and MockEmergencyHandler is removed."""
    main_file = Path("engine/main.py")
    source = main_file.read_text(encoding="utf-8")
    assert "MockEmergencyHandler" not in source, "MockEmergencyHandler must be removed from engine.main"
    assert "from engine.execution.emergency_handler import EmergencyHandler" in source
    assert "EmergencyHandler(bridge=bridge, client=exness)" in source


def test_emergency_killswitch_sqlite_operational_error_still_writes_lockfile(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify sqlite3.OperationalError during equity/DB resolution still writes lockfile."""
    lock_file = tmp_path / "EMERGENCY_KILLSWITCH.lock"
    assert not lock_file.exists()

    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.get_system_state.side_effect = sqlite3.OperationalError("unable to open database file")
    mock_db.set_system_state.side_effect = sqlite3.OperationalError("unable to open database file")

    handler = EmergencyHandler(
        db_manager=mock_db,
        lockfile_path=lock_file,
        peak_equity=1200.0,
    )

    with caplog.at_level("WARNING"):
        ok = handler.execute_emergency_killswitch()

    assert ok is True
    assert lock_file.exists()
    assert handler.is_killed is True

    raw_content = lock_file.read_text(encoding="utf-8")
    assert "1000" not in raw_content, "No fabricated 1000.0 equity allowed"

    payload = json.loads(raw_content)
    assert payload["trigger_reason"] == "MANUAL_TELEGRAM_KILLSWITCH"
    assert payload["peak_equity"] == 1200.0
    assert payload["current_equity"] == 0.0
    assert payload["drawdown_pct"] == 0.0
    assert payload["equity_source"] == "UNAVAILABLE"
    assert any("unable to open database file" in record.message for record in caplog.records)


def test_emergency_killswitch_sqlite_database_error_still_writes_lockfile(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify sqlite3.DatabaseError during equity/DB resolution still writes lockfile."""
    lock_file = tmp_path / "EMERGENCY_KILLSWITCH.lock"
    assert not lock_file.exists()

    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.get_system_state.side_effect = sqlite3.DatabaseError("file is not a database")
    mock_db.set_system_state.side_effect = sqlite3.DatabaseError("file is not a database")

    handler = EmergencyHandler(
        db_manager=mock_db,
        lockfile_path=lock_file,
        peak_equity=1200.0,
    )

    with caplog.at_level("WARNING"):
        ok = handler.execute_emergency_killswitch()

    assert ok is True
    assert lock_file.exists()
    assert handler.is_killed is True

    raw_content = lock_file.read_text(encoding="utf-8")
    assert "1000" not in raw_content, "No fabricated 1000.0 equity allowed"

    payload = json.loads(raw_content)
    assert payload["trigger_reason"] == "MANUAL_TELEGRAM_KILLSWITCH"
    assert payload["peak_equity"] == 1200.0
    assert payload["current_equity"] == 0.0
    assert payload["drawdown_pct"] == 0.0
    assert payload["equity_source"] == "UNAVAILABLE"
    assert any("file is not a database" in record.message for record in caplog.records)


def test_emergency_killswitch_peak_equity_positive_with_unavailable_equity_zero_drawdown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify peak_equity > 0 with unavailable equity produces drawdown_pct=0.0, never 100.0."""
    lock_file = tmp_path / "EMERGENCY_KILLSWITCH.lock"
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.get_system_state.return_value = None

    handler = EmergencyHandler(
        db_manager=mock_db,
        client=None,
        lockfile_path=lock_file,
        peak_equity=1500.0,
    )

    with caplog.at_level("WARNING"):
        ok = handler.execute_emergency_killswitch()

    assert ok is True
    assert lock_file.exists()
    payload = json.loads(lock_file.read_text(encoding="utf-8"))

    assert payload["peak_equity"] == 1500.0
    assert payload["current_equity"] == 0.0
    assert payload["equity_source"] == "UNAVAILABLE"
    assert payload["drawdown_pct"] == 0.0
    assert "100.0" not in json.dumps(payload), "Drawdown 100.0 must never be fabricated for UNAVAILABLE equity"
    assert any("skipping drawdown calculation" in record.message for record in caplog.records)


def test_set_system_state_paused_db_error_does_not_claim_paused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify set_system_state_paused does not set _is_paused=True if DB update fails."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.set_system_state.side_effect = sqlite3.OperationalError("disk I/O error")

    handler = EmergencyHandler(db_manager=mock_db)
    assert handler.is_paused is False

    with caplog.at_level("ERROR"):
        ok = handler.set_system_state_paused()

    assert ok is False
    assert handler.is_paused is False
    assert any("PAUSED state not persisted" in record.message for record in caplog.records)
