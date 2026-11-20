"""Production emergency execution handler.

Module: engine.execution.emergency_handler
Responsibility: Concrete implementation of ExecutionEmergencyHandler (Tier A).
1. Emergency liquidation of all open positions via ExnessBrokerBridge.
2. Hard emergency killswitch writing data/EMERGENCY_KILLSWITCH.lock.
3. System state transitions (PAUSED / NORMAL) via SQLite WAL database.
Owner: aeterna-execution
Tier: Tier A
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from engine.execution.broker_bridge import ExnessBrokerBridge, OrderDirection
from engine.ingestion.python.exness_client import ExnessClient
from engine.models import SystemStateRecord
from engine.telegram_bot.interfaces import ExecutionEmergencyHandler
from engine.telegram_bot.types import EmergencyCloseResult

if TYPE_CHECKING:
    from engine.shared.db.database import DatabaseManager

logger = logging.getLogger("aeterna.execution.emergency_handler")


class EmergencyHandler(ExecutionEmergencyHandler):
    """Production implementation of ExecutionEmergencyHandler (Tier A).

    Provides thread-safe emergency actions invoked from Telegram bot:
    1. Liquidation of open positions via ExnessBrokerBridge.
    2. Writing physical EMERGENCY_KILLSWITCH.lock file for Go watchdog.
    3. Persisting PAUSED and NORMAL system states in SQLite WAL repository.
    """

    def __init__(
        self,
        bridge: ExnessBrokerBridge | None = None,
        client: ExnessClient | None = None,
        db_manager: DatabaseManager | Any | None = None,
        lockfile_path: str | Path = "data/EMERGENCY_KILLSWITCH.lock",
        db_path: str = "data/trading.db",
        symbol: str = "XAUUSDm",
        peak_equity: float = 0.0,
    ) -> None:
        self.bridge = bridge
        self.client = client if client is not None else (bridge.client if bridge else None)
        if self.bridge is None and self.client is not None:
            self.bridge = ExnessBrokerBridge(self.client)

        self._db_manager = db_manager
        self.lockfile_path = Path(lockfile_path)
        self.db_path = Path(db_path)
        self.symbol = symbol
        self.peak_equity = float(peak_equity)
        self._is_paused = False
        self._is_killed = False
        self._state_lock = threading.Lock()

    @property
    def is_paused(self) -> bool:
        """Whether emergency pause state is currently active."""
        with self._state_lock:
            return self._is_paused

    @property
    def is_killed(self) -> bool:
        """Whether emergency killswitch has been triggered."""
        with self._state_lock:
            return self._is_killed

    def _fetch_open_positions(self, client: ExnessClient) -> list[Any] | None:
        """Fetch active positions from connected MT5 terminal under client lock."""
        if not client.connected or client.mt5 is None:
            logger.error("execute_force_close_all: MT5 terminal is not connected")
            return None

        mt5 = client.mt5
        if not hasattr(mt5, "positions_get"):
            logger.error("execute_force_close_all: MT5 positions_get is not available")
            return None

        positions_raw: Any = None
        query_error: bool = False
        try:
            positions_raw = mt5.positions_get()
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError):
            logger.exception("execute_force_close_all: failed to query positions")
            query_error = True

        if query_error or positions_raw is None:
            err = mt5.last_error() if hasattr(mt5, "last_error") else "unknown"
            logger.error("execute_force_close_all: positions_get returned None: %s", err)
            return None

        return list(positions_raw)

    def _close_single_position(
        self,
        bridge: ExnessBrokerBridge,
        pos: Any,
        max_deviation_pts: int,
    ) -> EmergencyCloseResult:
        """Attempt liquidation of a single MT5 position with explicit slippage tolerance."""
        ticket = int(getattr(pos, "ticket", 0))
        identifier = int(getattr(pos, "identifier", ticket))
        pos_symbol = str(getattr(pos, "symbol", self.symbol))
        volume = float(getattr(pos, "volume", 0.0))
        pos_type = getattr(pos, "type", 0)
        direction: OrderDirection = "BUY" if pos_type == 0 else "SELL"

        try:
            close_res = bridge.close_partial_position(
                ticket=ticket,
                position_identifier=identifier,
                symbol=pos_symbol,
                direction=direction,
                close_lot=volume,
                deviation=max_deviation_pts,
            )
            if close_res.success:
                logger.info(
                    "Force closed position %d: volume=%.2f, price=%s",
                    ticket,
                    volume,
                    close_res.executed_price,
                )
                return EmergencyCloseResult(
                    ticket=ticket,
                    success=True,
                    closed_lot=close_res.closed_lot if close_res.closed_lot > 0 else volume,
                    executed_price=close_res.executed_price,
                    slippage_points=0.0,
                    error_message=None,
                )

            logger.error(
                "Failed to force close position %d: %s (code: %s)",
                ticket,
                close_res.error_message,
                close_res.error_code,
            )
            return EmergencyCloseResult(
                ticket=ticket,
                success=False,
                closed_lot=0.0,
                executed_price=None,
                slippage_points=0.0,
                error_message=close_res.error_message or f"Error {close_res.error_code}",
            )
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.exception("Exception during force close of position %d", ticket)
            return EmergencyCloseResult(
                ticket=ticket,
                success=False,
                closed_lot=0.0,
                executed_price=None,
                slippage_points=0.0,
                error_message=str(exc),
            )

    def execute_force_close_all(self, max_deviation_pts: int = 50) -> list[EmergencyCloseResult]:
        """Liquidate all open positions immediately with specified maximum slippage tolerance.

        Args:
            max_deviation_pts: Maximum allowed slippage points during emergency closure.

        Returns:
            List of EmergencyCloseResult per attempted position closure.
        """
        client = self.client or (self.bridge.client if self.bridge else None)
        if client is None:
            logger.error("execute_force_close_all: no ExnessClient configured")
            return []

        with client.lock:
            positions = self._fetch_open_positions(client)
            if positions is None:
                return []

            if len(positions) == 0:
                logger.info("NO_OPEN_POSITIONS: No active open positions found to close.")
                return []

            bridge = self.bridge or ExnessBrokerBridge(client)
            self.bridge = bridge

            return [
                self._close_single_position(bridge, pos, max_deviation_pts)
                for pos in positions
            ]

    def _write_lockfile(self, payload: dict[str, Any]) -> bool:
        """Write emergency lockfile atomically with temp file and fsync."""
        lock_path = self.lockfile_path
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = lock_path.with_suffix(".tmp")
            content = json.dumps(payload, indent=2).encode("utf-8")
            with open(temp_path, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(lock_path)
            logger.critical("EMERGENCY KILLSWITCH lockfile successfully written to %s", lock_path)
            return True
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError):
            logger.exception("Failed to write EMERGENCY KILLSWITCH lockfile to %s", lock_path)
            return False

    def execute_emergency_killswitch(self) -> bool:
        """Trigger emergency shutdown, writing physical killswitch lockfile and stopping loop."""
        logger.critical("EMERGENCY KILLSWITCH triggered!")
        with self._state_lock:
            peak = self.peak_equity

        # Fail-closed: write physical lockfile before any DB/equity operations
        payload = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "trigger_reason": "MANUAL_TELEGRAM_KILLSWITCH",
            "peak_equity": round(peak, 2),
            "current_equity": 0.0,
            "drawdown_pct": 0.0,
            "equity_source": "UNAVAILABLE",
        }
        if not self._write_lockfile(payload):
            return False

        with self._state_lock:
            self._is_killed = True

        current_equity, equity_source = 0.0, "UNAVAILABLE"
        try:
            current_equity, equity_source = self._resolve_current_equity()
        except (sqlite3.Error, RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.error("Unexpected error resolving equity for killswitch: %s", exc)

        with self._state_lock:
            if current_equity > 0.0:
                self.peak_equity = max(self.peak_equity, current_equity)
            peak = self.peak_equity

        drawdown_pct = 0.0
        if equity_source != "UNAVAILABLE" and peak > 0.0 and current_equity < peak:
            drawdown_pct = round(((peak - current_equity) / peak) * 100.0, 4)
        elif equity_source == "UNAVAILABLE":
            logger.warning("Equity source UNAVAILABLE; skipping drawdown calculation (drawdown_pct=0.0)")

        payload.update({
            "peak_equity": round(peak, 2),
            "current_equity": round(current_equity, 2),
            "drawdown_pct": round(drawdown_pct, 4),
            "equity_source": equity_source,
        })
        self._write_lockfile(payload)

        if not self.set_system_state_paused():
            logger.warning(
                "Killswitch lockfile written, but failed to transition system state to PAUSED in database (partial state)"
            )
        return True

    def set_system_state_paused(self) -> bool:
        """Request immediate transition of system state to PAUSED."""
        db = self._get_db_manager()
        if db is None:
            logger.error("set_system_state_paused: database repository unavailable; PAUSED state not persisted")
            return False

        try:
            existing = db.get_system_state() if hasattr(db, "get_system_state") else None
            now_utc = datetime.now(UTC).isoformat()
            record = SystemStateRecord(
                id=1,
                state="PAUSED",
                current_spread=existing.current_spread if existing else 0.0,
                spread_baseline=existing.spread_baseline if existing else 0.0,
                spread_z_score=existing.spread_z_score if existing else 0.0,
                active_positions_count=existing.active_positions_count if existing else 0,
                equity_usd=existing.equity_usd if existing else 0.0,
                daily_pnl_usd=existing.daily_pnl_usd if existing else 0.0,
                trades_today_count=existing.trades_today_count if existing else 0,
                last_news_event=existing.last_news_event if existing else None,
                last_updated_utc=now_utc,
            )
            db.set_system_state(record)
            with self._state_lock:
                self._is_paused = True
            logger.warning("System state successfully transitioned to PAUSED in repository.")
            return True
        except (sqlite3.Error, RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.error(
                "Failed to transition system state to PAUSED in repository: %s; PAUSED state not persisted",
                exc,
            )
            return False

    def set_system_state_normal(self) -> bool:
        """Request resumption of system state to NORMAL."""
        db = self._get_db_manager()
        if db is None:
            logger.error("set_system_state_normal: database repository unavailable; NORMAL state not persisted")
            return False

        try:
            existing = db.get_system_state() if hasattr(db, "get_system_state") else None
            now_utc = datetime.now(UTC).isoformat()
            record = SystemStateRecord(
                id=1,
                state="NORMAL",
                current_spread=existing.current_spread if existing else 0.0,
                spread_baseline=existing.spread_baseline if existing else 0.0,
                spread_z_score=existing.spread_z_score if existing else 0.0,
                active_positions_count=existing.active_positions_count if existing else 0,
                equity_usd=existing.equity_usd if existing else 0.0,
                daily_pnl_usd=existing.daily_pnl_usd if existing else 0.0,
                trades_today_count=existing.trades_today_count if existing else 0,
                last_news_event=existing.last_news_event if existing else None,
                last_updated_utc=now_utc,
            )
            db.set_system_state(record)
            with self._state_lock:
                self._is_paused = False
            logger.info("System state successfully transitioned to NORMAL in repository.")
            return True
        except (sqlite3.Error, RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.error(
                "Failed to transition system state to NORMAL in repository: %s; NORMAL state not persisted",
                exc,
            )
            return False

    def _resolve_current_equity(self) -> tuple[float, str]:
        """Read current account equity from database state or MT5 connection.

        Returns:
            Tuple of (current_equity, equity_source).
            Never fabricates fallback equity: if unavailable, returns (0.0, "UNAVAILABLE").
        """
        # Try database state
        try:
            db = self._get_db_manager()
            if db is not None:
                state = db.get_system_state() if hasattr(db, "get_system_state") else None
                if state is not None and getattr(state, "equity_usd", None) is not None:
                    eq = float(state.equity_usd)
                    if eq > 0.0:
                        return eq, "DB_SYSTEM_STATE"
        except (sqlite3.Error, RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("Could not read equity from db_manager: %s", exc)

        # Try MT5 account info
        try:
            client = self.client
            if (
                client is not None
                and client.connected
                and client.mt5 is not None
                and hasattr(client.mt5, "account_info")
            ):
                acc = client.mt5.account_info()
                if acc is not None and getattr(acc, "equity", None):
                    eq = float(acc.equity)
                    if eq > 0.0:
                        return eq, "MT5_ACCOUNT_INFO"
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("Could not read MT5 account equity: %s", exc)

        logger.warning("Account equity unavailable from DB and MT5; setting 0.0 UNAVAILABLE")
        return 0.0, "UNAVAILABLE"

    def _get_db_manager(self) -> Any:
        """Lazily initialize DatabaseManager if not explicitly provided."""
        if self._db_manager is None:
            try:
                from engine.shared.db.database import DatabaseManager

                mgr = DatabaseManager(db_path=str(self.db_path))
                mgr.init_db()
                self._db_manager = mgr
            except (sqlite3.Error, RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
                logger.error("Failed to initialize DatabaseManager: %s", exc)
                self._db_manager = "DB_INIT_FAILED"

        if self._db_manager == "DB_INIT_FAILED":
            return None
        return self._db_manager


ProductionEmergencyHandler = EmergencyHandler
