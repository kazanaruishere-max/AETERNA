"""Multi-threading concurrency and thread-safety tests for MT5 client.

Validates:
1. REQ-EXE-006: ExnessClient wraps all MT5 C-extension access in threading.RLock.
2. Concurrent workers calling get_current_spread_pips and fetch_recent_candles
   simultaneously never enter MT5 methods concurrently (max_concurrent == 1).
3. Reentrant lock semantics: zero deadlock on nested calls within the same thread.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import numpy as np

from engine.ingestion.python.exness_client import ExnessClient


def _make_dummy_rates() -> Any:
    """Create synthetic numpy structured array matching MT5 copy_rates_from_pos."""
    dt_dtype = np.dtype(
        [
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("tick_volume", "u8"),
            ("spread", "i4"),
            ("real_volume", "u8"),
        ]
    )
    return np.array(
        [
            (1793347200, 2745.50, 2750.00, 2744.20, 2748.10, 1540, 18, 0),
        ],
        dtype=dt_dtype,
    )


def test_mt5_mutual_exclusion_under_high_concurrency() -> None:
    """Validate 10 threads calling MT5 methods simultaneously never overlap in C-extension."""
    active_calls = 0
    max_concurrent_calls = 0
    total_calls = 0
    concurrency_violated = False
    monitor_lock = threading.Lock()

    def mock_copy_rates_from_pos(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal active_calls, max_concurrent_calls, total_calls, concurrency_violated
        with monitor_lock:
            active_calls += 1
            total_calls += 1
            max_concurrent_calls = max(max_concurrent_calls, active_calls)
            if active_calls > 1:
                concurrency_violated = True
        try:
            time.sleep(0.01)
            return _make_dummy_rates()
        finally:
            with monitor_lock:
                active_calls -= 1

    def mock_symbol_info_tick(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal active_calls, max_concurrent_calls, total_calls, concurrency_violated
        with monitor_lock:
            active_calls += 1
            total_calls += 1
            max_concurrent_calls = max(max_concurrent_calls, active_calls)
            if active_calls > 1:
                concurrency_violated = True
        try:
            time.sleep(0.01)
            tick = MagicMock()
            tick.ask = 2750.50
            tick.bid = 2750.20
            return tick
        finally:
            with monitor_lock:
                active_calls -= 1

    mock_mt5 = MagicMock()
    mock_mt5.TIMEFRAME_M15 = 15
    mock_mt5.copy_rates_from_pos.side_effect = mock_copy_rates_from_pos
    mock_mt5.symbol_info_tick.side_effect = mock_symbol_info_tick

    client = ExnessClient(symbol="XAUUSD")
    client.connected = True
    client.mt5 = mock_mt5

    futures: list[concurrent.futures.Future[Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for i in range(20):
            if i % 2 == 0:
                futures.append(executor.submit(client.get_current_spread_pips))
            else:
                futures.append(executor.submit(client.fetch_recent_candles, "M15", 1))

        done, not_done = concurrent.futures.wait(futures, timeout=5.0)

    assert len(not_done) == 0, f"{len(not_done)} tasks timed out (potential deadlock)"
    for f in done:
        assert f.exception() is None

    assert not concurrency_violated, "Mutual exclusion violated: overlapping MT5 calls detected"
    assert max_concurrent_calls == 1, f"Expected max 1 concurrent MT5 call, got {max_concurrent_calls}"
    assert total_calls == 20, f"Expected 20 total calls, got {total_calls}"


def test_reentrant_lock_allows_nested_calls() -> None:
    """Verify RLock allows the same thread to hold lock and call MT5 methods without deadlock."""
    mock_mt5 = MagicMock()
    tick = MagicMock()
    tick.ask = 2750.50
    tick.bid = 2750.20
    mock_mt5.symbol_info_tick.return_value = tick

    client = ExnessClient(symbol="XAUUSD")
    client.connected = True
    client.mt5 = mock_mt5

    with client.lock:
        spread = client.get_current_spread_pips()

    assert spread == 3.0


def test_external_lock_blocks_competing_thread() -> None:
    """Verify holding client.lock externally blocks another thread from entering MT5 call."""
    mock_mt5 = MagicMock()
    tick = MagicMock()
    tick.ask = 2750.50
    tick.bid = 2750.20
    mock_mt5.symbol_info_tick.return_value = tick

    client = ExnessClient(symbol="XAUUSD")
    client.connected = True
    client.mt5 = mock_mt5

    acquired_event = threading.Event()
    worker_finished = threading.Event()
    worker_start_time = 0.0
    worker_finish_time = 0.0

    def background_worker() -> None:
        nonlocal worker_start_time, worker_finish_time
        acquired_event.wait()
        worker_start_time = time.monotonic()
        client.get_current_spread_pips()
        worker_finish_time = time.monotonic()
        worker_finished.set()

    thread = threading.Thread(target=background_worker)
    thread.start()

    with client.lock:
        acquired_event.set()
        time.sleep(0.05)

    worker_finished.wait(timeout=2.0)
    thread.join(timeout=2.0)

    assert worker_finish_time - worker_start_time >= 0.04
