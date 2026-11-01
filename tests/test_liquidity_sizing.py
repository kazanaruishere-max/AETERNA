"""Deterministic unit tests for liquidity filter, rollover protection, and position sizing.

Enforces financial invariants:
- REQ-RSK-003: Tick volume rolling Z-score & graduated sizing.
- REQ-RSK-006: Rollover buffer DST-aware boundaries.
- REQ-ING-002: Distinct audit reasons in rejection.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime

from engine.risk_gate.liquidity import RolloverFilter, TickVolumeFilter
from engine.risk_gate.sizing import PositionSizer


def test_tick_volume_warmup_and_anti_div_zero() -> None:
    """Readings 1..19 suppress Z-score; reading 20 produces valid float.

    Flat volume series produces Z = 0.0 without division by zero.
    """
    tvf = TickVolumeFilter(window_size=60, warmup_reads=20)

    for i in range(1, 20):
        mean, std, z = tvf.update(100.0)
        assert z is None, f"Reading {i} must suppress Z-score during warmup"
        assert not tvf.is_warmed_up
        assert tvf.read_count == i
        assert mean == 100.0
        assert std == 0.0

    # Reading 20 satisfies warmup
    mean, std, z = tvf.update(100.0)
    assert z is not None
    assert z == 0.0
    assert not math.isnan(z)
    assert tvf.is_warmed_up
    assert tvf.read_count == 20

    # Continue flat volume for another 80 ticks (total 100)
    for _ in range(80):
        _, std, z_flat = tvf.update(100.0)
        assert std == 0.0
        assert z_flat == 0.0


def test_graduated_liquidity_scale() -> None:
    """Z >= -2.0 produces scale 1.0; Z < -2.0 produces scale 0.5."""
    tvf = TickVolumeFilter(window_size=60, warmup_reads=20)

    # In warmup, scale is 1.0
    assert tvf.get_liquidity_scale() == 1.0

    # Warmup with high activity baseline around 1000
    for _ in range(30):
        tvf.update(1000.0)

    # Add variance to baseline
    for _ in range(15):
        tvf.update(1200.0)
    for _ in range(15):
        tvf.update(800.0)

    # Moderate volume near mean -> scale 1.0
    _, _, z_norm = tvf.update(950.0)
    assert z_norm is not None and z_norm >= -2.0
    assert tvf.get_liquidity_scale() == 1.0

    # Extreme low volume drop -> Z < -2.0 -> scale 0.5
    _, _, z_low = tvf.update(10.0)
    assert z_low is not None and z_low < -2.0
    assert tvf.get_liquidity_scale() == 0.5


def test_dst_aware_rollover_buffer_boundaries() -> None:
    """Verify US Summer (EDT) and Winter (EST) buffer boundary seconds.

    Summer: 20:44:00 - 22:01:00 UTC.
    Winter: 21:44:00 - 23:01:00 UTC.
    """
    # Summer (July 15, 2026 - EDT active)
    assert not RolloverFilter.is_in_rollover_buffer(datetime(2026, 7, 15, 20, 43, 59, tzinfo=UTC))
    assert RolloverFilter.is_in_rollover_buffer(datetime(2026, 7, 15, 20, 44, 0, tzinfo=UTC))
    assert RolloverFilter.is_in_rollover_buffer(datetime(2026, 7, 15, 22, 1, 0, tzinfo=UTC))
    assert not RolloverFilter.is_in_rollover_buffer(datetime(2026, 7, 15, 22, 1, 1, tzinfo=UTC))

    # Winter (January 15, 2026 - EST active)
    assert not RolloverFilter.is_in_rollover_buffer(datetime(2026, 1, 15, 21, 43, 59, tzinfo=UTC))
    assert RolloverFilter.is_in_rollover_buffer(datetime(2026, 1, 15, 21, 44, 0, tzinfo=UTC))
    assert RolloverFilter.is_in_rollover_buffer(datetime(2026, 1, 15, 23, 1, 0, tzinfo=UTC))
    assert not RolloverFilter.is_in_rollover_buffer(datetime(2026, 1, 15, 23, 1, 1, tzinfo=UTC))


def test_sizing_operation_order_divergence() -> None:
    """Scale-before-floor ordering prevents illegal broker steps and preserves risk budget.

    Equity = 1580.0, Risk = 0.5% (7.9 USD), SL Distance = 2.0 USD (200 USD/lot).
    Base Raw Lot = 7.9 / 200 = 0.0395.
    Correct Path (scale before floor): 0.0395 * 0.5 = 0.01975 -> floor = 0.01 lot.
    Flawed Path (floor before scale): floor(0.0395) = 0.03 -> 0.03 * 0.5 = 0.015 (invalid broker step!).
    """
    sizer = PositionSizer(risk_per_trade_pct=0.005, contract_size=100.0, min_lot=0.01)

    result = sizer.calculate_lot_size(
        equity_usd=1580.0,
        entry_price=2000.0,
        sl_price=1998.0,
        liquidity_scale=0.5,
    )

    assert result.is_valid is True
    assert result.lot_size == 0.01
    assert result.risk_usd == 7.9
    assert abs(result.raw_lot - 0.0395) < 1e-9
    assert result.liquidity_scale == 0.5
    assert result.rejection_reason is None

    # Verify that the lot size is strictly a multiple of min_lot (0.01)
    step_multiple = round(result.lot_size / 0.01, 6)
    assert step_multiple.is_integer()


def test_rejection_reason_differentiation() -> None:
    """Order rejection audit reasons must distinguish rollover vs insufficient equity."""
    sizer = PositionSizer(risk_per_trade_pct=0.005, contract_size=100.0, min_lot=0.01)

    # Scenario A: Blocked by rollover
    res_rollover = sizer.calculate_lot_size(
        equity_usd=10000.0,
        entry_price=2000.0,
        sl_price=1995.0,
        is_rollover=True,
    )
    assert res_rollover.is_valid is False
    assert res_rollover.lot_size == 0.0
    assert res_rollover.rejection_reason == "pre_rollover_force"

    # Scenario B: Low equity unable to afford 0.01 min lot with 0.5% risk
    # Equity = 200.0, 0.5% = 1.0 USD risk. SL 2.0 pts = 200 USD/lot. Raw = 0.005 < 0.01
    res_low_equity = sizer.calculate_lot_size(
        equity_usd=200.0,
        entry_price=2000.0,
        sl_price=1998.0,
        is_rollover=False,
    )
    assert res_low_equity.is_valid is False
    assert res_low_equity.lot_size == 0.0
    assert res_low_equity.rejection_reason == "insufficient_equity_for_min_lot"

    assert res_rollover.rejection_reason != res_low_equity.rejection_reason


def test_risk_percentage_never_exceeded() -> None:
    """100 random combinations of equity and SL distance never exceed 0.5% risk invariant."""
    sizer = PositionSizer(risk_per_trade_pct=0.005, contract_size=100.0, min_lot=0.01)

    rng = random.Random(42)
    for _ in range(100):
        equity = rng.uniform(100.0, 500000.0)
        entry = rng.uniform(1800.0, 2800.0)
        sl_dist = rng.uniform(0.5, 60.0)
        direction = rng.choice([-1.0, 1.0])
        sl = entry + direction * sl_dist
        scale = rng.choice([0.5, 1.0])

        res = sizer.calculate_lot_size(
            equity_usd=equity,
            entry_price=entry,
            sl_price=sl,
            liquidity_scale=scale,
        )

        if res.is_valid:
            actual_risk_usd = res.lot_size * sl_dist * 100.0
            risk_pct = actual_risk_usd / equity
            # Strict tolerance checking 0.5% (0.005)
            assert risk_pct <= 0.005000001, f"Risk {risk_pct:.7f} exceeded 0.005 for equity {equity}"
            assert res.lot_size >= 0.01
            assert res.lot_size <= 50.0
