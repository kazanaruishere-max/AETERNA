"""Module: engine.runtime.virtual_tracker
Responsibility: Mark virtual signal observations to market and resolve the
five-layer exit policy deterministically; never sends a broker order.
Owner: aeterna-backtest
Tier: A
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Final

from engine.ingestion.python.exness_client import ExnessClient
from engine.models import SignalObservationRecord
from engine.risk_gate.liquidity import RolloverFilter
from engine.shared.db.database import DatabaseManager

logger = logging.getLogger("aeterna.runtime.virtual_tracker")

MIN_LOT_VIRTUAL, SL_EXIT_NET_R, PARTIAL_NET_R = 0.01, -1.0, 1.0
BE_ARMED_NET_R, BE_FLOOR_R, MIN_RR_RATIO = 1.5, 0.10, 2.0
M15_SECONDS, M15_BARS_TIME_INVALIDATION = 900, 8
OPPOSITE_REGIME: Final[dict[str, str]] = {
    "BUY": "TRENDING_BEARISH",
    "SELL": "TRENDING_BULLISH",
}

ExitPlan = tuple[str, float, str | None]


class VirtualSignalTracker:
    """Prices open virtual observations from live bid/ask; no order is sent.

    Realized R is the net R at the closing tick (spread already deducted); only
    BE_ARMED is floored per ADR-017. A min-lot signal cannot be partially
    closed, so its marker persists as PARTIAL_SKIPPED_MIN_LOT before RUNNING.
    """

    def __init__(
        self,
        exness_client: ExnessClient,
        db_manager: DatabaseManager,
        regime_provider: Callable[[], str],
        symbol: str = "XAUUSDm",
        poll_interval_seconds: float = 2.0,
        tick_timeout_seconds: float = 1.5,
        max_time_invalidation_seconds: int = M15_BARS_TIME_INVALIDATION * M15_SECONDS,
    ) -> None:
        if poll_interval_seconds <= 0.0 or tick_timeout_seconds <= 0.0:
            raise ValueError("poll interval and tick timeout must be positive")
        if max_time_invalidation_seconds <= 0:
            raise ValueError("max_time_invalidation_seconds must be positive")
        self.exness_client = exness_client
        self.db_manager = db_manager
        self.regime_provider = regime_provider
        self.symbol = symbol
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.tick_timeout_seconds = float(tick_timeout_seconds)
        self.max_time_invalidation_seconds = int(max_time_invalidation_seconds)

    def mark_to_market(self, signal: SignalObservationRecord, tick: Any) -> bool:
        """Re-price one observation; True only when the row truly changed."""
        risk_distance = abs(signal.entry_px - signal.sl_px)
        if risk_distance <= 0.0:
            logger.error("zero risk distance signal_id=%s", signal.signal_id)
            return False
        if signal.order_type not in OPPOSITE_REGIME:
            logger.error("unknown order_type signal_id=%s", signal.signal_id)
            return False

        net_r = self._net_r(signal, tick, risk_distance)
        now_utc = datetime.fromtimestamp(int(tick.time), tz=UTC)
        plan = self._resolve_exit(signal, net_r, now_utc, risk_distance)
        if plan is None or plan == (
            signal.state,
            signal.r_realized_net,
            signal.exit_reason,
        ):
            return False

        state, r_realized_net, exit_reason = plan
        changed = self.db_manager.update_signal_observation(
            signal.signal_id, state, r_realized_net, exit_reason
        )
        log = logger.info if exit_reason is not None else logger.debug
        log(
            "marked signal_id=%s net_r=%.3f state=%s exit_reason=%s",
            signal.signal_id,
            net_r,
            state,
            exit_reason,
        )
        return changed

    @staticmethod
    def _net_r(
        signal: SignalObservationRecord, tick: Any, risk_distance: float
    ) -> float:
        """Conservative net R: adverse quote minus the live bid/ask spread."""
        bid, ask = float(tick.bid), float(tick.ask)
        if signal.order_type == "BUY":
            gross_r = (bid - signal.entry_px) / risk_distance
        else:
            gross_r = (signal.entry_px - ask) / risk_distance
        return gross_r - max(0.0, ask - bid) / risk_distance

    def _resolve_exit(
        self,
        signal: SignalObservationRecord,
        net_r: float,
        now_utc: datetime,
        risk_distance: float,
    ) -> ExitPlan | None:
        """Map one mark-to-market into at most one exit-layer transition."""
        if net_r <= SL_EXIT_NET_R:
            return ("CLOSED_SL", net_r, "sl_hit")
        if (
            int(now_utc.timestamp()) - signal.bar_ts
            >= self.max_time_invalidation_seconds
        ):
            return ("CLOSED_TIME", net_r, "time_invalidation")
        if RolloverFilter.is_in_rollover_buffer(now_utc):
            return ("CLOSED_ROLLOVER", net_r, "pre_rollover_force")
        if self.regime_provider() == OPPOSITE_REGIME[signal.order_type]:
            return ("CLOSED_REGIME", net_r, "regime_invalidation")

        rr_actual = abs(signal.tp_px - signal.entry_px) / risk_distance
        if rr_actual >= MIN_RR_RATIO and net_r >= rr_actual:
            return ("CLOSED_TP", net_r, "tp_hit")
        if signal.state == "BE_ARMED":
            if net_r <= BE_FLOOR_R:
                return ("CLOSED_TRAILING", BE_FLOOR_R, "trailing_hit")
            return ("BE_ARMED", max(BE_FLOOR_R, signal.r_realized_net), None)
        if net_r >= BE_ARMED_NET_R:
            return ("BE_ARMED", max(BE_FLOOR_R, signal.r_realized_net), None)
        if net_r >= PARTIAL_NET_R and signal.lot_virtual <= MIN_LOT_VIRTUAL:
            if signal.state == "PARTIAL_SKIPPED_MIN_LOT":
                return ("RUNNING", signal.r_realized_net, None)
            if signal.state == "OPEN":
                return ("PARTIAL_SKIPPED_MIN_LOT", signal.r_realized_net, None)
        return None

    def _fetch_latest_tick(self) -> Any:
        """Read the newest tick under the shared MT5 RLock (runs off-loop)."""
        with self.exness_client.lock:
            return self.exness_client.mt5.symbol_info_tick(self.symbol)

    async def _pull_latest_tick(self) -> Any | None:
        """Fetch a tick in a worker thread; None on timeout or MT5 failure."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._fetch_latest_tick),
                timeout=self.tick_timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "tick timeout after %.2fs symbol=%s; state untouched",
                self.tick_timeout_seconds,
                self.symbol,
            )
        except Exception:
            logger.exception(
                "tick fetch failed symbol=%s; state untouched", self.symbol
            )
        return None

    async def _run_cycle(self) -> None:
        """One cycle; a missing tick never mutates state, rows fail isolated."""
        tick = await self._pull_latest_tick()
        if tick is None:
            return
        for signal in self.db_manager.get_open_signal_observations(self.symbol):
            try:
                self.mark_to_market(signal, tick)
            except Exception:
                logger.exception("mark failed signal_id=%s", signal.signal_id)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Mark to market on a fixed cadence until stop_event is set."""
        logger.info("tracker started symbol=%s", self.symbol)
        while not stop_event.is_set():
            cycle_started = time.monotonic()
            await self._run_cycle()
            remaining = self.poll_interval_seconds - (time.monotonic() - cycle_started)
            if remaining > 0.0:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=remaining)
        logger.info("tracker stopped symbol=%s", self.symbol)
