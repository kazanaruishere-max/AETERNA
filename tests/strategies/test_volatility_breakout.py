"""Module: tests.strategies.test_volatility_breakout
Responsibility: Unit tests for M15 Volatility Breakout Strategy & H4 Regime Gate.
Owner: aeterna-strategy
Tier: Tier B
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from engine.analysis_engine.python.indicators import MarketRegime
from instruments.xauusd.strategies.volatility_breakout import (
    SignalType,
    TradeSignal,
    VolatilityBreakoutStrategy,
)


def _create_h4_dataframe(regime: str, n: int = 80) -> pd.DataFrame:
    """Create deterministic H4 OHLCV DataFrame for testing."""
    if regime == "bullish":
        # Steady uptrend: high ADX (>25) and EMA50 > EMA200
        high = [2600.0 + i * 2.0 for i in range(n)]
        low = [2598.0 + i * 2.0 for i in range(n)]
        close = [2599.0 + i * 2.0 for i in range(n)]
    elif regime == "bearish":
        # Steady downtrend: high ADX (>25) and EMA50 < EMA200
        high = [3000.0 - i * 2.0 for i in range(n)]
        low = [2998.0 - i * 2.0 for i in range(n)]
        close = [2999.0 - i * 2.0 for i in range(n)]
    elif regime == "ranging":
        # Low ADX (<20) via oscillation
        t = np.arange(n)
        close = [float(2600.0 + 3.0 * np.sin(val * 0.4)) for val in t]
        high = [c + 2.0 for c in close]
        low = [c - 2.0 for c in close]
    elif regime == "transitioning":
        # ADX between 20 and 25
        t = np.arange(n)
        close = [float(2600.0 + 3.0 * np.sin(val * 0.29)) for val in t]
        high = [c + 2.0 for c in close]
        low = [c - 2.0 for c in close]
    else:
        raise ValueError(f"Unknown regime requested: {regime}")

    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": [100] * n,
        }
    )


def _create_m15_dataframe(
    breakout_type: str = "none",
    bars: int = 25,
    base_high: float = 2650.0,
    base_low: float = 2640.0,
    base_close: float = 2645.0,
    expansion: bool = True,
) -> pd.DataFrame:
    """Create deterministic M15 OHLCV DataFrame with Donchian base and breakout bar."""
    high = [base_high] * (bars - 1)
    low = [base_low] * (bars - 1)
    close = [base_close] * (bars - 1)

    # Base ATR(14) with range 10.0 is ~10.43. 1.2 * ATR is ~12.51.
    if breakout_type == "bullish":
        # Close > base_high (2650.0)
        breakout_close = 2655.0
        if expansion:
            # Bar range = 2656 - 2640 = 16.0 (>= 1.2 * ATR)
            breakout_high = 2656.0
            breakout_low = 2640.0
        else:
            # Bar range = 2655 - 2648 = 7.0 (< 1.2 * ATR)
            breakout_high = 2655.0
            breakout_low = 2648.0
        high.append(breakout_high)
        low.append(breakout_low)
        close.append(breakout_close)
    elif breakout_type == "bearish":
        # Close < base_low (2640.0)
        breakout_close = 2635.0
        if expansion:
            # Bar range = 2645 - 2629 = 16.0 (>= 1.2 * ATR)
            breakout_high = 2645.0
            breakout_low = 2629.0
        else:
            # Bar range = 2638 - 2632 = 6.0 (< 1.2 * ATR)
            breakout_high = 2638.0
            breakout_low = 2632.0
        high.append(breakout_high)
        low.append(breakout_low)
        close.append(breakout_close)
    else:
        # No breakout: inside channel
        high.append(base_high)
        low.append(base_low)
        close.append(base_close)

    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": [100] * bars,
        }
    )


def test_bullish_breakout_confirmed() -> None:
    """Verify BUY signal when H4 Bullish + M15 Upper Breakout + ATR Expansion (RTM REQ-STR-001)."""
    h4_df = _create_h4_dataframe("bullish")
    m15_df = _create_m15_dataframe(breakout_type="bullish", expansion=True)

    strategy = VolatilityBreakoutStrategy()
    signal = strategy.evaluate_signal(m15_df=m15_df, h4_df=h4_df)

    assert signal.signal_type == SignalType.BUY
    assert signal.h4_regime == MarketRegime.TRENDING_BULLISH
    assert signal.entry_price == 2655.0
    assert signal.reason == "Bullish breakout confirmed"

    # Verify SL = Close - (1.5 * ATR)
    expected_sl = signal.entry_price - (1.5 * signal.atr_value)
    assert signal.stop_loss == pytest.approx(expected_sl)

    # Verify TP = Close + (2.0 * 1.5 * ATR)
    expected_tp = signal.entry_price + (2.0 * 1.5 * signal.atr_value)
    assert signal.take_profit == pytest.approx(expected_tp)

    # Verify Reward-to-Risk ratio is precisely 2.0
    rr_ratio = (signal.take_profit - signal.entry_price) / (
        signal.entry_price - signal.stop_loss
    )
    assert rr_ratio == pytest.approx(2.0, rel=1e-5)


def test_bearish_breakout_confirmed() -> None:
    """Verify SELL signal when H4 Bearish + M15 Lower Breakout + ATR Expansion (RTM REQ-STR-001)."""
    h4_df = _create_h4_dataframe("bearish")
    m15_df = _create_m15_dataframe(breakout_type="bearish", expansion=True)

    strategy = VolatilityBreakoutStrategy()
    signal = strategy.evaluate_signal(m15_df=m15_df, h4_df=h4_df)

    assert signal.signal_type == SignalType.SELL
    assert signal.h4_regime == MarketRegime.TRENDING_BEARISH
    assert signal.entry_price == 2635.0
    assert signal.reason == "Bearish breakout confirmed"

    # Verify SL = Close + (1.5 * ATR)
    expected_sl = signal.entry_price + (1.5 * signal.atr_value)
    assert signal.stop_loss == pytest.approx(expected_sl)

    # Verify TP = Close - (2.0 * 1.5 * ATR)
    expected_tp = signal.entry_price - (2.0 * 1.5 * signal.atr_value)
    assert signal.take_profit == pytest.approx(expected_tp)

    # Verify Reward-to-Risk ratio is precisely 2.0
    rr_ratio = (signal.entry_price - signal.take_profit) / (
        signal.stop_loss - signal.entry_price
    )
    assert rr_ratio == pytest.approx(2.0, rel=1e-5)


def test_h4_regime_blocks_entry() -> None:
    """Verify M15 breakout is blocked if H4 is RANGING or TRANSITIONING (RTM REQ-STR-002)."""
    strategy = VolatilityBreakoutStrategy()
    m15_bullish = _create_m15_dataframe(breakout_type="bullish", expansion=True)

    # 1. RANGING H4
    h4_ranging = _create_h4_dataframe("ranging")
    sig_ranging = strategy.evaluate_signal(m15_df=m15_bullish, h4_df=h4_ranging)
    assert sig_ranging.signal_type == SignalType.NO_SIGNAL
    assert sig_ranging.h4_regime == MarketRegime.RANGING
    assert sig_ranging.reason == "Blocked by H4 regime"

    # 2. TRANSITIONING H4
    h4_trans = _create_h4_dataframe("transitioning")
    sig_trans = strategy.evaluate_signal(m15_df=m15_bullish, h4_df=h4_trans)
    assert sig_trans.signal_type == SignalType.NO_SIGNAL
    assert sig_trans.h4_regime == MarketRegime.TRANSITIONING
    assert sig_trans.reason == "Blocked by H4 regime"


def test_counter_trend_breakout_blocked() -> None:
    """Verify counter-trend breakout is rejected by H4 regime master gate."""
    strategy = VolatilityBreakoutStrategy()

    # 1. Bullish breakout with Bearish H4 regime
    h4_bearish = _create_h4_dataframe("bearish")
    m15_bullish = _create_m15_dataframe(breakout_type="bullish", expansion=True)
    sig_bull_blocked = strategy.evaluate_signal(
        m15_df=m15_bullish, h4_df=h4_bearish
    )
    assert sig_bull_blocked.signal_type == SignalType.NO_SIGNAL
    assert sig_bull_blocked.reason == "Counter-trend breakout blocked by H4 regime"

    # 2. Bearish breakout with Bullish H4 regime
    h4_bullish = _create_h4_dataframe("bullish")
    m15_bearish = _create_m15_dataframe(breakout_type="bearish", expansion=True)
    sig_bear_blocked = strategy.evaluate_signal(
        m15_df=m15_bearish, h4_df=h4_bullish
    )
    assert sig_bear_blocked.signal_type == SignalType.NO_SIGNAL
    assert sig_bear_blocked.reason == "Counter-trend breakout blocked by H4 regime"


def test_volatility_expansion_filter() -> None:
    """Verify breakout is rejected if candle bar range < 1.2 * ATR."""
    strategy = VolatilityBreakoutStrategy()
    h4_bullish = _create_h4_dataframe("bullish")

    # M15 breakout without volatility expansion (small candle range)
    m15_small_candle = _create_m15_dataframe(
        breakout_type="bullish", expansion=False
    )
    sig = strategy.evaluate_signal(m15_df=m15_small_candle, h4_df=h4_bullish)

    assert sig.signal_type == SignalType.NO_SIGNAL
    assert sig.h4_regime == MarketRegime.TRENDING_BULLISH
    assert sig.reason == "ATR expansion not met"


def test_insufficient_data_fail_safe() -> None:
    """Verify graceful fail-safe on empty or insufficient length DataFrames."""
    strategy = VolatilityBreakoutStrategy()
    h4_valid = _create_h4_dataframe("bullish")
    m15_valid = _create_m15_dataframe(breakout_type="bullish", expansion=True)

    # 1. Empty DataFrames
    empty_df = pd.DataFrame(columns=["high", "low", "close"])
    sig_empty_m15 = strategy.evaluate_signal(m15_df=empty_df, h4_df=h4_valid)
    assert sig_empty_m15.signal_type == SignalType.NO_SIGNAL
    assert sig_empty_m15.reason == "Insufficient data"

    sig_empty_h4 = strategy.evaluate_signal(m15_df=m15_valid, h4_df=empty_df)
    assert sig_empty_h4.signal_type == SignalType.NO_SIGNAL
    assert sig_empty_h4.reason == "Insufficient data"

    # 2. Too few bars for M15 Donchian channel (<= 20 bars)
    m15_short = m15_valid.iloc[:15].copy()
    sig_short_m15 = strategy.evaluate_signal(m15_df=m15_short, h4_df=h4_valid)
    assert sig_short_m15.signal_type == SignalType.NO_SIGNAL
    assert sig_short_m15.reason == "Insufficient data"

    # 3. Too few bars for H4 ADX (< 28 bars)
    h4_short = h4_valid.iloc[:20].copy()
    sig_short_h4 = strategy.evaluate_signal(m15_df=m15_valid, h4_df=h4_short)
    assert sig_short_h4.signal_type == SignalType.NO_SIGNAL
    assert sig_short_h4.reason == "Insufficient data"

    # 4. None input handling
    sig_none = strategy.evaluate_signal(  # type: ignore[arg-type]
        m15_df=None,  # pyright: ignore[reportArgumentType]
        h4_df=None,  # pyright: ignore[reportArgumentType]
    )
    assert sig_none.signal_type == SignalType.NO_SIGNAL


def test_trade_signal_frozen_immutability() -> None:
    """Verify TradeSignal dataclass is immutable (frozen)."""
    signal = TradeSignal(
        signal_type=SignalType.BUY,
        entry_price=2650.0,
        stop_loss=2635.0,
        take_profit=2680.0,
        atr_value=10.0,
        h4_regime=MarketRegime.TRENDING_BULLISH,
        reason="Test",
    )
    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        signal.entry_price = 2700.0  # type: ignore[misc]


def test_custom_parameters() -> None:
    """Verify custom parameters (multipliers, periods) are respected."""
    custom_strategy = VolatilityBreakoutStrategy(
        donchian_period=20,
        atr_period=14,
        atr_multiplier_sl=2.0,
        min_rr_ratio=3.0,
        atr_expansion_multiplier=1.5,
    )
    h4_df = _create_h4_dataframe("bullish")
    m15_df = _create_m15_dataframe(breakout_type="bullish", expansion=True)

    sig = custom_strategy.evaluate_signal(m15_df=m15_df, h4_df=h4_df)
    assert sig.signal_type == SignalType.BUY
    # SL distance = 2.0 * ATR
    expected_sl = sig.entry_price - (2.0 * sig.atr_value)
    assert sig.stop_loss == pytest.approx(expected_sl)
    # TP distance = 3.0 * (2.0 * ATR)
    expected_tp = sig.entry_price + (3.0 * 2.0 * sig.atr_value)
    assert sig.take_profit == pytest.approx(expected_tp)
    rr_ratio = (sig.take_profit - sig.entry_price) / (
        sig.entry_price - sig.stop_loss
    )
    assert rr_ratio == pytest.approx(3.0, rel=1e-5)
