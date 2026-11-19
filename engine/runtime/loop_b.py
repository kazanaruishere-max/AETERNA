"""Module: engine.runtime.loop_b
Responsibility: Evaluate closed M15 bars into deterministic virtual signal
observations gated by the Kronos H4 regime, a strict R:R floor, the news state
machine, and a restart-safe bar cursor. No live order is ever sent.
Owner: aeterna-runtime
Tier: A
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Protocol, cast

from engine.analysis_engine.python.interfaces import (
    KronosInferenceEngine,
    StrategyEvaluator,
)
from engine.analysis_engine.python.types import CandleDict, ModelInferenceResult
from engine.ingestion.python.exness_client import ExnessClient
from engine.models import (
    BarCursorRecord,
    BlockedReason,
    BlockedSignalRecord,
    CandleRecord,
    SignalObservationRecord,
    TradeDirection,
)
from engine.shared.db.database import DatabaseManager
from engine.state_machine.state_machine import NewsStateMachine
from instruments.xauusd.strategies.volatility_breakout import SignalType

logger = logging.getLogger("aeterna.runtime.loop_b")

M15_SECONDS = 900
H4_SECONDS = 14_400
FETCH_TIMEOUT_SECONDS = 1.5


class SignalLike(Protocol):
    """Minimal shape of a strategy candidate consumed by Loop B."""

    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float


class AnalysisLoopB:
    """Turns each closed M15 bar into at most one auditable virtual signal."""

    def __init__(
        self,
        exness_client: ExnessClient,
        kronos_engine: KronosInferenceEngine,
        strategy_evaluator: StrategyEvaluator,
        state_machine: NewsStateMachine,
        db_manager: DatabaseManager,
        symbol: str = "XAUUSDm",
        bar_lookback_m15: int = 100,
        bar_lookback_h4: int = 512,
        min_rr_ratio: float = 2.0,
        virtual_lot: float = 0.01,
    ) -> None:
        if bar_lookback_m15 <= 0 or bar_lookback_h4 <= 0:
            raise ValueError("bar lookbacks must be positive")
        if min_rr_ratio <= 0.0:
            raise ValueError(f"min_rr_ratio must be positive, got {min_rr_ratio}")
        if virtual_lot <= 0.0:
            raise ValueError(f"virtual_lot must be positive, got {virtual_lot}")

        self.exness_client = exness_client
        self.kronos_engine = kronos_engine
        self.strategy_evaluator = strategy_evaluator
        self.state_machine = state_machine
        self.db_manager = db_manager
        self.symbol = symbol
        self.bar_lookback_m15 = int(bar_lookback_m15)
        self.bar_lookback_h4 = int(bar_lookback_h4)
        self.min_rr_ratio = float(min_rr_ratio)
        self.virtual_lot = float(virtual_lot)
        self.strategy_id = type(strategy_evaluator).__name__

    async def run_once(self, bar_ts: int) -> SignalObservationRecord | None:
        """Evaluate one closed M15 bar exactly once; None when gated or duplicate.

        bar_ts is the open-time of the M15 bar that has already closed.
        """
        if bar_ts % M15_SECONDS != 0:
            raise ValueError(f"bar_ts must be an M15 floor, got {bar_ts}")
        if self._is_processed(bar_ts):
            logger.debug(
                "bar skipped symbol=%s bar_ts=%d reason=cursor", self.symbol, bar_ts
            )
            return None

        context = await self._load_context(bar_ts)
        if context is None:
            self._advance_cursor(bar_ts)
            return None

        m15_candles, h4_candles = context
        try:
            regime = self.kronos_engine.infer_regime(h4_candles)
            if not self._regime_gate_passes(bar_ts, regime):
                return None
            state_gate = self._state_gate()
            if state_gate is not None:
                self._record_blocked(
                    bar_ts, state_gate, "LONG", 0.0, "signal=not_evaluated"
                )
                return None
            observation = self._evaluate(bar_ts, m15_candles, h4_candles)
        finally:
            self._advance_cursor(bar_ts)

        if observation is None:
            return None
        if not self.db_manager.insert_signal_observation(observation):
            logger.info("observation duplicate signal_id=%s", observation.signal_id)
            return None
        logger.info(
            "observation stored signal_id=%s order_type=%s",
            observation.signal_id,
            observation.order_type,
        )
        return observation

    async def run_forever(
        self, m15_event: asyncio.Event, stop_event: asyncio.Event
    ) -> None:
        """Evaluate every signaled M15 close until stop_event is set.

        Loop A fires m15_event when a tick enters a new M15 bar whose
        open-time is floor(now/900)*900.  The bar that just closed is
        therefore floor(now/900)*900 - 900, i.e. closed_bar_ts.
        """
        logger.info("Loop B started symbol=%s", self.symbol)
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(m15_event.wait(), timeout=1.0)
            except TimeoutError:
                continue
            m15_event.clear()
            triggered_bar_ts = (int(time.time()) // M15_SECONDS) * M15_SECONDS
            closed_bar_ts = triggered_bar_ts - M15_SECONDS
            if self._is_processed(closed_bar_ts):
                logger.info(
                    "bar skipped symbol=%s bar_ts=%d reason=stale",
                    self.symbol,
                    closed_bar_ts,
                )
                continue
            try:
                await self.run_once(closed_bar_ts)
            except Exception:
                logger.exception(
                    "bar evaluation failed symbol=%s bar_ts=%d",
                    self.symbol,
                    closed_bar_ts,
                )
        logger.info("Loop B stopped symbol=%s", self.symbol)

    async def _load_context(
        self, bar_ts: int
    ) -> tuple[list[CandleDict], list[CandleDict]] | None:
        """Fetch M15/H4 candles off-loop; None when MT5 or validation fails."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._fetch_context, bar_ts),
                timeout=FETCH_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "candle fetch timed out symbol=%s bar_ts=%d timeout=%.1fs",
                self.symbol,
                bar_ts,
                FETCH_TIMEOUT_SECONDS,
            )
        except ValueError as exc:
            logger.warning(
                "context rejected symbol=%s bar_ts=%d error=%s",
                self.symbol,
                bar_ts,
                exc,
            )
        except Exception:
            logger.exception(
                "candle fetch failed symbol=%s bar_ts=%d", self.symbol, bar_ts
            )
        return None

    def _fetch_context(self, bar_ts: int) -> tuple[list[CandleDict], list[CandleDict]]:
        """Read both timeframes under the MT5 RLock and exclude forming bars.

        bar_ts is the open-time of the last closed M15 bar.

        M15 cutoff  = bar_ts           (include closed bar, exclude forming)
        H4  cutoff  = last H4 open-time whose bar is fully closed at bar_ts
                    = ((bar_ts + M15_SECONDS) // H4_SECONDS) * H4_SECONDS
                      - H4_SECONDS
        """
        h4_cutoff = ((bar_ts + M15_SECONDS) // H4_SECONDS) * H4_SECONDS - H4_SECONDS

        # Request one extra bar: the exchange always returns the forming bar too.
        with self.exness_client.lock:
            m15_records = self.exness_client.fetch_recent_candles(
                "M15", self.bar_lookback_m15 + 1
            )
            h4_records = self.exness_client.fetch_recent_candles(
                "H4", self.bar_lookback_h4 + 1
            )

        m15_cutoff_str = _iso_utc(bar_ts)
        h4_cutoff_str = _iso_utc(h4_cutoff)

        m15_candles = [
            _to_candle_dict(candle)
            for candle in m15_records
            if candle.timestamp_utc <= m15_cutoff_str
        ][-self.bar_lookback_m15 :]
        h4_candles = [
            _to_candle_dict(candle)
            for candle in h4_records
            if candle.timestamp_utc <= h4_cutoff_str
        ][-self.bar_lookback_h4 :]

        if len(m15_candles) < self.bar_lookback_m15:
            raise ValueError(
                f"insufficient M15 candles: {len(m15_candles)} < {self.bar_lookback_m15}"
            )
        if len(h4_candles) != self.bar_lookback_h4:
            raise ValueError(
                f"H4 window must be exactly {self.bar_lookback_h4}, got {len(h4_candles)}"
            )
        return m15_candles, h4_candles

    def _regime_gate_passes(self, bar_ts: int, regime: ModelInferenceResult) -> bool:
        """Kronos must certify its own context window before any evaluation."""
        if not regime.temporal_assertion_passed:
            logger.warning(
                "regime gate failed symbol=%s bar_ts=%d reason=temporal_assertion",
                self.symbol,
                bar_ts,
            )
            return False
        logger.info(
            "regime gate symbol=%s bar_ts=%d regime=%s confidence=%.3f",
            self.symbol,
            bar_ts,
            regime.regime,
            regime.confidence,
        )
        return True

    def _state_gate(self) -> BlockedReason | None:
        """Map the news state machine to the blocking audit reason, if any."""
        state = self.state_machine.state
        if state == "PAUSED":
            return "state_machine_paused"
        if state == "PRE_NEWS_WATCH":
            return "state_machine_pre_news"
        return None

    def _evaluate(
        self, bar_ts: int, m15_candles: list[CandleDict], h4_candles: list[CandleDict]
    ) -> SignalObservationRecord | None:
        """Keep the first directional candidate that clears the R:R floor."""
        signals = cast(
            list[SignalLike],
            self.strategy_evaluator.evaluate_signals(m15_candles, h4_candles),
        )
        for signal in signals:
            if signal.signal_type not in (SignalType.BUY, SignalType.SELL):
                continue
            if signal.stop_loss <= 0.0 or signal.take_profit <= 0.0:
                continue
            risk = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profit - signal.entry_price)
            rr_ratio = reward / risk if risk > 0.0 else 0.0
            if rr_ratio < self.min_rr_ratio:
                self._record_blocked(
                    bar_ts,
                    # No dedicated schema reason exists for a sub-floor R:R.
                    "stale_signal_expired",
                    _direction(signal.signal_type),
                    signal.entry_price,
                    f"gate=min_rr rr_ratio={rr_ratio:.2f} min_rr={self.min_rr_ratio:.2f}",
                )
                continue
            return self._build_observation(bar_ts, signal)
        return None

    def _build_observation(
        self, bar_ts: int, signal: SignalLike
    ) -> SignalObservationRecord:
        """Freeze a candidate into the immutable virtual journal contract."""
        return SignalObservationRecord(
            signal_id=f"{self.symbol}:{bar_ts}:{self.strategy_id}",
            symbol=self.symbol,
            bar_ts=bar_ts,
            strategy_id=self.strategy_id,
            order_type=signal.signal_type.value,
            state="OPEN",
            entry_px=signal.entry_price,
            sl_px=signal.stop_loss,
            tp_px=signal.take_profit,
            lot_virtual=self.virtual_lot,
        )

    def _record_blocked(
        self,
        bar_ts: int,
        reason: BlockedReason,
        direction: TradeDirection,
        entry_px: float,
        details: str,
    ) -> None:
        """Audit a suppressed bar without touching system state."""
        state = self.db_manager.get_system_state()
        self.db_manager.insert_blocked_signal(
            BlockedSignalRecord(
                timestamp_utc=_iso_utc(bar_ts),
                pair=self.symbol,
                direction=direction,
                strategy_selected=self.strategy_id,
                reason_blocked=reason,
                confidence_at_time=0.0,
                would_be_entry_price=entry_px,
                current_spread=state.current_spread if state is not None else 0.0,
                details=f"bar_ts={bar_ts} {details}",
            )
        )

    def _is_processed(self, bar_ts: int) -> bool:
        """True when this bar (or a newer one) was already consumed."""
        cursor = self.db_manager.get_bar_cursor(self.symbol, "M15")
        return cursor is not None and cursor.last_closed_bar_ts >= bar_ts

    def _advance_cursor(self, bar_ts: int) -> None:
        """Persist the restart-safe cursor after every evaluation attempt."""
        self.db_manager.advance_bar_cursor(
            BarCursorRecord(
                symbol=self.symbol,
                timeframe="M15",
                last_closed_bar_ts=bar_ts,
                updated_at_ms=int(time.time() * 1000),
            )
        )


def _iso_utc(epoch_seconds: int) -> str:
    """Format epoch seconds as the canonical UTC candle timestamp."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_candle_dict(candle: CandleRecord) -> CandleDict:
    """Adapt a stored candle record to the analysis engine contract."""
    return CandleDict(
        timestamp_utc=candle.timestamp_utc,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        tick_volume=candle.tick_volume,
    )


def _direction(signal_type: SignalType) -> TradeDirection:
    """Translate a directional signal into the ledger direction vocabulary."""
    return "LONG" if signal_type is SignalType.BUY else "SHORT"
