"""Unit tests for dual news filter, online EWMA spread filter, and 4-state state machine.

Tests financial and operational invariants REQ-RSK-001 and REQ-RSK-002:
1. Warm-up suppression: t < 30 returns None, t = 30 returns valid float Z-score.
2. Anti div-by-zero epsilon: Identical flat spread produces Z = 0.0 without crash.
3. DST-aware news UTC conversion: EDT (July) vs EST (January).
4. Calendar-based transition: NORMAL -> PRE_NEWS_WATCH -> PAUSED.
5. Volatility spike transition: Z >= 3.0 triggers PAUSED without news.
6. Recovery stability: K=12 reads trigger RECOVERY_CHECK, anomaly Z >= 1.5 resets to PAUSED,
   M=300 seconds stability returns to NORMAL.
7. SQLite system_state singleton persistence synchronization.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from engine.shared.db.database import DatabaseManager
from engine.state_machine.news_filter import (
    NewsCalendarFilter,
    convert_eastern_to_utc,
)
from engine.state_machine.spread_filter import SpreadFilter
from engine.state_machine.state_machine import NewsStateMachine, SpreadProvider

UTC = ZoneInfo("UTC")


def test_spread_filter_warmup_suppresses_z_score() -> None:
    """Readings 1..29 return z_score is None; reading 30 returns valid float."""
    sf = SpreadFilter(alpha=0.08, window_size=60, warmup_reads=30)

    for i in range(1, 30):
        baseline, _, z_score = sf.update(1.5)
        assert z_score is None, f"Read {i} must suppress Z-score during warmup"
        assert not sf.is_warmed_up
        assert sf.read_count == i
        assert baseline > 0.0

    # Reading 30 completes warmup
    baseline, _, z_score = sf.update(1.5)
    assert z_score is not None
    assert isinstance(z_score, float)
    assert sf.is_warmed_up
    assert sf.read_count == 30
    assert not math.isnan(z_score)


def test_spread_filter_anti_div_by_zero_epsilon() -> None:
    """60 identical readings with zero variance yield Z-score 0.0 without zero division."""
    sf = SpreadFilter(alpha=0.08, window_size=60, warmup_reads=30)
    z_score: float | None = None
    for _ in range(60):
        _, _, z_score = sf.update(2.0)

    assert sf.baseline == 2.0
    assert sf.std_dev == 0.0
    assert z_score is not None
    assert z_score == 0.0
    assert not math.isnan(z_score)
    # Micro delta smaller than 1e-6 must also safely evaluate to 0.0
    _, _, z_micro = sf.update(2.0000001)
    assert z_micro == 0.0


def test_dst_aware_news_utc_conversion() -> None:
    """Verify dynamic Eastern Time to UTC conversion for EDT (summer) and EST (winter)."""
    # Summer (EDT, UTC-4): 08:30 EDT == 12:30:00 UTC
    summer_dt = convert_eastern_to_utc("2024-07-15", "08:30:00")
    assert summer_dt.year == 2024
    assert summer_dt.month == 7
    assert summer_dt.day == 15
    assert summer_dt.hour == 12
    assert summer_dt.minute == 30
    assert summer_dt.second == 0
    assert summer_dt.tzinfo == UTC

    # Winter (EST, UTC-5): 08:30 EST == 13:30:00 UTC
    winter_dt = convert_eastern_to_utc("2024-01-15", "08:30:00")
    assert winter_dt.year == 2024
    assert winter_dt.month == 1
    assert winter_dt.day == 15
    assert winter_dt.hour == 13
    assert winter_dt.minute == 30
    assert winter_dt.second == 0
    assert winter_dt.tzinfo == UTC

    # FOMC 14:00 EDT in Summer -> 18:00:00 UTC
    fomc_summer = convert_eastern_to_utc("2024-06-12", "14:00:00")
    assert fomc_summer.hour == 18
    assert fomc_summer.minute == 0


def test_transition_normal_to_pre_news_and_paused() -> None:
    """Verify smooth calendar-based transitions: NORMAL -> PRE_NEWS_WATCH -> PAUSED."""
    news_filter = NewsCalendarFilter()
    t_news = datetime(2024, 7, 15, 12, 30, tzinfo=UTC)
    news_filter.add_event(t_news)

    spread_filter = SpreadFilter()
    for _ in range(35):
        spread_filter.update(1.2)

    sm = NewsStateMachine(spread_filter=spread_filter, news_filter=news_filter)

    # 1. 12:15 UTC (15 mins prior): Outside pre-news window -> NORMAL
    t_15min_prior = t_news - timedelta(minutes=15)
    assert sm.update(t_15min_prior, 1.2) == "NORMAL"

    # 2. 12:20 UTC (10 mins prior): Enters [T_news - 10m, T_news) -> PRE_NEWS_WATCH
    t_10min_prior = t_news - timedelta(minutes=10)
    assert sm.update(t_10min_prior, 1.2) == "PRE_NEWS_WATCH"

    # 3. 12:29 UTC (1 min prior): Inside pre-news window -> PRE_NEWS_WATCH
    t_1min_prior = t_news - timedelta(minutes=1)
    assert sm.update(t_1min_prior, 1.2) == "PRE_NEWS_WATCH"

    # 4. 12:30 UTC: Release time starts blackout [T_news, T_news + 15m] -> PAUSED
    assert sm.update(t_news, 1.2) == "PAUSED"

    # 5. 12:40 UTC: In the middle of blackout -> PAUSED
    t_mid_blackout = t_news + timedelta(minutes=10)
    assert sm.update(t_mid_blackout, 1.2) == "PAUSED"

    # 6. 12:45 UTC: Exactly at end of blackout window (15m) -> PAUSED
    t_end_blackout = t_news + timedelta(minutes=15)
    assert sm.update(t_end_blackout, 1.2) == "PAUSED"


def test_transition_paused_by_spread_spike() -> None:
    """Spike in spread generating Z >= 3.0 forces transition to PAUSED without news."""
    news_filter = NewsCalendarFilter()
    spread_filter = SpreadFilter(alpha=0.08, window_size=60, warmup_reads=30)

    # Warm up with base spread ~1.0 pip and small variance
    for i in range(40):
        val = 1.0 + (0.05 if i % 2 == 0 else -0.05)
        spread_filter.update(val)

    sm = NewsStateMachine(
        spread_filter=spread_filter,
        news_filter=news_filter,
        z_threshold_pause=3.0,
    )

    t0 = datetime(2024, 7, 15, 10, 0, 0, tzinfo=UTC)
    assert sm.update(t0, 1.0) == "NORMAL"

    # Inject large spread spike (e.g. 2.5 pips against 1.0 baseline with ~0.05 std dev => Z ~ 30)
    t1 = t0 + timedelta(seconds=1)
    state = sm.update(t1, 2.5)
    assert sm.z_score is not None
    assert sm.z_score >= 3.0
    assert state == "PAUSED"


def test_recovery_check_k12_and_m300_stability() -> None:
    """Test full recovery lifecycle: K=12 reads trigger RECOVERY_CHECK, anomaly resets, 300s completes."""
    news_filter = NewsCalendarFilter()
    spread_filter = SpreadFilter(alpha=0.08, window_size=60, warmup_reads=30)

    # Warm up with ~1.0 pip spread
    for i in range(50):
        spread_filter.update(1.0 + (0.05 if i % 2 == 0 else -0.05))

    sm = NewsStateMachine(
        spread_filter=spread_filter,
        news_filter=news_filter,
        k_stable_reads=12,
        m_stability_seconds=300,
        z_threshold_pause=3.0,
        z_threshold_resume=1.5,
    )

    t0 = datetime(2024, 7, 15, 10, 0, 0, tzinfo=UTC)
    assert sm.update(t0, 1.0) == "NORMAL"

    # 1. Trigger PAUSED via spread spike
    t_curr = t0 + timedelta(seconds=1)
    state = sm.update(t_curr, 2.5)
    assert state == "PAUSED"

    # 2. Feed K=11 consecutive calm reads (Z < 1.5) -> Still PAUSED
    for k in range(1, 12):
        t_curr += timedelta(seconds=1)
        state = sm.update(t_curr, 1.0)
        assert sm.z_score is not None and sm.z_score < 1.5
        assert state == "PAUSED"
        assert sm.k_counter == k

    # 3. 12th consecutive calm read -> Triggers RECOVERY_CHECK
    t_curr += timedelta(seconds=1)
    t_recovery_1 = t_curr
    state = sm.update(t_recovery_1, 1.0)
    assert state == "RECOVERY_CHECK"
    assert sm.recovery_start_time == t_recovery_1

    # 4. Advance 99 seconds stably in RECOVERY_CHECK
    t_curr = t_recovery_1 + timedelta(seconds=99)
    state = sm.update(t_curr, 1.0)
    assert state == "RECOVERY_CHECK"

    # 5. At second 100, an anomaly (Z >= 1.5) occurs -> Thrown back to PAUSED, timer resets
    t_curr = t_recovery_1 + timedelta(seconds=100)
    state = sm.update(t_curr, 2.5)
    assert sm.z_score is not None and sm.z_score >= 1.5
    assert state == "PAUSED"
    assert sm.recovery_start_time is None
    assert sm.k_counter == 0

    # 6. Re-accumulate K=12 calm reads
    for _ in range(11):
        t_curr += timedelta(seconds=1)
        state = sm.update(t_curr, 1.0)
        assert state == "PAUSED"

    t_curr += timedelta(seconds=1)
    t_recovery_2 = t_curr
    state = sm.update(t_recovery_2, 1.0)
    assert state == "RECOVERY_CHECK"
    assert sm.recovery_start_time == t_recovery_2

    # 7. Advance to 299 seconds -> Still RECOVERY_CHECK
    t_curr = t_recovery_2 + timedelta(seconds=299)
    state = sm.update(t_curr, 1.0)
    assert state == "RECOVERY_CHECK"

    # 8. Reaching 300 full seconds of uninterrupted calm -> Transitions to NORMAL
    t_curr = t_recovery_2 + timedelta(seconds=300)
    state = sm.update(t_curr, 1.0)
    assert state == "NORMAL"
    assert sm.recovery_start_time is None


def test_system_state_sqlite_persistence(tmp_path: Path) -> None:
    """Verify SQLite system_state singleton is synchronously updated on state transitions."""
    db_path = tmp_path / "aeterna_state.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_db()

    news_filter = NewsCalendarFilter()
    spread_filter = SpreadFilter(warmup_reads=5)
    for _ in range(10):
        spread_filter.update(1.2)

    sm = NewsStateMachine(
        spread_filter=spread_filter,
        news_filter=news_filter,
        db_manager=db_mgr,
    )

    t_eval = datetime(2024, 7, 15, 12, 0, tzinfo=UTC)

    # Trigger transition to PAUSED via spike
    sm.update(t_eval, 5.0)

    # Verify SQLite row
    record = db_mgr.get_system_state()
    assert record is not None
    assert record.state == "PAUSED"
    assert record.current_spread == 5.0
    assert record.last_updated_utc == t_eval.isoformat()

    # Also test duck-typed update_system_state callback adapter
    mock_mgr = MagicMock()
    mock_sm = NewsStateMachine(
        spread_filter=SpreadFilter(warmup_reads=5),
        news_filter=news_filter,
        db_manager=mock_mgr,
    )
    for _ in range(10):
        mock_sm.spread_filter.update(1.2)

    mock_sm.update(t_eval, 5.0)
    mock_mgr.update_system_state.assert_called_once()


def test_spread_provider_protocol() -> None:
    """Verify SpreadProvider protocol dispatch via update method."""
    class MockSpreadProvider:
        def get_current_spread_pips(self) -> float:
            return 1.45

    provider: SpreadProvider = MockSpreadProvider()
    news_filter = NewsCalendarFilter()
    spread_filter = SpreadFilter(warmup_reads=5)
    sm = NewsStateMachine(spread_filter=spread_filter, news_filter=news_filter)

    t = datetime(2024, 7, 15, 10, 0, tzinfo=UTC)
    state = sm.update(t, spread_provider=provider)
    assert state in ("NORMAL", "PRE_NEWS_WATCH", "PAUSED", "RECOVERY_CHECK")
    assert sm.current_spread == 1.45
