"""Unit tests for the M15 Analysis Loop B.

Validates REQ-RUNTIME-003 (exactly one evaluation per closed bar),
REQ-STR-002 (zero look-ahead M15/H4 context), REQ-STR-007 (Kronos regime
gate), and REQ-RSK-006 (no replayed signal after a restart).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from engine.analysis_engine.python.indicators import MarketRegime
from engine.analysis_engine.python.types import CandleDict, ModelInferenceResult
from engine.ingestion.python.exness_client import ExnessClient
from engine.models import BarCursorRecord
from engine.runtime.loop_b import AnalysisLoopB
from engine.shared.db.database import DatabaseManager
from engine.state_machine.state_machine import NewsStateMachine
from instruments.xauusd.strategies.volatility_breakout import SignalType, TradeSignal

# BAR_TS is the closed M15 bar open-time (M15-aligned).
BAR_TS = 1_700_000_100  # exact M15 floor  (1_700_000_100 % 900 == 0)
M15_STEP = 900
H4_STEP = 14_400
M15_LOOKBACK = 100
H4_LOOKBACK = 512

# H4 cutoff: last closed H4 bar open-time when evaluating BAR_TS.
# Formula: ((BAR_TS + M15_STEP) // H4_STEP) * H4_STEP - H4_STEP
_H4_LAST_CLOSED = ((BAR_TS + M15_STEP) // H4_STEP) * H4_STEP - H4_STEP  # 1_699_977_600
_H4_FORMING_OPEN = (
    _H4_LAST_CLOSED + H4_STEP
)  # 1_699_992_000  (forming — must be excluded)


def _ts(epoch_seconds: int) -> str:
    """Format epoch seconds as an ISO-8601 UTC candle timestamp (test helper)."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rates(bar_ts: int, step: int, count: int) -> list[dict[str, float]]:
    """Build ascending MT5-style rates for *count* closed bars ending at bar_ts.

    Generates timestamps [bar_ts - (count-1)*step, ..., bar_ts] (count closed
    bars) plus one forming bar at bar_ts + step.  bar_ts must be aligned to
    step.
    """
    timestamps = [bar_ts - step * offset for offset in range(count - 1, -1, -1)]
    timestamps.append(bar_ts + step)
    return [
        {
            "time": float(ts),
            "open": 2400.0,
            "high": 2402.0,
            "low": 2398.0,
            "close": 2401.0,
            "tick_volume": 120.0,
        }
        for ts in timestamps
    ]


def _m15_rates() -> list[dict[str, float]]:
    """101 M15 bars: 100 closed bars ending at BAR_TS plus one forming bar."""
    return _rates(BAR_TS, M15_STEP, M15_LOOKBACK)


def _h4_rates() -> list[dict[str, float]]:
    """513 H4 bars: 512 closed bars ending at _H4_LAST_CLOSED plus one forming bar.

    H4 bars are H4-boundary-aligned.  The forming bar at _H4_FORMING_OPEN
    must be excluded by _fetch_context.
    """
    return _rates(_H4_LAST_CLOSED, H4_STEP, H4_LOOKBACK)


def _mock_mt5() -> MagicMock:
    """MT5 stand-in returning 101 M15 bars and 513 H4 bars."""
    mt5 = MagicMock()
    mt5.TIMEFRAME_M15 = 15
    mt5.TIMEFRAME_H4 = 4
    m15_data = _m15_rates()
    h4_data = _h4_rates()

    def _copy(_symbol: str, timeframe: int, _start: int, _count: int) -> Any:
        return m15_data if timeframe == mt5.TIMEFRAME_M15 else h4_data

    mt5.copy_rates_from_pos.side_effect = _copy
    return mt5


class _FakeKronos:
    """Deterministic Kronos stand-in that counts H4 inference calls."""

    def __init__(self) -> None:
        self.calls = 0

    def infer_regime(self, context_candles: list[CandleDict]) -> ModelInferenceResult:
        self.calls += 1
        return ModelInferenceResult(
            model_id="kronos-onnx-test",
            timestamp_utc="2023-11-14T22:15:00Z",
            regime="TRENDING_BULLISH",
            confidence=0.87,
            probabilities={"TRENDING_BULLISH": 0.87},
            context_candles_count=len(context_candles),
            temporal_assertion_passed=True,
        )

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        return len(candles) == H4_LOOKBACK


class _FakeEvaluator:
    """Deterministic strategy evaluator returning a fixed candidate list."""

    def __init__(self, signals: list[TradeSignal]) -> None:
        self.calls = 0
        self.received: list[tuple[int, int]] = []
        self._signals = signals
        # Last candles passed to the evaluator, for boundary assertions.
        self.last_m15: list[CandleDict] = []
        self.last_h4: list[CandleDict] = []

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: Any | None = None,
        sentiment: Any | None = None,
    ) -> list[TradeSignal]:
        self.calls += 1
        self.received.append((len(m15_candles), len(h4_candles)))
        self.last_m15 = list(m15_candles)
        self.last_h4 = list(h4_candles)
        return self._signals


def _signal(signal_type: SignalType, entry: float, sl: float, tp: float) -> TradeSignal:
    return TradeSignal(
        signal_type=signal_type,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        atr_value=5.0,
        h4_regime=MarketRegime.TRENDING_BULLISH,
        reason="unit-test",
    )


def _build_loop(
    tmp_path: Path,
    signals: list[TradeSignal],
    state: str = "NORMAL",
) -> tuple[AnalysisLoopB, DatabaseManager, _FakeEvaluator, _FakeKronos]:
    """Wire Loop B against mocked MT5, fake engines, and temp SQLite."""
    client = ExnessClient(symbol="XAUUSDm")
    client.mt5 = _mock_mt5()
    client.connected = True

    db_manager = DatabaseManager(db_path=tmp_path / "loop_b.db")
    db_manager.init_db()

    evaluator = _FakeEvaluator(signals)
    kronos = _FakeKronos()
    loop_b = AnalysisLoopB(
        exness_client=client,
        kronos_engine=kronos,
        strategy_evaluator=evaluator,
        state_machine=cast(NewsStateMachine, SimpleNamespace(state=state)),
        db_manager=db_manager,
        symbol="XAUUSDm",
    )
    return loop_b, db_manager, evaluator, kronos


def _rows(db_manager: DatabaseManager, table: str) -> list[Any]:
    with db_manager.get_connection() as conn:
        return list(conn.execute(f"SELECT * FROM {table}").fetchall())


# ---------------------------------------------------------------------------
# Original characterisation tests (must not be weakened)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_b_bar_close_advances_cursor_once(tmp_path: Path) -> None:
    """Two events for the same bar close evaluate the bar exactly once."""
    loop_b, db_manager, evaluator, kronos = _build_loop(
        tmp_path, [_signal(SignalType.BUY, 2400.0, 2390.0, 2425.0)]
    )

    first = await loop_b.run_once(BAR_TS)
    second = await loop_b.run_once(BAR_TS)

    assert first is not None
    assert second is None
    assert evaluator.calls == 1
    assert kronos.calls == 1
    assert len(_rows(db_manager, "signal_observations")) == 1
    cursor = db_manager.get_bar_cursor("XAUUSDm", "M15")
    assert cursor is not None
    assert cursor.last_closed_bar_ts == BAR_TS


@pytest.mark.asyncio
async def test_loop_b_writes_signal_observation_when_rr_valid(tmp_path: Path) -> None:
    """A BUY candidate at R:R 2.5 lands as an OPEN observation without look-ahead."""
    loop_b, db_manager, evaluator, _ = _build_loop(
        tmp_path, [_signal(SignalType.BUY, 2400.0, 2390.0, 2425.0)]
    )

    record = await loop_b.run_once(BAR_TS)

    assert record is not None
    assert record.signal_id == f"XAUUSDm:{BAR_TS}:_FakeEvaluator"
    assert record.bar_ts == BAR_TS
    assert record.state == "OPEN"
    assert evaluator.received == [(M15_LOOKBACK, H4_LOOKBACK)]

    rows = _rows(db_manager, "signal_observations")
    assert len(rows) == 1
    row = rows[0]
    assert (row["entry_px"], row["sl_px"], row["tp_px"]) == (2400.0, 2390.0, 2425.0)
    assert (row["order_type"], row["lot_virtual"]) == ("BUY", 0.01)
    assert (row["partial_skipped_min_lot"], row["r_realized_net"]) == (0, 0.0)
    assert row["exit_reason"] is None


@pytest.mark.asyncio
async def test_loop_b_rejects_below_min_rr(tmp_path: Path) -> None:
    """A BUY candidate at R:R 1.9 yields no observation and an audit row."""
    loop_b, db_manager, _, _ = _build_loop(
        tmp_path, [_signal(SignalType.BUY, 2400.0, 2390.0, 2419.0)]
    )

    record = await loop_b.run_once(BAR_TS)

    assert record is None
    assert _rows(db_manager, "signal_observations") == []
    blocked = _rows(db_manager, "blocked_signals")
    assert len(blocked) == 1
    assert blocked[0]["direction"] == "LONG"
    assert "gate=min_rr" in blocked[0]["details"]


@pytest.mark.asyncio
async def test_loop_b_blocks_signal_when_state_paused(tmp_path: Path) -> None:
    """A PAUSED state machine suppresses evaluation and audits the block."""
    loop_b, db_manager, evaluator, _ = _build_loop(
        tmp_path,
        [_signal(SignalType.BUY, 2400.0, 2390.0, 2425.0)],
        state="PAUSED",
    )

    record = await loop_b.run_once(BAR_TS)

    assert record is None
    assert evaluator.calls == 0
    assert _rows(db_manager, "signal_observations") == []
    blocked = _rows(db_manager, "blocked_signals")
    assert [row["reason_blocked"] for row in blocked] == ["state_machine_paused"]


@pytest.mark.asyncio
async def test_loop_b_restart_does_not_replay_old_bar(tmp_path: Path) -> None:
    """A cursor ahead of the signaled bar makes the loop skip evaluation."""
    loop_b, db_manager, evaluator, _ = _build_loop(
        tmp_path, [_signal(SignalType.BUY, 2400.0, 2390.0, 2425.0)]
    )
    future_ts = 9_999_999_900 - (9_999_999_900 % M15_STEP)
    db_manager.advance_bar_cursor(
        BarCursorRecord(
            symbol="XAUUSDm",
            timeframe="M15",
            last_closed_bar_ts=future_ts,
            updated_at_ms=0,
        )
    )

    m15_event = asyncio.Event()
    stop_event = asyncio.Event()
    task = asyncio.create_task(loop_b.run_forever(m15_event, stop_event))
    try:
        m15_event.set()
        await asyncio.sleep(0.05)
    finally:
        stop_event.set()
        await asyncio.wait_for(task, timeout=3.0)

    assert evaluator.calls == 0
    assert _rows(db_manager, "signal_observations") == []
    cursor = db_manager.get_bar_cursor("XAUUSDm", "M15")
    assert cursor is not None
    assert cursor.last_closed_bar_ts == future_ts


# ---------------------------------------------------------------------------
# New boundary / look-ahead tests (REQ-STR-002, REQ-RUNTIME-003)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_b_excludes_forming_bar_at_bar_ts(tmp_path: Path) -> None:
    """Forming M15 and forming H4 bars must never reach the evaluator.

    Given:
      - M15 feed contains 100 closed bars [BAR_TS - 99*900 .. BAR_TS] plus a
        forming bar at BAR_TS + 900.
      - H4 feed contains 512 closed bars ending at _H4_LAST_CLOSED plus a
        forming bar at _H4_FORMING_OPEN.

    Assert:
      - Evaluator receives exactly M15_LOOKBACK M15 candles.
      - Last M15 candle timestamp_utc == _ts(BAR_TS)  (closed bar).
      - Evaluator receives exactly H4_LOOKBACK H4 candles.
      - Last H4 candle timestamp_utc == _ts(_H4_LAST_CLOSED).
      - Forming M15 (BAR_TS + 900) is absent from the slice.
      - Forming H4 (_H4_FORMING_OPEN) is absent from the slice.
    """
    loop_b, _, evaluator, _ = _build_loop(
        tmp_path, [_signal(SignalType.BUY, 2400.0, 2390.0, 2425.0)]
    )

    await loop_b.run_once(BAR_TS)

    assert evaluator.calls == 1, "evaluator must be called exactly once"

    # M15 boundary assertion
    m15_slice = evaluator.last_m15
    assert len(m15_slice) == M15_LOOKBACK
    assert m15_slice[-1]["timestamp_utc"] == _ts(BAR_TS), (
        "last M15 candle must be the closed bar, not the forming bar"
    )
    forming_m15_ts = _ts(BAR_TS + M15_STEP)
    assert all(c["timestamp_utc"] != forming_m15_ts for c in m15_slice), (
        "forming M15 bar must not appear in the slice sent to the evaluator"
    )

    # H4 boundary assertion
    h4_slice = evaluator.last_h4
    assert len(h4_slice) == H4_LOOKBACK
    assert h4_slice[-1]["timestamp_utc"] == _ts(_H4_LAST_CLOSED), (
        "last H4 candle must be the last fully closed H4 bar"
    )
    forming_h4_ts = _ts(_H4_FORMING_OPEN)
    assert all(c["timestamp_utc"] != forming_h4_ts for c in h4_slice), (
        "forming H4 bar must not appear in the slice sent to the evaluator"
    )


@pytest.mark.asyncio
async def test_loop_b_run_forever_uses_previous_closed_bar(tmp_path: Path) -> None:
    """run_forever must evaluate the bar that just closed, not the one opening.

    When Loop A fires m15_event at real-time T where T is in bar whose
    open-time is triggered_bar_ts = floor(T/900)*900, the bar that CLOSED is
    closed_bar_ts = triggered_bar_ts - 900.

    This test patches time.time() so that triggered_bar_ts = BAR_TS + 900,
    which means closed_bar_ts = BAR_TS.  We assert:
      - run_once is invoked with BAR_TS (not BAR_TS + 900).
      - The cursor stored is BAR_TS.
    """
    loop_b, db_manager, evaluator, _ = _build_loop(
        tmp_path, [_signal(SignalType.BUY, 2400.0, 2390.0, 2425.0)]
    )

    # Simulated now: a tick arrived slightly inside BAR_TS + 900.
    fake_now = BAR_TS + M15_STEP + 1

    m15_event = asyncio.Event()
    stop_event = asyncio.Event()

    with patch("engine.runtime.loop_b.time.time", return_value=float(fake_now)):
        task = asyncio.create_task(loop_b.run_forever(m15_event, stop_event))
        try:
            m15_event.set()
            await asyncio.sleep(0.1)
        finally:
            stop_event.set()
            await asyncio.wait_for(task, timeout=3.0)

    assert evaluator.calls == 1, "evaluator must run exactly once"
    # The observation bar_ts must be BAR_TS (the closed bar), not BAR_TS + 900.
    obs_rows = _rows(db_manager, "signal_observations")
    assert len(obs_rows) == 1
    assert obs_rows[0]["bar_ts"] == BAR_TS

    cursor = db_manager.get_bar_cursor("XAUUSDm", "M15")
    assert cursor is not None
    assert cursor.last_closed_bar_ts == BAR_TS, (
        "cursor must record closed_bar_ts, not triggered_bar_ts"
    )
