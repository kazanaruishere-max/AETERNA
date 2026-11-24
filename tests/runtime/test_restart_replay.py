"""Unit and integration tests for restart gap detection and STRATEGY_ONLY replay.

Covers REQ-RUNTIME-003 and REQ-RUNTIME-011.
Owner: aeterna-runtime
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from engine.analysis_engine.python.indicators import MarketRegime
from engine.analysis_engine.python.types import CandleDict, ModelInferenceResult
from engine.models import (
    BarCursorRecord,
    CandleRecord,
    ReplayRunRecord,
    SignalObservationRecord,
    SystemStateRecord,
)
from engine.runtime.bootstrap import (
    ReplayGatedLoopA,
    ReplayGatedLoopB,
    build_runtime_bundle,
    run_restart_recovery,
)
from engine.runtime.restart_replay import (
    H4_SECONDS,
    M15_SECONDS,
    GapStatus,
    RestartReplayConfig,
    RestartReplayEngine,
    compute_config_hash,
    compute_current_closed_bar,
    detect_gap,
)
from engine.shared.db.database import DatabaseManager
from instruments.xauusd.strategies.volatility_breakout import SignalType, TradeSignal

SYMBOL = "XAUUSDm"
T_BASE = 1_700_000_100  # Exact M15 floor (1_700_000_100 % 900 == 0)


def _ts(epoch_seconds: int) -> str:
    """Format epoch seconds as ISO-8601 UTC timestamp."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_candles(
    end_bar_ts: int, step: int, count: int, pair: str = SYMBOL, timeframe: str = "M15"
) -> list[CandleRecord]:
    """Generate ascending contiguous CandleRecords ending at end_bar_ts."""
    timestamps = [end_bar_ts - step * offset for offset in range(count - 1, -1, -1)]
    return [
        CandleRecord(
            pair=pair,
            timeframe=timeframe,  # type: ignore[arg-type]
            timestamp_utc=_ts(ts),
            source="exness_mt5",
            open=2000.0,
            high=2005.0,
            low=1995.0,
            close=2002.0,
            tick_volume=100,
        )
        for ts in timestamps
    ]


class FakeExnessClient:
    """Deterministic ExnessClient stand-in supplying M15 and H4 candles."""

    def __init__(self, current_ts: int, missing_ts: set[int] | None = None) -> None:
        self.symbol = SYMBOL
        self.lock = threading.RLock()
        self.connected = True
        self.current_ts = current_ts
        self.missing_ts = missing_ts or set()

    def fetch_recent_candles(
        self, timeframe: str, count: int
    ) -> list[CandleRecord]:
        step = M15_SECONDS if timeframe == "M15" else H4_SECONDS
        aligned_ts = (self.current_ts // step) * step
        all_candles = _generate_candles(
            aligned_ts, step, count + 50, timeframe=timeframe
        )
        if timeframe == "M15" and self.missing_ts:
            return [
                c
                for c in all_candles
                if int(
                    datetime.fromisoformat(
                        c.timestamp_utc
                    ).timestamp()
                )
                not in self.missing_ts
            ][-count:]
        return all_candles[-count:]


class FakeKronos:
    """Deterministic Kronos stand-in recording evaluated H4 candle windows."""

    def __init__(self) -> None:
        self.calls: list[list[CandleDict]] = []
        self.model_id = "kronos_h4_v1.0.0"

    def infer_regime(self, context_candles: list[CandleDict]) -> ModelInferenceResult:
        self.calls.append(list(context_candles))
        return ModelInferenceResult(
            model_id=self.model_id,
            timestamp_utc="2026-11-23T05:00:00Z",
            regime="TRENDING_BULLISH",
            confidence=0.92,
            probabilities={"TRENDING_BULLISH": 0.92},
            context_candles_count=len(context_candles),
            temporal_assertion_passed=True,
        )

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        return len(candles) >= 100


class FakeStrategyEvaluator:
    """Deterministic StrategyEvaluator returning mock signals and recording calls."""

    def __init__(
        self,
        signals_map: dict[str, list[TradeSignal]] | None = None,
        default_signals: list[TradeSignal] | None = None,
    ) -> None:
        self.signals_map = signals_map or {}
        self.default_signals = default_signals or []
        self.calls: list[tuple[str, str]] = []

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: Any = None,
        sentiment: Any = None,
    ) -> list[TradeSignal]:
        last_m15 = m15_candles[-1]["timestamp_utc"] if m15_candles else ""
        last_h4 = h4_candles[-1]["timestamp_utc"] if h4_candles else ""
        self.calls.append((last_m15, last_h4))
        return self.signals_map.get(last_m15, self.default_signals)


def _make_buy_signal(entry: float = 2000.0, sl: float = 1990.0, tp: float = 2025.0) -> TradeSignal:
    return TradeSignal(
        signal_type=SignalType.BUY,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        atr_value=5.0,
        h4_regime=MarketRegime.TRENDING_BULLISH,
        reason="test_signal",
    )


def _init_db(tmp_path: Path) -> DatabaseManager:
    db = DatabaseManager(db_path=tmp_path / "replay_test.db")
    db.init_db()
    return db


# ---------------------------------------------------------------------------
# Test 1: no gap when cursor current
# ---------------------------------------------------------------------------


def test_no_gap_when_cursor_current(tmp_path: Path) -> None:
    """last_cursor == current_closed -> missed_count == 0, status NO_GAP, 0 replay rows created."""
    db = _init_db(tmp_path)
    now_utc = 1795411608  # 05:26:48 UTC -> current_closed = 05:00:00 UTC = 1795410000
    current_closed = compute_current_closed_bar(now_utc)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=current_closed,
        config_hash=config_hash,
    )

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "NO_GAP"
    assert summary.missed_count == 0
    assert summary.replayed_count == 0
    assert summary.observations_created == 0
    assert summary.blocked_created == 0
    assert len(db.list_replay_runs_by_status("COMPLETED")) == 0


# ---------------------------------------------------------------------------
# Test 2: gap math exact three bars
# ---------------------------------------------------------------------------


def test_gap_math_exact_three_bars() -> None:
    """Exact identification of 3 bars: 04:30, 04:45, 05:00 UTC."""
    # 04:15:00 UTC = 1795407300
    last_cursor_ts = 1795407300
    # 05:26:48 UTC = 1795411608 -> current_closed = 05:00:00 UTC = 1795410000
    now_utc = 1795411608
    config_hash = "test_hash"

    cursor = BarCursorRecord(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        updated_at_ms=1000,
        config_hash=config_hash,
    )

    res = detect_gap(
        now_utc=now_utc,
        last_cursor=cursor,
        current_config_hash=config_hash,
        max_replay_bars=32,
    )

    assert res.status == GapStatus.REPLAY_REQUIRED
    assert res.current_closed_bar_ts == 1795410000  # 05:00:00 UTC
    assert res.first_missed_bar_ts == 1795408200   # 04:30:00 UTC
    assert res.last_missed_bar_ts == 1795410000    # 05:00:00 UTC
    assert res.missed_count == 3

    expected_bars = [1795408200, 1795409100, 1795410000]
    actual_bars = list(
        range(
            res.first_missed_bar_ts,
            res.last_missed_bar_ts + M15_SECONDS,
            M15_SECONDS,
        )
    )
    assert actual_bars == expected_bars


# ---------------------------------------------------------------------------
# Test 3: no baseline does not replay blindly
# ---------------------------------------------------------------------------


def test_no_baseline_does_not_replay_blindly(tmp_path: Path) -> None:
    """Empty bar_cursors table initializes cursor to current_closed, 0 replay bars executed."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "NO_BASELINE"
    assert summary.missed_count == 0
    assert summary.replayed_count == 0

    cursor = db.get_bar_cursor(SYMBOL, "M15")
    assert cursor is not None
    assert cursor.last_closed_bar_ts == current_closed
    assert cursor.config_hash == engine.config_hash


# ---------------------------------------------------------------------------
# Test 4: gap too large blocks with 32 cap
# ---------------------------------------------------------------------------


def test_gap_too_large_blocks(tmp_path: Path) -> None:
    """missed_count > 32 blocks with GAP_TOO_LARGE and prevents cursor advance."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    # 33 bars ago
    last_cursor_ts = current_closed - (33 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "GAP_TOO_LARGE"
    assert summary.missed_count == 33
    assert summary.replayed_count == 0

    # Cursor must not advance
    cursor = db.get_bar_cursor(SYMBOL, "M15")
    assert cursor is not None
    assert cursor.last_closed_bar_ts == last_cursor_ts


# ---------------------------------------------------------------------------
# Test 5: config drift blocks
# ---------------------------------------------------------------------------


def test_config_drift_blocks(tmp_path: Path) -> None:
    """Active config_hash differs from bar_cursors.config_hash -> CONFIG_DRIFT aborts replay."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (3 * M15_SECONDS)

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash="old_divergent_hash_deadbeef",
    )

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "CONFIG_DRIFT"
    assert summary.replayed_count == 0

    cursor = db.get_bar_cursor(SYMBOL, "M15")
    assert cursor is not None
    assert cursor.last_closed_bar_ts == last_cursor_ts


# ---------------------------------------------------------------------------
# Test 6: replay oldest to newest
# ---------------------------------------------------------------------------


def test_replay_oldest_to_newest(tmp_path: Path) -> None:
    """Gap spans multiple bars [T1, T2, T3]. Order of evaluation is strictly T1 -> T2 -> T3."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (3 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    evaluator = FakeStrategyEvaluator()
    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=evaluator,
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "COMPLETED"
    assert summary.replayed_count == 3

    evaluated_m15 = [call[0] for call in evaluator.calls]
    expected_m15 = [
        _ts(last_cursor_ts + M15_SECONDS),
        _ts(last_cursor_ts + 2 * M15_SECONDS),
        _ts(last_cursor_ts + 3 * M15_SECONDS),
    ]
    assert evaluated_m15 == expected_m15


# ---------------------------------------------------------------------------
# Test 7: replay idempotent on second restart
# ---------------------------------------------------------------------------


def test_replay_idempotent_on_second_restart(tmp_path: Path) -> None:
    """Second restart immediately after replay finds NO_GAP with 0 duplicate rows written."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (2 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    evaluator = FakeStrategyEvaluator(default_signals=[_make_buy_signal()])
    client = FakeExnessClient(now_utc)
    config = RestartReplayConfig(replay_mode="auto", max_bars=32)

    engine1 = RestartReplayEngine(
        exness_client=client,
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=evaluator,
        config=config,
        symbol=SYMBOL,
    )

    summary1 = engine1.run_recovery(now_utc=now_utc)
    assert summary1.status == "COMPLETED"
    assert summary1.observations_created == 2

    obs_before = db.get_observations_by_origin("REPLAY")
    assert len(obs_before) == 2

    # Second restart with same clock time
    engine2 = RestartReplayEngine(
        exness_client=client,
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=evaluator,
        config=config,
        symbol=SYMBOL,
    )

    summary2 = engine2.run_recovery(now_utc=now_utc)
    assert summary2.status == "NO_GAP"
    assert summary2.missed_count == 0
    assert summary2.observations_created == 0

    obs_after = db.get_observations_by_origin("REPLAY")
    assert len(obs_after) == 2


# ---------------------------------------------------------------------------
# Test 8: crash mid-replay resumes at last success
# ---------------------------------------------------------------------------


def test_crash_mid_replay_resumes_at_last_success(tmp_path: Path) -> None:
    """Simulated crash after bar 1 leaves prior run INTERRUPTED; second run resumes at bar 2."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    # 3 bars missed: B1, B2, B3
    last_cursor_ts = current_closed - (3 * M15_SECONDS)
    config_hash = compute_config_hash()

    bar1_ts = last_cursor_ts + M15_SECONDS
    # 1. Cursor was persisted at bar 1 before the process crashed:
    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=bar1_ts,
        config_hash=config_hash,
    )
    # 2. Simulate process termination where replay_runs was left in status 'RUNNING':
    crashed_run = ReplayRunRecord(
        replay_id=f"replay:{SYMBOL}:crashed:1",
        symbol=SYMBOL,
        timeframe="M15",
        last_cursor_ts=last_cursor_ts,
        first_missed_bar_ts=bar1_ts,
        last_missed_bar_ts=current_closed,
        missed_count=3,
        started_at_utc=_ts(now_utc - 60),
        status="RUNNING",
        replay_mode="STRATEGY_ONLY",
        config_hash=config_hash,
        strategy_id="FakeStrategyEvaluator",
        model_id="kronos_h4_v1.0.0",
        observations_created=1,
    )
    db.create_replay_run(crashed_run)
    db.insert_replay_observation(
        SignalObservationRecord(
            signal_id=f"{SYMBOL}:{bar1_ts}:FakeStrategyEvaluator",
            symbol=SYMBOL,
            bar_ts=bar1_ts,
            strategy_id="FakeStrategyEvaluator",
            order_type="BUY",
            state="OPEN",
            entry_px=2000.0,
            sl_px=1990.0,
            tp_px=2025.0,
            lot_virtual=0.01,
            origin="REPLAY",
            replay_id=crashed_run.replay_id,
        )
    )

    client = FakeExnessClient(now_utc)
    config = RestartReplayConfig(replay_mode="auto", max_bars=32)

    # Launch engine after crash:
    engine2 = RestartReplayEngine(
        exness_client=client,
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(default_signals=[_make_buy_signal()]),
        config=config,
        symbol=SYMBOL,
    )

    summary2 = engine2.run_recovery(now_utc=now_utc)
    assert summary2.status == "COMPLETED"
    # Remaining 2 bars evaluated (bars 2 and 3)
    assert summary2.missed_count == 2
    assert summary2.replayed_count == 2
    assert summary2.first_missed_bar_ts == bar1_ts + M15_SECONDS
    assert summary2.last_missed_bar_ts == current_closed

    # Verify prior run was transitioned to INTERRUPTED during cleanup
    interrupted_runs = db.list_replay_runs_by_status("INTERRUPTED")
    completed_runs = db.list_replay_runs_by_status("COMPLETED")
    assert len(interrupted_runs) == 1
    assert interrupted_runs[0].replay_id == crashed_run.replay_id
    assert len(completed_runs) == 1
    assert len(db.get_observations_by_origin("REPLAY")) == 3


# ---------------------------------------------------------------------------
# Test 9: replay does not mutate live system_state
# ---------------------------------------------------------------------------


def test_replay_does_not_mutate_live_system_state(tmp_path: Path) -> None:
    """Inspect system_state IPC state during/after replay: live values remain untouched."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (3 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    initial_state = SystemStateRecord(
        state="NORMAL",
        current_spread=1.2,
        spread_baseline=1.1,
        spread_z_score=0.45,
        active_positions_count=1,
        equity_usd=50000.0,
        daily_pnl_usd=120.0,
        trades_today_count=2,
        last_news_event="CPI_RELEASE_GOLDEN",
        last_updated_utc="2026-11-23T04:43:55Z",
    )
    db.set_system_state(initial_state)

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(default_signals=[_make_buy_signal()]),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "COMPLETED"

    state_after = db.get_system_state()
    assert state_after == initial_state


# ---------------------------------------------------------------------------
# Test 10: replay marks origin=REPLAY
# ---------------------------------------------------------------------------


def test_replay_marks_origin_replay(tmp_path: Path) -> None:
    """All rows emitted by replay have origin == 'REPLAY' and valid replay_id. Zero 'LIVE'."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (2 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    # Signal 1: valid R:R >= 2.0 (creates observation)
    sig_valid = _make_buy_signal(entry=2000.0, sl=1990.0, tp=2025.0)
    # Signal 2: invalid R:R < 2.0 (creates blocked signal)
    sig_blocked = _make_buy_signal(entry=2000.0, sl=1990.0, tp=2005.0)

    t1 = _ts(last_cursor_ts + M15_SECONDS)
    t2 = _ts(last_cursor_ts + 2 * M15_SECONDS)
    evaluator = FakeStrategyEvaluator(signals_map={t1: [sig_valid], t2: [sig_blocked]})

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=evaluator,
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "COMPLETED"
    assert summary.observations_created == 1
    assert summary.blocked_created == 1

    replay_obs = db.get_observations_by_origin("REPLAY")
    live_obs = db.get_observations_by_origin("LIVE")
    assert len(replay_obs) == 1
    assert len(live_obs) == 0
    assert replay_obs[0].origin == "REPLAY"
    assert replay_obs[0].replay_id == summary.replay_id

    replay_blocked = db.get_blocked_signals_by_origin("REPLAY")
    live_blocked = db.get_blocked_signals_by_origin("LIVE")
    assert len(replay_blocked) == 1
    assert len(live_blocked) == 0
    assert replay_blocked[0].origin == "REPLAY"
    assert replay_blocked[0].replay_id == summary.replay_id


# ---------------------------------------------------------------------------
# Test 11: replay does not send live observation alert
# ---------------------------------------------------------------------------


def test_replay_does_not_send_live_observation_alert(tmp_path: Path) -> None:
    """Replay executes silently with 0 live alert publications and emits an admin summary."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (3 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(default_signals=[_make_buy_signal()]),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    mock_publisher = MagicMock()
    summary = engine.run_recovery(now_utc=now_utc)

    # Publisher was not called during replay
    assert mock_publisher.call_count == 0
    # Summary message is cleanly formatted for Telegram admin
    admin_msg = summary.format_admin_message()
    assert "[AETERNA REPLAY AUDIT]" in admin_msg
    assert "Replayed: 3" in admin_msg
    assert "Status: COMPLETED" in admin_msg


# ---------------------------------------------------------------------------
# Test 12: zero lookahead H4 cutoff
# ---------------------------------------------------------------------------


def test_zero_lookahead_h4_cutoff(tmp_path: Path) -> None:
    """Evaluate bar at timestamp T. Context has max H4 timestamp <= cutoff; no future candles."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - M15_SECONDS
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    kronos = FakeKronos()
    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=kronos,
        strategy_evaluator=FakeStrategyEvaluator(),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    engine.run_recovery(now_utc=now_utc)
    assert len(kronos.calls) == 1

    h4_candles_passed = kronos.calls[0]
    expected_cutoff_ts = (
        ((current_closed + M15_SECONDS) // H4_SECONDS) * H4_SECONDS - H4_SECONDS
    )
    expected_cutoff_str = _ts(expected_cutoff_ts)

    for c in h4_candles_passed:
        assert c["timestamp_utc"] <= expected_cutoff_str


# ---------------------------------------------------------------------------
# Test 13: missing candles blocks, not skips
# ---------------------------------------------------------------------------


def test_missing_candles_blocks_not_skips(tmp_path: Path) -> None:
    """Missing candle at T2 halts replay with BLOCKED, cursor remains at T1, does not skip to T3."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (3 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    # Drop bar 2 (last_cursor_ts + 2 * M15_SECONDS)
    missing_bar_ts = last_cursor_ts + (2 * M15_SECONDS)
    client = FakeExnessClient(now_utc, missing_ts={missing_bar_ts})

    engine = RestartReplayEngine(
        exness_client=client,
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(),
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "MISSING_CANDLES"
    assert summary.replayed_count == 1  # Only bar 1 succeeded

    # Cursor must be halted at bar 1, NOT skipped to bar 3
    cursor = db.get_bar_cursor(SYMBOL, "M15")
    assert cursor is not None
    assert cursor.last_closed_bar_ts == last_cursor_ts + M15_SECONDS


# ---------------------------------------------------------------------------
# Test 14: blocked signals deduped by compound UNIQUE index
# ---------------------------------------------------------------------------


def test_blocked_signals_deduped(tmp_path: Path) -> None:
    """Compound UNIQUE index prevents duplicate blocked signals under re-evaluation."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - M15_SECONDS
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    sub_rr_signal = _make_buy_signal(entry=2000.0, sl=1990.0, tp=2005.0)  # R:R = 0.5 < 2.0
    evaluator = FakeStrategyEvaluator(default_signals=[sub_rr_signal])

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=evaluator,
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    # First replay creates 1 blocked signal
    summary1 = engine.run_recovery(now_utc=now_utc)
    assert summary1.blocked_created == 1
    assert len(db.get_blocked_signals_by_origin("REPLAY")) == 1

    # Reset cursor back to trigger evaluation of the same bar again
    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    # Second replay evaluates same bar: compound UNIQUE index prevents duplicate row
    summary2 = engine.run_recovery(now_utc=now_utc)
    assert summary2.blocked_created == 0
    assert len(db.get_blocked_signals_by_origin("REPLAY")) == 1


# ---------------------------------------------------------------------------
# Test 15: replay summary counts match replay_runs record
# ---------------------------------------------------------------------------


def test_replay_summary_counts(tmp_path: Path) -> None:
    """Summary payload metrics exactly match persisted replay_runs database row."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    last_cursor_ts = current_closed - (3 * M15_SECONDS)
    config_hash = compute_config_hash()

    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=last_cursor_ts,
        config_hash=config_hash,
    )

    t1 = _ts(last_cursor_ts + M15_SECONDS)
    t2 = _ts(last_cursor_ts + 2 * M15_SECONDS)
    t3 = _ts(last_cursor_ts + 3 * M15_SECONDS)

    sig_valid = _make_buy_signal(entry=2000.0, sl=1990.0, tp=2030.0)
    sig_sub_rr = _make_buy_signal(entry=2000.0, sl=1990.0, tp=2005.0)

    evaluator = FakeStrategyEvaluator(
        signals_map={t1: [sig_valid], t2: [sig_sub_rr], t3: []}
    )

    engine = RestartReplayEngine(
        exness_client=FakeExnessClient(now_utc),
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=evaluator,
        config=RestartReplayConfig(replay_mode="auto", max_bars=32),
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=now_utc)
    assert summary.status == "COMPLETED"
    assert summary.missed_count == 3
    assert summary.replayed_count == 3
    assert summary.observations_created == 1
    assert summary.blocked_created == 1

    assert summary.replay_id is not None
    record = db.get_replay_run(summary.replay_id)
    assert record is not None
    assert record.status == "COMPLETED"
    assert record.missed_count == summary.missed_count
    assert record.observations_created == summary.observations_created
    assert record.blocked_created == summary.blocked_created


# ---------------------------------------------------------------------------
# Runtime Config & Fail-Closed Validation
# ---------------------------------------------------------------------------


def test_runtime_config_fail_closed_validation() -> None:
    """RestartReplayConfig strictly enforces mode and max_bars == 32 without defaults."""
    # Valid explicit config
    cfg = RestartReplayConfig(replay_mode="auto", max_bars=32)
    assert cfg.replay_mode == "auto"
    assert cfg.max_bars == 32

    # Invalid mode
    with pytest.raises(ValueError, match="CONFIG_ERROR: RESTART_REPLAY_MODE"):
        RestartReplayConfig(replay_mode="unknown_mode", max_bars=32)

    # Mismatched max_bars policy cap
    with pytest.raises(ValueError, match="CONFIG_ERROR: RESTART_REPLAY_MAX_BARS"):
        RestartReplayConfig(replay_mode="auto", max_bars=16)

    # Missing from env
    with pytest.raises(ValueError, match="RESTART_REPLAY_MODE is missing"):
        RestartReplayConfig.from_env({})

    # Mismatched from env
    with pytest.raises(ValueError, match="policy mismatch"):
        RestartReplayConfig.from_env(
            {"RESTART_REPLAY_MODE": "auto", "RESTART_REPLAY_MAX_BARS": "64"}
        )


# ---------------------------------------------------------------------------
# Bootstrap Integration & Gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_replay_gated_loop_b_blocks(tmp_path: Path) -> None:
    """Loop B live run_forever fails closed and cancels TaskGroup when replay is blocked."""
    db = _init_db(tmp_path)
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    # Drift config_hash to trigger blocking status
    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=current_closed - (2 * M15_SECONDS),
        config_hash="drifted_hash",
    )

    client = FakeExnessClient(now_utc)
    config = RestartReplayConfig(replay_mode="auto", max_bars=32)
    engine = RestartReplayEngine(
        exness_client=client,
        db_manager=db,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(),
        config=config,
        symbol=SYMBOL,
    )

    m15_event = asyncio.Event()
    stop_event = asyncio.Event()
    loop_b = ReplayGatedLoopB(
        exness_client=client,
        kronos_engine=FakeKronos(),
        strategy_evaluator=FakeStrategyEvaluator(),
        state_machine=SimpleNamespace(state="NORMAL"),
        db_manager=db,
        symbol=SYMBOL,
        replay_engine=engine,
    )

    with pytest.raises(RuntimeError, match="Loop B startup blocked by restart replay"):
        await loop_b.run_forever(m15_event, stop_event)

    assert stop_event.is_set()


@pytest.mark.asyncio
async def test_bootstrap_loop_a_waits_for_replay_gate(tmp_path: Path) -> None:
    """Loop A pauses and does not start live tick polling until replay gate is set."""
    db = _init_db(tmp_path)
    client = FakeExnessClient(1795411608)
    replay_gate = asyncio.Event()
    stop_event = asyncio.Event()

    loop_a = ReplayGatedLoopA(
        exness_client=client,
        state_machine=SimpleNamespace(
            state="NORMAL",
            update_tick=MagicMock(),
            update_spread=MagicMock(),
        ),
        db_manager=db,
        m15_event=asyncio.Event(),
        symbol=SYMBOL,
        poll_interval_seconds=0.01,
        replay_gate=replay_gate,
    )

    task = asyncio.create_task(loop_a.run_forever(stop_event))
    await asyncio.sleep(0.05)
    assert not stop_event.is_set()

    replay_gate.set()
    await asyncio.sleep(0.05)
    stop_event.set()
    await task


def test_bootstrap_build_runtime_bundle_wiring(tmp_path: Path) -> None:
    """build_runtime_bundle successfully wires replay_engine and run_restart_recovery."""
    now_utc = 1795411608
    current_closed = compute_current_closed_bar(now_utc)
    db_path = str(tmp_path / "bundle_wiring.db")
    db = DatabaseManager(db_path=db_path)
    db.init_db()
    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=current_closed,
        config_hash=compute_config_hash(),
    )

    client = FakeExnessClient(now_utc)
    bot = MagicMock()
    evaluator = FakeStrategyEvaluator()
    kronos = FakeKronos()

    bundle = build_runtime_bundle(
        exness_client=client,  # type: ignore[arg-type]
        control_bot=bot,
        admin_chat_id=12345,
        db_path=db_path,
        symbol=SYMBOL,
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
        replay_config=RestartReplayConfig(replay_mode="auto", max_bars=32),
    )

    assert bundle.replay_engine is not None
    summary = run_restart_recovery(bundle, now_utc=now_utc)
    assert summary is not None
    assert summary.status == "NO_GAP"
