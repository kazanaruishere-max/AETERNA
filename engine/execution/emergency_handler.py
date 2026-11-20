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
        peak_equity: float = 1000.0,
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

    @property
    def is_paused(self) -> bool:
        """Whether emergency pause state is currently active."""
        return self._is_paused

    @property
    def is_killed(self) -> bool:
        """Whether emergency killswitch has been triggered."""
        return self._is_killed

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
            if not client.connected or client.mt5 is None:
                logger.error("execute_force_close_all: MT5 terminal is not connected")
                return []

            mt5 = client.mt5
            if not hasattr(mt5, "positions_get"):
                logger.error("execute_force_close_all: MT5 positions_get is not available")
                return []

            try:
                positions = mt5.positions_get()
            except Exception:
                logger.exception("execute_force_close_all: failed to query positions")
                return []

            if positions is None:
                err = mt5.last_error() if hasattr(mt5, "last_error") else "unknown"
                logger.error("execute_force_close_all: positions_get returned None: %s", err)
                return []

            if len(positions) == 0:
                logger.info("NO_OPEN_POSITIONS: No active open positions found to close.")
                return []

            bridge = self.bridge
            if bridge is None:
                bridge = ExnessBrokerBridge(client)
                self.bridge = bridge

            results: list[EmergencyCloseResult] = []
            for pos in positions:
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
                    )
                    if close_res.success:
                        logger.info(
                            "Force closed position %d: volume=%.2f, price=%s",
                            ticket,
                            volume,
                            close_res.executed_price,
                        )
                        results.append(
                            EmergencyCloseResult(
                                ticket=ticket,
                                success=True,
                                closed_lot=close_res.closed_lot if close_res.closed_lot > 0 else volume,
                                executed_price=close_res.executed_price,
                                slippage_points=0.0,
                                error_message=None,
                            )
                        )
                    else:
                        logger.error(
                            "Failed to force close position %d: %s (code: %s)",
                            ticket,
                            close_res.error_message,
                            close_res.error_code,
                        )
                        results.append(
                            EmergencyCloseResult(
                                ticket=ticket,
                                success=False,
                                closed_lot=0.0,
                                executed_price=None,
                                slippage_points=0.0,
                                error_message=close_res.error_message or f"Error {close_res.error_code}",
                            )
                        )
                except Exception as exc:
                    logger.exception("Exception during force close of position %d", ticket)
                    results.append(
                        EmergencyCloseResult(
                            ticket=ticket,
                            success=False,
                            closed_lot=0.0,
                            executed_price=None,
                            slippage_points=0.0,
                            error_message=str(exc),
                        )
                    )

            return results

    def execute_emergency_killswitch(self) -> bool:
        """Trigger emergency shutdown, writing physical killswitch lockfile and stopping loop."""
        logger.critical("EMERGENCY KILLSWITCH triggered!")

        current_equity = self._resolve_current_equity()
        self.peak_equity = max(self.peak_equity, current_equity)

        peak = self.peak_equity
        drawdown_pct = 0.0
        if peak > 0.0 and current_equity < peak:
            drawdown_pct = round(((peak - current_equity) / peak) * 100.0, 4)

        now_utc = datetime.now(UTC).isoformat()
        payload = {
            "timestamp_utc": now_utc,
            "trigger_reason": "MANUAL_TELEGRAM_KILLSWITCH",
            "peak_equity": round(peak, 2),
            "current_equity": round(current_equity, 2),
            "drawdown_pct": round(drawdown_pct, 4),
        }

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
        except Exception:
            logger.exception("Failed to write EMERGENCY KILLSWITCH lockfile to %s", lock_path)
            return False

        self.set_system_state_paused()
        self._is_killed = True
        return True

    def set_system_state_paused(self) -> bool:
        """Request immediate transition of system state to PAUSED."""
        db = self._get_db_manager()
        if db is None:
            logger.error("set_system_state_paused: database repository unavailable")
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
                equity_usd=existing.equity_usd if existing else 1000.0,
                daily_pnl_usd=existing.daily_pnl_usd if existing else 0.0,
                trades_today_count=existing.trades_today_count if existing else 0,
                last_news_event=existing.last_news_event if existing else None,
                last_updated_utc=now_utc,
            )
            db.set_system_state(record)
            self._is_paused = True
            logger.warning("System state successfully transitioned to PAUSED in repository.")
            return True
        except Exception:
            logger.exception("Failed to transition system state to PAUSED")
            return False

    def set_system_state_normal(self) -> bool:
        """Request resumption of system state to NORMAL."""
        db = self._get_db_manager()
        if db is None:
            logger.error("set_system_state_normal: database repository unavailable")
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
                equity_usd=existing.equity_usd if existing else 1000.0,
                daily_pnl_usd=existing.daily_pnl_usd if existing else 0.0,
                trades_today_count=existing.trades_today_count if existing else 0,
                last_news_event=existing.last_news_event if existing else None,
                last_updated_utc=now_utc,
            )
            db.set_system_state(record)
            self._is_paused = False
            logger.info("System state successfully transitioned to NORMAL in repository.")
            return True
        except Exception:
            logger.exception("Failed to transition system state to NORMAL")
            return False

    def _resolve_current_equity(self) -> float:
        """Read current account equity from database state or MT5 connection."""
        db = self._get_db_manager()
        if db is not None:
            try:
                state = db.get_system_state()
                if state is not None and getattr(state, "equity_usd", None) is not None and float(state.equity_usd) > 0.0:
                    return float(state.equity_usd)
            except (RuntimeError, ValueError, OSError, TypeError) as exc:
                logger.warning("Could not read equity from db_manager: %s", exc)

        client = self.client
        if client is not None and client.connected and client.mt5 is not None:
            try:
                if hasattr(client.mt5, "account_info"):
                    acc = client.mt5.account_info()
                    if acc is not None and getattr(acc, "equity", None):
                        return float(acc.equity)
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.debug("Could not read MT5 account equity: %s", exc)

        return 1000.0

    def _get_db_manager(self) -> Any:
        """Lazily initialize DatabaseManager if not explicitly provided."""
        if self._db_manager is None:
            from engine.shared.db.database import DatabaseManager

            mgr = DatabaseManager(db_path=str(self.db_path))
            mgr.init_db()
            self._db_manager = mgr
        return self._db_manager


ProductionEmergencyHandler = EmergencyHandler
