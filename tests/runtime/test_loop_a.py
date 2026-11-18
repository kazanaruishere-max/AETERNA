"""Unit tests for Fast-Tick Loop A.

Validates REQ-ARCH-007 (2s non-blocking tick cadence), REQ-RSK-001
(spread spike forces PAUSED within one cycle), and REQ-RUNTIME-002
(M15 bar-close event signalling), plus graceful MT5 failure handling.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from engine.ingestion.python.exness_client import ExnessClient
from engine.runtime.loop_a import M15_SECONDS, FastTickLoopA
from engine.shared.db.database import DatabaseManager
from engine.state_machine.news_filter import NewsCalendarFilter
from engine.state_machine.spread_filter import SpreadFilter
from engine.state_machine.state_machine import NewsStateMachine

# 1_700_000_800 falls inside the M15 bar starting at 1_700_000_100;
# 1_700_001_000 is the exact start of the next M15 bar.
BAR_ONE_TS = 1_700_000_800
BAR_TWO_TS = 1_700_001_000


def _tick(bid: float, ask: float, ts: int) -> SimpleNamespace:
    """Build a minimal MT5 tick stand-in."""
    return SimpleNamespace(bid=bid, ask=ask, time=ts)


def _tick_source(*responses: Any) -> Callable[[str], Any]:
    """Return a symbol_info_tick stub yielding responses, then None forever."""
    remaining = list(responses)

    def _next_tick(_symbol: str) -> Any:
        if not remaining:
            return None
        response = remaining.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    return _next_tick


def _build_engine(
    tmp_path: Path,
    *responses: Any,
    warmup_spread: float | None = None,
) -> tuple[FastTickLoopA, DatabaseManager, NewsStateMachine, asyncio.Event]:
    """Wire Loop A against mocked MT5, real state machine, and temp SQLite."""
    mock_mt5 = MagicMock()
    mock_mt5.symbol_info_tick.side_effect = _tick_source(*responses)

    client = ExnessClient(symbol="XAUUSDm")
    client.mt5 = mock_mt5

    db_manager = DatabaseManager(db_path=tmp_path / "loop_a.db")
    db_manager.init_db()

    spread_filter = SpreadFilter(warmup_reads=30)
    if warmup_spread is not None:
        for _ in range(30):
            spread_filter.update(warmup_spread)

    state_machine = NewsStateMachine(
        spread_filter=spread_filter,
        news_filter=NewsCalendarFilter(),
        db_manager=db_manager,
    )
    m15_event = asyncio.Event()
    loop_a = FastTickLoopA(
        exness_client=client,
        state_machine=state_machine,
        db_manager=db_manager,
        m15_event=m15_event,
        symbol="XAUUSDm",
        poll_interval_seconds=0.01,
    )
    return loop_a, db_manager, state_machine, m15_event


async def _run_until(
    loop_a: FastTickLoopA,
    predicate: Callable[[], bool],
) -> None:
    """Run Loop A until predicate holds, then stop and await task completion."""

    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.005)

    stop_event = asyncio.Event()
    task = asyncio.create_task(loop_a.run_forever(stop_event))
    try:
        await asyncio.wait_for(_poll(), timeout=2.0)
    finally:
        stop_event.set()
        await task


@pytest.mark.asyncio
async def test_loop_a_tick_cycle_updates_state_and_database(tmp_path: Path) -> None:
    """One tick bid=2750.0 ask=2750.3 yields 3.0 pips in SM and SQLite."""
    loop_a, db_manager, state_machine, _ = _build_engine(
        tmp_path, _tick(2750.0, 2750.3, BAR_ONE_TS)
    )

    await _run_until(loop_a, lambda: db_manager.get_system_state() is not None)

    record = db_manager.get_system_state()
    assert record is not None
    assert record.id == 1
    assert record.current_spread == 3.0
    assert state_machine.current_spread == 3.0
    assert record.spread_baseline == 3.0
    assert record.state == state_machine.state == "NORMAL"


@pytest.mark.asyncio
async def test_loop_a_detects_m15_bar_close_and_sets_event(tmp_path: Path) -> None:
    """m15_event stays clear on the first bar and fires on the next bar."""
    loop_a, db_manager, _, m15_event = _build_engine(
        tmp_path, _tick(2750.0, 2750.1, BAR_ONE_TS)
    )

    await _run_until(loop_a, lambda: loop_a.last_bar_m15_ts is not None)

    assert loop_a.last_bar_m15_ts == (BAR_ONE_TS // M15_SECONDS) * M15_SECONDS
    assert not m15_event.is_set()

    loop_a.exness_client.mt5.symbol_info_tick.side_effect = _tick_source(
        _tick(2750.0, 2750.1, BAR_TWO_TS)
    )
    await _run_until(loop_a, m15_event.is_set)

    assert m15_event.is_set()
    assert loop_a.last_bar_m15_ts == BAR_TWO_TS
    assert db_manager.get_system_state() is not None


@pytest.mark.asyncio
async def test_loop_a_spread_spike_forces_paused_state(tmp_path: Path) -> None:
    """An extreme spread tick (Z >= 3.0) flips state to PAUSED in one cycle."""
    loop_a, db_manager, state_machine, _ = _build_engine(
        tmp_path, _tick(2750.0, 2750.9, BAR_ONE_TS), warmup_spread=1.0
    )

    await _run_until(loop_a, lambda: db_manager.get_system_state() is not None)

    assert state_machine.z_score is not None
    assert state_machine.z_score >= 3.0
    assert state_machine.state == "PAUSED"
    record = db_manager.get_system_state()
    assert record is not None
    assert record.state == "PAUSED"
    assert record.current_spread == 9.0
    assert record.spread_z_score == state_machine.z_score


@pytest.mark.asyncio
async def test_loop_a_graceful_on_mt5_timeout_or_disconnect(tmp_path: Path) -> None:
    """None tick and TimeoutError are logged and skipped; the next beat survives."""
    loop_a, db_manager, _, _ = _build_engine(
        tmp_path,
        None,
        TimeoutError("symbol_info_tick timeout"),
        _tick(2750.0, 2750.2, BAR_ONE_TS),
    )

    await _run_until(loop_a, lambda: db_manager.get_system_state() is not None)

    record = db_manager.get_system_state()
    assert record is not None
    assert record.current_spread == 2.0
    assert loop_a.exness_client.mt5.symbol_info_tick.call_count >= 3
