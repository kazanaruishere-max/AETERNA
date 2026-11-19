"""Deterministic unit tests for the virtual signal tracker.

Locks REQ-RUNTIME-004, REQ-RSK-005, REQ-RSK-006, and REQ-RSK-007: exits resolve
from bid/ask only and a missing tick never mutates state.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from engine.ingestion.python.exness_client import ExnessClient
from engine.models import SignalObservationRecord
from engine.runtime.virtual_tracker import VirtualSignalTracker
from engine.shared.db.database import DatabaseManager

BAR_TS = 1_699_963_200  # 2023-11-14T12:00:00Z, far outside any rollover buffer
ROLLOVER_TS = 1_699_998_600  # 2023-11-14T21:50:00Z, inside the winter buffer
ENTRY_PX, RISK_DISTANCE = 2750.0, 2.0
Observation = tuple[str, float, str | None]


def _tick(bid: float, ask: float, ts: int = BAR_TS) -> Any:
    return SimpleNamespace(bid=bid, ask=ask, time=ts)


def _signal(
    order_type: str = "BUY", bar_ts: int = BAR_TS, lot_virtual: float = 0.01
) -> SignalObservationRecord:
    """BUY risks 2.0 with TP at 2R; SELL mirrors the same geometry."""
    sign = 1.0 if order_type == "BUY" else -1.0
    return SignalObservationRecord(
        signal_id=f"XAUUSDm:{bar_ts}:{order_type}",
        symbol="XAUUSDm",
        bar_ts=bar_ts,
        strategy_id="volatility_breakout",
        order_type=order_type,
        state="OPEN",
        entry_px=ENTRY_PX,
        sl_px=ENTRY_PX - sign * RISK_DISTANCE,
        tp_px=ENTRY_PX + sign * 2.0 * RISK_DISTANCE,
        lot_virtual=lot_virtual,
    )


def _db(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(tmp_path / "virtual_tracker.db")
    manager.init_db()
    return manager


def _tracker(
    db: DatabaseManager,
    regime: str = "TRENDING_BULLISH",
    tick_fn: Any = None,
    **kwargs: Any,
) -> VirtualSignalTracker:
    client = ExnessClient()
    client.mt5 = MagicMock()
    if tick_fn is not None:
        client.mt5.symbol_info_tick.side_effect = tick_fn
    return VirtualSignalTracker(client, db, regime_provider=lambda: regime, **kwargs)


def _mark(
    db: DatabaseManager,
    signal: SignalObservationRecord,
    tick: Any,
    regime: str = "TRENDING_BULLISH",
) -> bool:
    assert db.insert_signal_observation(signal)
    return _tracker(db, regime).mark_to_market(signal, tick)


def _read(db: DatabaseManager, signal_id: str) -> Observation:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT state, r_realized_net, exit_reason FROM signal_observations"
            " WHERE signal_id = ?",
            (signal_id,),
        ).fetchone()
    assert row is not None
    return (row["state"], row["r_realized_net"], row["exit_reason"])


def test_virtual_tracker_closes_long_at_stop_loss(tmp_path: Path) -> None:
    """BUY at bid 2748.00 pays the 0.20 spread on top of its full 1R risk."""
    db = _db(tmp_path)
    signal = _signal()

    assert _mark(db, signal, _tick(2748.0, 2748.2)) is True

    state, r_net, exit_reason = _read(db, signal.signal_id)
    assert (state, exit_reason) == ("CLOSED_SL", "sl_hit")
    assert r_net == pytest.approx(-1.1)


def test_virtual_tracker_closes_short_at_take_profit_with_spread_cost(
    tmp_path: Path,
) -> None:
    """A short TP beyond 2R realizes 2.05 net R after the 0.20 spread."""
    db = _db(tmp_path)
    signal = _signal(order_type="SELL")

    assert _mark(db, signal, _tick(2745.5, 2745.7), "TRENDING_BEARISH") is True

    state, r_net, exit_reason = _read(db, signal.signal_id)
    assert (state, exit_reason) == ("CLOSED_TP", "tp_hit")
    assert r_net == pytest.approx(2.15 - 0.20 / RISK_DISTANCE)


def test_virtual_tracker_time_invalidation_after_eight_m15_bars(
    tmp_path: Path,
) -> None:
    """Exactly 8 M15 bars (7200s) of dead tape closes the observation."""
    db = _db(tmp_path)
    signal = _signal()

    assert _mark(db, signal, _tick(2750.2, 2750.4, BAR_TS + 7200)) is True

    state, _, exit_reason = _read(db, signal.signal_id)
    assert (state, exit_reason) == ("CLOSED_TIME", "time_invalidation")


def test_virtual_tracker_time_invalidation_boundary(tmp_path: Path) -> None:
    for elapsed, expected_state in ((7199, "OPEN"), (7200, "CLOSED_TIME")):
        case_path = tmp_path / str(elapsed)
        case_path.mkdir()
        db = _db(case_path)
        signal = _signal()

        assert _mark(db, signal, _tick(2750.2, 2750.4, BAR_TS + elapsed)) is (
            elapsed == 7200
        )

        state, _, _ = _read(db, signal.signal_id)
        assert state == expected_state


def test_virtual_tracker_regime_flip_forces_exit(tmp_path: Path) -> None:
    """A bearish H4 regime invalidates a live long immediately."""
    db = _db(tmp_path)
    signal = _signal()

    assert _mark(db, signal, _tick(2750.2, 2750.4), "TRENDING_BEARISH") is True

    state, _, exit_reason = _read(db, signal.signal_id)
    assert (state, exit_reason) == ("CLOSED_REGIME", "regime_invalidation")


def test_virtual_tracker_sell_regime_flip_forces_exit(tmp_path: Path) -> None:
    db = _db(tmp_path)
    signal = _signal(order_type="SELL")

    assert _mark(db, signal, _tick(2749.8, 2750.0), "TRENDING_BULLISH") is True

    state, _, exit_reason = _read(db, signal.signal_id)
    assert (state, exit_reason) == ("CLOSED_REGIME", "regime_invalidation")


def test_virtual_tracker_partial_skipped_at_min_lot(tmp_path: Path) -> None:
    """A 0.01-lot signal cannot split 50%, so the marker becomes its state."""
    db = _db(tmp_path)
    signal = _signal()

    assert _mark(db, signal, _tick(2752.1, 2752.1)) is True
    assert _read(db, signal.signal_id)[0] == "PARTIAL_SKIPPED_MIN_LOT"

    active = db.get_open_signal_observations("XAUUSDm")
    assert len(active) == 1
    assert _tracker(db).mark_to_market(active[0], _tick(2752.1, 2752.1)) is True
    assert _read(db, signal.signal_id)[0] == "RUNNING"


def test_virtual_tracker_forces_exit_inside_rollover_buffer(tmp_path: Path) -> None:
    """15 minutes before the winter bank break the virtual row is closed."""
    db = _db(tmp_path)
    signal = _signal(bar_ts=ROLLOVER_TS - 300)

    assert _mark(db, signal, _tick(2750.2, 2750.4, ROLLOVER_TS)) is True

    state, _, exit_reason = _read(db, signal.signal_id)
    assert (state, exit_reason) == ("CLOSED_ROLLOVER", "pre_rollover_force")


def test_virtual_tracker_rollover_outside_buffer_does_not_close(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    timestamp = ROLLOVER_TS - 1800
    signal = _signal(bar_ts=timestamp - 300)

    assert _mark(db, signal, _tick(2750.2, 2750.4, timestamp)) is False

    state, _, exit_reason = _read(db, signal.signal_id)
    assert (state, exit_reason) == ("OPEN", None)


def test_virtual_tracker_arms_be_at_threshold(tmp_path: Path) -> None:
    db = _db(tmp_path)
    signal = _signal()

    assert _mark(db, signal, _tick(2753.0, 2753.0)) is True

    assert _read(db, signal.signal_id) == ("BE_ARMED", 0.10, None)


def test_virtual_tracker_does_not_arm_be_below_threshold(tmp_path: Path) -> None:
    db = _db(tmp_path)
    signal = _signal()

    assert _mark(db, signal, _tick(2752.98, 2752.98)) is True

    assert _read(db, signal.signal_id) == ("PARTIAL_SKIPPED_MIN_LOT", 0.0, None)


def test_virtual_tracker_closes_be_armed_at_floor(tmp_path: Path) -> None:
    db = _db(tmp_path)
    signal = dataclasses.replace(_signal(), state="BE_ARMED", r_realized_net=0.10)

    assert _mark(db, signal, _tick(2750.2, 2750.2)) is True

    assert _read(db, signal.signal_id) == ("CLOSED_TRAILING", 0.10, "trailing_hit")


def test_virtual_tracker_be_armed_does_not_regress_to_running(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    signal = dataclasses.replace(_signal(), state="BE_ARMED", r_realized_net=0.10)

    assert _mark(db, signal, _tick(2752.4, 2752.4)) is False

    assert _read(db, signal.signal_id) == ("BE_ARMED", 0.10, None)


def test_virtual_tracker_rejects_zero_risk_distance(tmp_path: Path) -> None:
    """A degenerate SL never fabricates an exit or touches the row."""
    db = _db(tmp_path)
    signal = dataclasses.replace(_signal(), sl_px=ENTRY_PX)
    assert db.insert_signal_observation(signal)

    with patch.object(db, "update_signal_observation") as update:
        assert _tracker(db).mark_to_market(signal, _tick(2750.2, 2750.4)) is False
    update.assert_not_called()


@pytest.mark.asyncio
async def test_virtual_tracker_timeout_keeps_state_unchanged(tmp_path: Path) -> None:
    """A tick missing its 0.05s budget leaves the observation untouched."""
    db = _db(tmp_path)
    signal = _signal()
    assert db.insert_signal_observation(signal)

    def _stalled_tick(_symbol: str) -> Any:
        time.sleep(0.5)
        return _tick(2752.1, 2752.1)

    tracker = _tracker(
        db,
        tick_fn=_stalled_tick,
        tick_timeout_seconds=0.05,
        poll_interval_seconds=0.05,
    )
    with patch.object(db, "update_signal_observation") as update:
        stop_event = asyncio.Event()
        task = asyncio.create_task(tracker.run_forever(stop_event))
        await asyncio.sleep(0.2)
        stop_event.set()
        await asyncio.wait_for(task, timeout=3.0)

    update.assert_not_called()
    assert _read(db, signal.signal_id) == ("OPEN", 0.0, None)
