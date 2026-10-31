"""
Module: tests.analysis.test_indicators
Responsibility: Deterministic unit tests and Wilder 1978 Golden Benchmark for technical indicators.
Owner: aeterna-verifier
Tier: B
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analysis_engine.python.indicators import (
    MarketRegime,
    calculate_adx,
    calculate_atr,
    calculate_donchian_channel,
    calculate_ema,
    calculate_true_range,
    classify_h4_regime,
    wilder_smoothing,
)

WILDER_1978_DATA: dict[str, list[float]] = {
    "high": [
        50.00,
        51.50,
        52.00,
        53.50,
        53.00,
        50.50,
        49.00,
        48.50,
        47.00,
        48.00,
        49.00,
        49.50,
        48.50,
        47.50,
        47.00,
    ],
    "low": [
        48.00,
        49.50,
        50.00,
        51.00,
        49.50,
        48.00,
        46.50,
        45.00,
        45.50,
        46.00,
        47.50,
        48.00,
        47.00,
        46.00,
        45.00,
    ],
    "close": [
        49.00,
        51.00,
        51.50,
        53.00,
        50.00,
        48.50,
        47.00,
        46.00,
        46.50,
        47.50,
        48.50,
        49.00,
        47.50,
        46.50,
        45.50,
    ],
}


def test_wilder_1978_golden_benchmark() -> None:
    """Verify exact Wilder 1978 textbook golden values on 15th bar (TASK-M3-01 §7.1)."""
    df = pd.DataFrame(WILDER_1978_DATA)
    high = pd.Series(df["high"])
    low = pd.Series(df["low"])
    close = pd.Series(df["close"])
    tr = calculate_true_range(high, low, close)
    assert tr.iloc[0] == pytest.approx(2.00, abs=1e-4)
    assert tr.iloc[1] == pytest.approx(2.50, abs=1e-4)

    # ATR test
    atr = calculate_atr(high, low, close, period=14)
    assert np.isnan(atr.iloc[13])
    assert atr.iloc[14] == pytest.approx(2.214286, abs=1e-4)

    # ADX components test
    plus_di, minus_di, dx, adx = calculate_adx(high, low, close, period=14)
    assert np.isnan(plus_di.iloc[13])
    assert np.isnan(minus_di.iloc[13])
    assert np.isnan(dx.iloc[13])
    assert np.isnan(adx.iloc[14])  # ADX requires 14 bars of DX

    assert plus_di.iloc[14] == pytest.approx(19.354839, abs=1e-4)
    assert minus_di.iloc[14] == pytest.approx(29.032258, abs=1e-4)
    assert dx.iloc[14] == pytest.approx(20.000000, abs=1e-4)


def test_wilder_smoothing_generic() -> None:
    """Verify recursive RMA smoothing formula behavior."""
    series = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
    # period=3: initial at index 2 is mean(10, 12, 14) = 12.0
    ws = wilder_smoothing(series, period=3)
    assert np.isnan(ws.iloc[0])
    assert np.isnan(ws.iloc[1])
    assert ws.iloc[2] == pytest.approx(12.0)
    # bar 3: (12 * 2 + 16) / 3 = 40 / 3 = 13.333333
    assert ws.iloc[3] == pytest.approx(13.333333, abs=1e-4)
    # bar 4: (13.333333 * 2 + 18) / 3 = 44.666667 / 3 = 14.888889
    assert ws.iloc[4] == pytest.approx(14.888889, abs=1e-4)


def test_h4_regime_hysteresis() -> None:
    """Verify all regime branches and boundary conditions (TASK-M3-01 §7.2)."""
    assert classify_h4_regime(26.0, 2750.0, 2700.0) == MarketRegime.TRENDING_BULLISH
    assert classify_h4_regime(26.0, 2680.0, 2700.0) == MarketRegime.TRENDING_BEARISH
    assert classify_h4_regime(22.5, 2750.0, 2700.0) == MarketRegime.TRANSITIONING
    assert classify_h4_regime(20.0, 2750.0, 2700.0) == MarketRegime.TRANSITIONING
    assert classify_h4_regime(24.99, 2750.0, 2700.0) == MarketRegime.TRANSITIONING
    assert classify_h4_regime(18.0, 2750.0, 2700.0) == MarketRegime.RANGING
    assert classify_h4_regime(19.99, 2750.0, 2700.0) == MarketRegime.RANGING


def test_h4_regime_fail_fast_on_nan_and_none() -> None:
    """Verify fail-fast fault-out (Pilar 2) raises ValueError on NaN and None."""
    with pytest.raises(
        ValueError, match="Indicator values contain NaN; cannot classify regime."
    ):
        classify_h4_regime(float("nan"), 2750.0, 2700.0)

    with pytest.raises(
        ValueError, match="Indicator values contain NaN; cannot classify regime."
    ):
        classify_h4_regime(26.0, float("nan"), 2700.0)

    with pytest.raises(
        ValueError, match="Indicator values contain NaN; cannot classify regime."
    ):
        classify_h4_regime(26.0, 2750.0, float("nan"))

    with pytest.raises(
        ValueError, match="Indicator values contain NaN; cannot classify regime."
    ):
        # pyright: ignore[reportArgumentType]
        classify_h4_regime(None, 2750.0, 2700.0)  # type: ignore[arg-type]


def test_donchian_channel_shift() -> None:
    """Verify zero lookahead bias with shift(1) (TASK-M3-01 §7.3)."""
    high = pd.Series([100.0, 105.0, 110.0, 150.0, 108.0])
    low = pd.Series([90.0, 92.0, 95.0, 80.0, 94.0])

    upper, middle, lower = calculate_donchian_channel(high, low, period=3)

    # First 3 bars must be NaN
    assert np.isnan(upper.iloc[0])
    assert np.isnan(upper.iloc[1])
    assert np.isnan(upper.iloc[2])

    # Bar 3 sees max of bars 0..2 (100, 105, 110) -> 110.0 (NOT bar 3's 150.0)
    assert upper.iloc[3] == 110.0
    # Bar 3 sees min of bars 0..2 (90, 92, 95) -> 90.0 (NOT bar 3's 80.0)
    assert lower.iloc[3] == 90.0
    assert middle.iloc[3] == 100.0

    # Bar 4 sees max of bars 1..3 (105, 110, 150) -> 150.0
    assert upper.iloc[4] == 150.0
    # Bar 4 sees min of bars 1..3 (92, 95, 80) -> 80.0
    assert lower.iloc[4] == 80.0
    assert middle.iloc[4] == 115.0


def test_ema_calculation() -> None:
    """Verify standard EMA calculation with adjust=False."""
    series = pd.Series([10.0, 20.0, 30.0, 40.0])
    ema = calculate_ema(series, period=2)
    # alpha = 2 / (2 + 1) = 2/3
    # ema[0] = 10.0
    # ema[1] = 20 * (2/3) + 10 * (1/3) = 16.666667
    assert ema.iloc[0] == pytest.approx(10.0)
    assert ema.iloc[1] == pytest.approx(16.666667, abs=1e-4)


def test_adx_anti_silent_swallowing_zero_division() -> None:
    """Verify anti-silent swallowing returns np.nan when sum_di is zero."""
    # Flat market produces zero movement
    flat_high = pd.Series([100.0] * 20)
    flat_low = pd.Series([100.0] * 20)
    flat_close = pd.Series([100.0] * 20)
    _, _, dx, _ = calculate_adx(flat_high, flat_low, flat_close, period=14)
    # Zero TR and Zero DM leads to NaN (no silent 0.0 fallbacks)
    assert np.isnan(dx.iloc[14])
