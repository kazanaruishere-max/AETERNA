"""Module: engine.runtime.loop_a
Responsibility: Fast-tick (2s) MT5 bid/ask polling, real-time spread guard,
system_state IPC persistence, and M15 bar-close signalling for Loop B.
Owner: aeterna-runtime
Tier: A
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from engine.ingestion.python.exness_client import ExnessClient
from engine.models import SystemStateRecord
from engine.shared.db.database import DatabaseManager
from engine.state_machine.state_machine import NewsStateMachine

logger = logging.getLogger("aeterna.runtime.loop_a")

M15_SECONDS = 900
PIP_MULTIPLIER = 10.0
TICK_FETCH_TIMEOUT_SECONDS = 1.5


class FastTickLoopA:
    """Polls MT5 tick data every 2 seconds and guards real-time spread risk."""

    def __init__(
        self,
        exness_client: ExnessClient,
        state_machine: NewsStateMachine,
        db_manager: DatabaseManager,
        m15_event: asyncio.Event,
        symbol: str = "XAUUSDm",
        poll_interval_seconds: float = 2.0,
    ) -> None:
        if poll_interval_seconds <= 0.0:
            raise ValueError(
                f"poll_interval_seconds must be positive, got {poll_interval_seconds}"
            )

        self.exness_client = exness_client
        self.state_machine = state_machine
        self.db_manager = db_manager
        self.m15_event = m15_event
        self.symbol = symbol
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.last_bar_m15_ts: int | None = None

    def _fetch_latest_tick(self) -> Any:
        """Read the newest tick under the shared MT5 RLock (runs off-loop)."""
        with self.exness_client.lock:
            return self.exness_client.mt5.symbol_info_tick(self.symbol)

    async def _pull_latest_tick(self) -> Any | None:
        """Fetch a tick in a worker thread; None on timeout or MT5 failure."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._fetch_latest_tick),
                timeout=TICK_FETCH_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "MT5 tick fetch timed out after %.1fs for %s; skipping cycle",
                TICK_FETCH_TIMEOUT_SECONDS,
                self.symbol,
            )
        except Exception:
            logger.exception(
                "MT5 tick fetch failed for %s; skipping cycle", self.symbol
            )
        return None

    async def _poll_and_guard(self) -> None:
        """Run one full tick cycle: guard, persist, and M15 close detection."""
        tick = await self._pull_latest_tick()
        if tick is None:
            return

        tick_utc = datetime.fromtimestamp(int(tick.time), tz=UTC)
        spread_pips = round((float(tick.ask) - float(tick.bid)) * PIP_MULTIPLIER, 2)
        self.state_machine.update(current_utc=tick_utc, current_spread_pips=spread_pips)
        self._persist_system_state(spread_pips, tick_utc)
        self._signal_m15_close(int(tick.time))

    def _persist_system_state(self, spread_pips: float, tick_utc: datetime) -> None:
        """Idempotently upsert the system_state singleton (id=1)."""
        existing = self.db_manager.get_system_state()
        baseline = self.state_machine.baseline
        z_score = self.state_machine.z_score
        self.db_manager.set_system_state(
            SystemStateRecord(
                state=self.state_machine.state,
                current_spread=spread_pips,
                spread_baseline=baseline if baseline is not None else spread_pips,
                spread_z_score=z_score if z_score is not None else 0.0,
                active_positions_count=existing.active_positions_count
                if existing
                else 0,
                equity_usd=existing.equity_usd if existing else 0.0,
                daily_pnl_usd=existing.daily_pnl_usd if existing else 0.0,
                trades_today_count=existing.trades_today_count if existing else 0,
                last_news_event=existing.last_news_event if existing else None,
                last_updated_utc=tick_utc.isoformat(),
                id=1,
            )
        )

    def _signal_m15_close(self, tick_time_seconds: int) -> None:
        """Set m15_event once per new M15 bar so Loop B runs on bar close."""
        bar_m15_ts = (tick_time_seconds // M15_SECONDS) * M15_SECONDS
        if self.last_bar_m15_ts is not None and bar_m15_ts > self.last_bar_m15_ts:
            logger.info("M15 bar closed at %d; waking Loop B", self.last_bar_m15_ts)
            self.m15_event.set()
        self.last_bar_m15_ts = bar_m15_ts

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Poll on a fixed cadence until stop_event is set."""
        logger.info(
            "Loop A started (symbol=%s, interval=%.2fs)",
            self.symbol,
            self.poll_interval_seconds,
        )
        while not stop_event.is_set():
            cycle_started = time.monotonic()
            await self._poll_and_guard()
            remaining = self.poll_interval_seconds - (time.monotonic() - cycle_started)
            if remaining > 0.0:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=remaining)
        logger.info("Loop A stopped (symbol=%s)", self.symbol)
