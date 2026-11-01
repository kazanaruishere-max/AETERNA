"""
Module: tests.analysis.test_backtest_runner
Responsibility: Integration and parity test suite for PyO3 backtest runner & candle loader.
Owner: aeterna-verifier
Tier: B
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aeterna_backtest  # pyright: ignore[reportMissingTypeStubs]
import pytest

from engine.analysis_engine.python.loader import load_candles_from_db
from engine.analysis_engine.python.runner import BacktestRunner
from engine.analysis_engine.python.types import (
    BacktestConfigDict,
    CandleDict,
    OrderDict,
)
from engine.shared.db.database import DatabaseManager

_backtest_ext: Any = aeterna_backtest


def _make_candle(
    timestamp_utc: str,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: int = 100,
) -> CandleDict:
    """Helper to construct a typed CandleDict."""
    return {
        "timestamp_utc": timestamp_utc,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "tick_volume": volume,
    }


@pytest.fixture
def temp_db(tmp_path: Path) -> DatabaseManager:
    """Create a temporary initialized DatabaseManager for test isolation."""
    db_file = tmp_path / "test_trading.db"
    manager = DatabaseManager(db_path=db_file)
    manager.init_db()
    return manager


def test_pyo3_direct_pnl_parity() -> None:
    """REQ-BKT-001: Pure math PnL parity between Python FFI and hand calculations."""
    cfg: BacktestConfigDict = {
        "contract_size": 100.0,
        "point_size": 0.01,
        "pip_size": 0.10,
        "leverage": 200.0,
        "stop_level_points": 300.0,
        "slippage_free_points": 15.0,
        "default_spread_points": 0.0,
    }

    # 1. Long position: entry 2700.0, exit 2710.0, lot 1.0
    res_long: dict[str, float] = _backtest_ext.py_calculate_pnl(
        direction="LONG",
        entry_price=2700.0,
        exit_price=2710.0,
        lot_size=1.0,
        config=cfg,
    )
    assert abs(res_long["gross_pnl_usd"] - 1000.0) < 1e-6
    assert abs(res_long["net_pnl_usd"] - 1000.0) < 1e-6
    assert abs(res_long["pnl_pips"] - 100.0) < 1e-6
    assert abs(res_long["margin_required_usd"] - 1350.0) < 1e-6

    # 2. Short position: entry 2750.0, exit 2740.0, lot 0.5
    res_short: dict[str, float] = _backtest_ext.py_calculate_pnl(
        direction="SHORT",
        entry_price=2750.0,
        exit_price=2740.0,
        lot_size=0.5,
        config=cfg,
    )
    assert abs(res_short["gross_pnl_usd"] - 500.0) < 1e-6
    assert abs(res_short["net_pnl_usd"] - 500.0) < 1e-6
    assert abs(res_short["pnl_pips"] - 100.0) < 1e-6
    assert abs(res_short["margin_required_usd"] - 687.5) < 1e-6


def test_sqlite_candle_loader_integrity(temp_db: DatabaseManager) -> None:
    """REQ-BKT-001: Validate SQLite candle loading via pair column in ASC order."""
    candles_to_seed = [
        (
            "XAUUSD",
            "M1",
            "2026-01-01T00:02:00Z",
            "exness_mt5",
            2745.0,
            2746.0,
            2744.0,
            2745.0,
            90,
        ),
        (
            "XAUUSD",
            "M1",
            "2026-01-01T00:00:00Z",
            "exness_mt5",
            2740.0,
            2742.0,
            2739.0,
            2740.5,
            100,
        ),
        (
            "XAUUSD",
            "M1",
            "2026-01-01T00:01:00Z",
            "exness_mt5",
            2741.0,
            2746.0,
            2740.5,
            2745.5,
            120,
        ),
        (
            "EURUSD",
            "M1",
            "2026-01-01T00:00:00Z",
            "exness_mt5",
            1.0850,
            1.0860,
            1.0845,
            1.0855,
            50,
        ),
    ]

    with temp_db.get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO market_candles (pair, timeframe, timestamp_utc, source, open, high, low, close, tick_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            candles_to_seed,
        )

    # Load XAUUSD candles
    loaded = load_candles_from_db(
        temp_db, pair="XAUUSD", timeframe="M1", source="exness_mt5"
    )
    assert len(loaded) == 3

    # Verify chronological ASC ordering
    timestamps = [c["timestamp_utc"] for c in loaded]
    assert timestamps == [
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:01:00Z",
        "2026-01-01T00:02:00Z",
    ]

    # Time-window filtering
    filtered = load_candles_from_db(
        temp_db,
        pair="XAUUSD",
        timeframe="M1",
        source="exness_mt5",
        start_time_utc="2026-01-01T00:01:00Z",
        end_time_utc="2026-01-01T00:01:00Z",
    )
    assert len(filtered) == 1
    assert filtered[0]["timestamp_utc"] == "2026-01-01T00:01:00Z"

    # Query with non-existent pair raises ValueError
    with pytest.raises(ValueError, match="No candles found for specified criteria"):
        load_candles_from_db(temp_db, pair="GBPUSD")


def test_end_to_end_backtest_with_sqlite_data(temp_db: DatabaseManager) -> None:
    """REQ-BKT-001: End-to-end simulation from SQLite candles with 1 TP win and 1 SL loss."""
    candles_seed = [
        (
            "XAUUSD",
            "M1",
            "2026-01-01T00:00:00Z",
            "exness_mt5",
            2740.0,
            2742.0,
            2739.0,
            2740.5,
            100,
        ),
        (
            "XAUUSD",
            "M1",
            "2026-01-01T00:01:00Z",
            "exness_mt5",
            2741.0,
            2746.0,
            2740.5,
            2745.5,
            120,
        ),
        (
            "XAUUSD",
            "M1",
            "2026-01-01T00:02:00Z",
            "exness_mt5",
            2745.0,
            2746.0,
            2744.0,
            2745.0,
            90,
        ),
        (
            "XAUUSD",
            "M1",
            "2026-01-01T00:03:00Z",
            "exness_mt5",
            2745.0,
            2745.5,
            2739.0,
            2739.5,
            150,
        ),
    ]

    with temp_db.get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO market_candles (pair, timeframe, timestamp_utc, source, open, high, low, close, tick_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            candles_seed,
        )

    orders: list[OrderDict] = [
        {
            "id": "order-tp-win",
            "direction": "LONG",
            "requested_price": 2740.00,
            "lot_size": 0.10,
            "sl_price": 2735.00,
            "tp_price": 2745.00,
            "signal_timestamp_utc": "2026-01-01T00:00:00Z",
        },
        {
            "id": "order-sl-loss",
            "direction": "LONG",
            "requested_price": 2745.00,
            "lot_size": 0.10,
            "sl_price": 2740.00,
            "tp_price": 2755.00,
            "signal_timestamp_utc": "2026-01-01T00:02:00Z",
        },
    ]

    runner = BacktestRunner(db_manager=temp_db)
    report = runner.run_from_db(
        pair="XAUUSD",
        timeframe="M1",
        source="exness_mt5",
        orders=orders,
        initial_balance=10000.0,
        mc_seed=42,
    )

    assert report.summary["total_trades"] == 2
    assert report.summary["win_trades"] == 1
    assert report.summary["loss_trades"] == 1
    assert len(report.trades) == 2

    # Monte Carlo result exists and includes verified fields
    assert report.monte_carlo is not None
    assert report.monte_carlo["iterations"] == 1000
    assert 0.0 <= report.monte_carlo["risk_of_ruin_10pct_dd"] <= 1.0


def test_short_and_long_symmetry_via_python() -> None:
    """REQ-BKT-001: Short paying spread at Ask exit yields $98 profit vs $100 without spread."""
    candles: list[CandleDict] = [
        _make_candle("2026-01-07T10:00:00Z", 2740.00, 2741.00, 2739.50, 2740.20),
        _make_candle("2026-01-07T10:01:00Z", 2739.00, 2739.50, 2728.00, 2729.00),
    ]

    short_order: list[OrderDict] = [
        {
            "id": "short-win-1",
            "direction": "SHORT",
            "requested_price": 2740.00,
            "lot_size": 0.10,
            "sl_price": 2750.00,
            "tp_price": 2730.00,
            "signal_timestamp_utc": "2026-01-07T10:00:00Z",
        }
    ]
    runner = BacktestRunner()

    # Run A: with standard spread (20.0 points = $0.20 USD)
    config_spread: BacktestConfigDict = {"default_spread_points": 20.0}
    report_spread = runner.run(
        candles=candles, orders=short_order, config=config_spread, run_mc=False
    )

    # Run B: zero spread baseline
    config_zero: BacktestConfigDict = {"default_spread_points": 0.0}
    report_zero = runner.run(
        candles=candles, orders=short_order, config=config_zero, run_mc=False
    )

    assert report_spread.summary["total_trades"] == 1
    assert report_zero.summary["total_trades"] == 1

    net_with_spread = report_spread.summary["net_pnl_usd"]
    net_zero_spread = report_zero.summary["net_pnl_usd"]

    # Short trade paying spread is strictly less profitable than zero spread
    assert net_with_spread < net_zero_spread
    assert abs(net_with_spread - 98.00) < 1e-4
    assert abs(net_zero_spread - 100.00) < 1e-4

    # The difference is exactly the $2.00 spread cost (0.10 lot * 100 * $0.20)
    assert abs(net_zero_spread - net_with_spread - 2.00) < 1e-4


def test_pyo3_monte_carlo_parity() -> None:
    """REQ-BKT-005: Monte Carlo output exact field validation & deterministic reproducibility."""
    trades = [{"net_pnl_usd": 60.0 if i % 2 == 0 else -40.0} for i in range(20)]

    run1: dict[str, Any] = _backtest_ext.py_run_monte_carlo(
        trades=trades,
        num_simulations=1000,
        seed=42,
        initial_equity=10000.0,
    )
    run2: dict[str, Any] = _backtest_ext.py_run_monte_carlo(
        trades=trades,
        num_simulations=1000,
        seed=42,
        initial_equity=10000.0,
    )

    # 1. Exact field name checks
    expected_fields = {
        "iterations",
        "median_max_dd_pct",
        "percentile_95_max_dd_pct",
        "percentile_99_max_dd_pct",
        "risk_of_ruin_10pct_dd",
    }
    assert set(run1.keys()) == expected_fields
    assert run1["iterations"] == 1000
    assert 0.0 <= run1["risk_of_ruin_10pct_dd"] <= 1.0

    # 2. 100% reproducibility check between seeded runs
    assert run1["iterations"] == run2["iterations"]
    assert abs(run1["median_max_dd_pct"] - run2["median_max_dd_pct"]) < 1e-6
    assert (
        abs(run1["percentile_95_max_dd_pct"] - run2["percentile_95_max_dd_pct"]) < 1e-6
    )
    assert (
        abs(run1["percentile_99_max_dd_pct"] - run2["percentile_99_max_dd_pct"]) < 1e-6
    )
    assert abs(run1["risk_of_ruin_10pct_dd"] - run2["risk_of_ruin_10pct_dd"]) < 1e-6


def test_pyo3_boundary_validation_raises_value_error() -> None:
    """REQ-BKT-001: Invalid inputs raise ValueError without crashing or panicking."""
    # 1. Candle with high < low
    invalid_candle_high_low = [
        _make_candle("2026-01-01T00:00:00Z", 2740.0, 2730.0, 2750.0, 2740.0)
    ]
    with pytest.raises(ValueError):
        _backtest_ext.py_run_backtest(invalid_candle_high_low, [], None, 10000.0)

    # 2. Candle with negative or zero price
    invalid_candle_zero = [
        _make_candle("2026-01-01T00:00:00Z", 0.0, 2750.0, 2730.0, 2740.0)
    ]
    with pytest.raises(ValueError):
        _backtest_ext.py_run_backtest(invalid_candle_zero, [], None, 10000.0)

    # 3. Invalid order requested price
    valid_candle = [
        _make_candle("2026-01-01T00:00:00Z", 2740.0, 2750.0, 2730.0, 2740.0)
    ]
    invalid_order: list[OrderDict] = [
        {
            "id": "order-neg",
            "direction": "LONG",
            "requested_price": -100.0,
            "lot_size": 0.10,
            "sl_price": None,
            "tp_price": None,
            "signal_timestamp_utc": "2026-01-01T00:00:00Z",
        }
    ]
    with pytest.raises(ValueError):
        _backtest_ext.py_run_backtest(valid_candle, invalid_order, None, 10000.0)

    # 4. Invalid initial balance
    with pytest.raises(ValueError, match="Initial balance must be positive and finite"):
        _backtest_ext.py_run_backtest(valid_candle, [], None, -1000.0)

    # 5. Invalid direction
    with pytest.raises(ValueError, match="Invalid direction"):
        _backtest_ext.py_calculate_pnl("UPWARDS", 2700.0, 2710.0, 1.0, None)

    # 6. Empty trades in Monte Carlo
    with pytest.raises(ValueError):
        _backtest_ext.py_run_monte_carlo([], 1000, 42, 10000.0)


def test_hours_since_weekly_open_dst() -> None:
    """REQ-BKT-001: Dynamic US DST calculation parity for weekly market open."""
    # Summer (US EDT): Market opens Sunday 21:00 UTC
    # 2026-06-08T00:00:00Z is Monday 00:00 UTC -> 3.0 Sunday hours elapsed
    summer_hours: float = _backtest_ext.py_hours_since_weekly_open(
        "2026-06-08T00:00:00Z"
    )
    assert abs(summer_hours - 3.0) < 1e-4

    # Winter (US EST): Market opens Sunday 22:00 UTC
    # 2026-01-05T00:00:00Z is Monday 00:00 UTC -> 2.0 Sunday hours elapsed
    winter_hours: float = _backtest_ext.py_hours_since_weekly_open(
        "2026-01-05T00:00:00Z"
    )
    assert abs(winter_hours - 2.0) < 1e-4


def test_stale_orders_logged_to_blocked_signals_db(temp_db: DatabaseManager) -> None:
    """REQ-ING-002: Stale orders beyond validity window are logged to blocked_signals in SQLite."""
    candle_seed = [
        (
            "XAUUSD",
            "M1",
            "2026-01-01T10:30:00Z",
            "exness_mt5",
            2740.0,
            2745.0,
            2738.0,
            2742.0,
            100,
        )
    ]
    with temp_db.get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO market_candles (pair, timeframe, timestamp_utc, source, open, high, low, close, tick_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            candle_seed,
        )

    stale_order: list[OrderDict] = [
        {
            "id": "order-stale-1",
            "direction": "LONG",
            "requested_price": 2740.00,
            "lot_size": 0.10,
            "sl_price": 2730.00,
            "tp_price": 2750.00,
            "signal_timestamp_utc": "2026-01-01T10:00:00Z",  # 1800s elapsed > 900s validity window
            "validity_window_seconds": 900,
        }
    ]

    runner = BacktestRunner(db_manager=temp_db)
    report = runner.run_from_db(
        pair="XAUUSD",
        timeframe="M1",
        source="exness_mt5",
        orders=stale_order,
        run_mc=False,
    )

    assert len(report.discarded_orders) == 1
    discarded = report.discarded_orders[0]
    assert discarded["order_id"] == "order-stale-1"
    assert discarded["reason"] == "stale_signal_expired"
    assert discarded["elapsed_seconds"] == 1800
    assert report.summary["total_trades"] == 0

    # Verify row inserted into SQLite blocked_signals table
    with temp_db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM blocked_signals WHERE reason_blocked = 'stale_signal_expired';"
        )
        rows = cursor.fetchall()

    assert len(rows) == 1
    blocked_row = dict(rows[0])
    assert blocked_row["reason_blocked"] == "stale_signal_expired"
    assert blocked_row["pair"] == "XAUUSD"
    assert blocked_row["direction"] == "LONG"
    assert abs(blocked_row["would_be_entry_price"] - 2740.00) < 1e-4
    assert "order-stale-1" in (blocked_row["details"] or "")
    assert blocked_row["timestamp_utc"] == "2026-01-01T10:30:00Z"
