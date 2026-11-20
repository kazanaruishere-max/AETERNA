"""Runtime tri-loop and virtual tracker orchestration service.

Module: engine.runtime.runtime_service
Responsibility: Orchestrates FastTickLoopA, AnalysisLoopB, VirtualSignalTracker,
                and SignalOnlyDashboard in an isolated zero-risk signal-only lifecycle.
Owner: aeterna-lead
Tier: Tier A
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from engine.analysis_engine.python.types import CandleDict
from engine.runtime.chart_snapshot import render_ohlc_png
from engine.runtime.dashboard import ObservationCard, SignalOnlyDashboard

logger = logging.getLogger("aeterna.runtime.runtime_service")


class RuntimeService:
    """Orchestrates runtime tri-loop, virtual signal tracker, and observation publishing."""

    def __init__(
        self,
        loop_a: Any,
        loop_b: Any,
        virtual_tracker: Any,
        dashboard: SignalOnlyDashboard,
        db_manager: Any,
        symbol: str = "XAUUSDm",
        publish_interval_seconds: float = 5.0,
        chart_candle_provider: Callable[[int], list[CandleDict]] | None = None,
    ) -> None:
        self.loop_a = loop_a
        self.loop_b = loop_b
        self.virtual_tracker = virtual_tracker
        self.dashboard = dashboard
        self.db_manager = db_manager
        self.symbol = symbol
        self.publish_interval_seconds = float(publish_interval_seconds)
        self.chart_candle_provider = chart_candle_provider
        self._published_signal_ids: set[str] = set()

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Run all loops and publisher concurrently under an asyncio.TaskGroup."""
        logger.info("RuntimeService starting for symbol=%s", self.symbol)
        m15_event = getattr(self.loop_a, "m15_event", None)
        if m15_event is None:
            m15_event = asyncio.Event()

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._run_loop_a(stop_event))
                tg.create_task(self._run_loop_b(m15_event, stop_event))
                tg.create_task(self._run_virtual_tracker(stop_event))
                tg.create_task(self._publish_new_observations(stop_event))
        except* Exception as eg:
            logger.error(
                "RuntimeService TaskGroup cancelled due to exception: %s",
                eg.exceptions,
            )
            raise
        finally:
            logger.info("RuntimeService stopped cleanly for symbol=%s", self.symbol)

    async def _run_loop_a(self, stop_event: asyncio.Event) -> None:
        """Run Loop A and handle lifecycle logging."""
        await self.loop_a.run_forever(stop_event)

    async def _run_loop_b(
        self, m15_event: asyncio.Event, stop_event: asyncio.Event
    ) -> None:
        """Run Loop B and handle lifecycle logging."""
        await self.loop_b.run_forever(m15_event, stop_event)

    async def _run_virtual_tracker(self, stop_event: asyncio.Event) -> None:
        """Run Virtual Signal Tracker and handle lifecycle logging."""
        await self.virtual_tracker.run_forever(stop_event)

    async def _publish_new_observations(self, stop_event: asyncio.Event) -> None:
        """Poll database for open observations and publish new ones to admin."""
        logger.info(
            "Observation publisher loop started (interval=%.1fs)",
            self.publish_interval_seconds,
        )
        while not stop_event.is_set():
            try:
                await self._poll_and_publish_once()
            except Exception:
                logger.exception("Error while polling or publishing observations")

            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.publish_interval_seconds
                )
            except TimeoutError:
                continue

    async def _poll_and_publish_once(self) -> None:
        """Fetch open observations and publish un-emitted signals."""
        records = await asyncio.to_thread(
            self.db_manager.get_open_signal_observations, self.symbol
        )
        for record in records:
            if record.signal_id in self._published_signal_ids:
                continue

            card = self._create_card_from_record(record)
            success = self._publish_card_with_optional_chart(card, record.bar_ts)
            if success:
                self._published_signal_ids.add(record.signal_id)

    def _publish_card_with_optional_chart(
        self, card: ObservationCard, bar_ts: int
    ) -> bool:
        """Publish observation card with rendered OHLC chart if available, else text."""
        candles = self._get_candles_for_bar(bar_ts)
        if not candles:
            logger.info("CHART_UNAVAILABLE=FALLBACK_TEXT")
            return self.dashboard.publish(card)

        try:
            png_bytes = render_ohlc_png(
                candles,
                zone_low=card.zone_low,
                zone_high=card.zone_high,
                invalidation_level=card.invalidation_level,
            )
            return self.dashboard.publish_with_chart(card, png_bytes)
        except Exception:
            logger.exception("Chart rendering failed; falling back to text")
            logger.info("CHART_UNAVAILABLE=FALLBACK_TEXT")
            return self.dashboard.publish(card)

    def _get_candles_for_bar(self, bar_ts: int) -> list[CandleDict] | None:
        """Fetch candles from provider; return None on failure or if provider missing."""
        if self.chart_candle_provider is None:
            return None
        try:
            candles = self.chart_candle_provider(bar_ts)
            return candles if candles else None
        except Exception:
            logger.exception("chart_candle_provider failed for bar_ts=%d", bar_ts)
            return None

    def _create_card_from_record(self, record: Any) -> ObservationCard:
        """Map a SignalObservationRecord into an admin ObservationCard."""
        dt = datetime.fromtimestamp(record.bar_ts, tz=UTC)
        timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        regime = "UNKNOWN"
        if hasattr(record, "regime") and record.regime:
            regime = str(record.regime)

        return ObservationCard(
            timestamp_utc=timestamp_str,
            symbol=record.symbol,
            regime_bias=regime,
            zone_low=record.entry_px,
            zone_high=record.entry_px,
            invalidation_level=record.sl_px,
            liquidity_state="NORMAL",
            blackout_window=None,
            sample_count=len(self._published_signal_ids) + 1,
            data_tag="internal_virtual_journal",
        )
