"""News and volatility 4-state state machine orchestrator.

Implements REQ-RSK-001 & REQ-RSK-002:
State Machine States:
1. NORMAL: Standard algorithmic operation.
2. PRE_NEWS_WATCH: Entered 10 minutes before scheduled high-impact news releases.
3. PAUSED: Trading halted during news blackout [T_news, T_news + 15m] OR spread spike Z >= 3.0.
4. RECOVERY_CHECK: Gated recovery requiring blackout expiration AND K=12 consecutive
   stable reads (Z < 1.5). Reverts to PAUSED if Z >= 1.5 during M=300s window.
   Transitions to NORMAL once 300s of stability is verified.

Synchronizes state transitions with SQLite singleton 'system_state' table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from engine.models import StateMachineState, SystemStateRecord
from engine.state_machine.news_filter import NewsCalendarFilter
from engine.state_machine.spread_filter import SpreadFilter


class SpreadProvider(Protocol):
    """Protocol for dynamic spread measurement providers."""

    def get_current_spread_pips(self) -> float:
        """Return the current market spread in pips."""
        ...


class NewsStateMachine:
    """Orchestrates market state gating between NORMAL, PRE_NEWS_WATCH, PAUSED, and RECOVERY_CHECK."""

    def __init__(
        self,
        spread_filter: SpreadFilter,
        news_filter: NewsCalendarFilter,
        k_stable_reads: int = 12,
        m_stability_seconds: int = 300,
        z_threshold_pause: float = 3.0,
        z_threshold_resume: float = 1.5,
        db_manager: Any | None = None,
    ) -> None:
        if k_stable_reads <= 0:
            raise ValueError(f"k_stable_reads must be positive, got {k_stable_reads}")
        if m_stability_seconds <= 0:
            raise ValueError(f"m_stability_seconds must be positive, got {m_stability_seconds}")
        if z_threshold_pause <= z_threshold_resume:
            raise ValueError(
                f"z_threshold_pause ({z_threshold_pause}) must exceed z_threshold_resume ({z_threshold_resume})"
            )

        self.spread_filter = spread_filter
        self.news_filter = news_filter
        self.k_stable_reads = int(k_stable_reads)
        self.m_stability_seconds = int(m_stability_seconds)
        self.z_threshold_pause = float(z_threshold_pause)
        self.z_threshold_resume = float(z_threshold_resume)
        self.db_manager = db_manager

        self._state: StateMachineState = "NORMAL"
        self._k_counter: int = 0
        self._recovery_start_time: datetime | None = None
        self._current_spread: float = 0.0

    @property
    def state(self) -> StateMachineState:
        """Current operational state."""
        return self._state

    @property
    def k_counter(self) -> int:
        """Count of consecutive calm readings during PAUSED state."""
        return self._k_counter

    @property
    def recovery_start_time(self) -> datetime | None:
        """Timestamp when RECOVERY_CHECK stability monitoring commenced."""
        return self._recovery_start_time

    @property
    def current_spread(self) -> float:
        """Most recent spread reading in pips."""
        return self._current_spread

    @property
    def baseline(self) -> float | None:
        """Current EWMA spread baseline in pips."""
        return self.spread_filter.baseline

    @property
    def z_score(self) -> float | None:
        """Current spread Z-score."""
        return self.spread_filter.z_score

    def update(
        self,
        current_utc: datetime,
        current_spread_pips: float | None = None,
        spread_provider: SpreadProvider | None = None,
    ) -> StateMachineState:
        """Update state machine with timestamp and spread reading.

        Args:
            current_utc: Current evaluation timestamp.
            current_spread_pips: Spread in pips (optional if spread_provider given).
            spread_provider: Provider satisfying SpreadProvider Protocol (optional).

        Returns:
            New StateMachineState.
        """
        if current_spread_pips is None:
            if spread_provider is not None:
                current_spread_pips = spread_provider.get_current_spread_pips()
            else:
                raise ValueError("Must provide either current_spread_pips or spread_provider")

        self._current_spread = float(current_spread_pips)
        baseline, _, z_score = self.spread_filter.update(self._current_spread)

        is_blackout = self.news_filter.is_in_news_blackout(current_utc)
        is_pre_news = self.news_filter.is_in_pre_news_window(current_utc)
        is_spread_spike = z_score is not None and z_score >= self.z_threshold_pause

        old_state = self._state
        new_state = old_state

        # Universal pause condition: news blackout OR spread spike (Z >= 3.0)
        if is_blackout or is_spread_spike:
            new_state = "PAUSED"
            self._k_counter = 0
            self._recovery_start_time = None
        elif old_state == "NORMAL":
            if is_pre_news:
                new_state = "PRE_NEWS_WATCH"
        elif old_state == "PRE_NEWS_WATCH":
            if not is_pre_news:
                new_state = "NORMAL"
        elif old_state == "PAUSED":
            # In PAUSED, if blackout is over and spread is calm (Z < 1.5)
            # Accumulate K consecutive calm reads
            if (not is_blackout) and (z_score is not None) and (z_score < self.z_threshold_resume):
                self._k_counter += 1
                if self._k_counter >= self.k_stable_reads:
                    new_state = "RECOVERY_CHECK"
                    self._recovery_start_time = current_utc
                    self._k_counter = 0
            else:
                self._k_counter = 0
        elif old_state == "RECOVERY_CHECK":
            # Anomaly check: elevated spread (Z >= 1.5) or blackout sends back to PAUSED
            if (z_score is not None and z_score >= self.z_threshold_resume) or is_blackout:
                new_state = "PAUSED"
                self._recovery_start_time = None
                self._k_counter = 0
            else:
                # Check 300-second stability timer
                if self._recovery_start_time is not None:
                    elapsed = (current_utc - self._recovery_start_time).total_seconds()
                    if elapsed >= self.m_stability_seconds:
                        self._recovery_start_time = None
                        self._k_counter = 0
                        if is_pre_news:
                            new_state = "PRE_NEWS_WATCH"
                        else:
                            new_state = "NORMAL"

        self._state = new_state

        if new_state != old_state:
            self._persist_system_state(
                new_state=new_state,
                current_spread=self._current_spread,
                baseline=baseline,
                z_score=z_score,
                current_utc=current_utc,
            )

        return new_state

    def _persist_system_state(
        self,
        new_state: StateMachineState,
        current_spread: float,
        baseline: float,
        z_score: float | None,
        current_utc: datetime,
    ) -> None:
        """Synchronize state transition with SQLite system_state singleton table."""
        if self.db_manager is None:
            return

        # 1. Custom update_system_state method on db_manager (e.g. mock or dedicated adapter)
        if hasattr(self.db_manager, "update_system_state"):
            try:
                self.db_manager.update_system_state(
                    state=new_state,
                    current_spread=current_spread,
                    spread_baseline=baseline,
                    spread_z_score=z_score if z_score is not None else 0.0,
                    last_updated_utc=current_utc.isoformat(),
                )
                return
            except TypeError:
                self.db_manager.update_system_state(state=new_state)
                return

        # 2. Canonical DatabaseManager interface via set_system_state
        if hasattr(self.db_manager, "set_system_state"):
            existing = None
            if hasattr(self.db_manager, "get_system_state"):
                existing = self.db_manager.get_system_state()

            record = SystemStateRecord(
                id=1,
                state=new_state,
                current_spread=current_spread,
                spread_baseline=baseline,
                spread_z_score=z_score if z_score is not None else 0.0,
                active_positions_count=existing.active_positions_count if existing else 0,
                equity_usd=existing.equity_usd if existing else 0.0,
                daily_pnl_usd=existing.daily_pnl_usd if existing else 0.0,
                trades_today_count=existing.trades_today_count if existing else 0,
                last_news_event=existing.last_news_event if existing else None,
                last_updated_utc=current_utc.isoformat(),
            )
            self.db_manager.set_system_state(record)
