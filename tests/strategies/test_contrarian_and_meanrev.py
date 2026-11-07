"""Unit tests for Positioning Contrarian (REQ-STR-004) and Mean-Reversion (REQ-STR-006).

Module: tests.strategies.test_contrarian_and_meanrev
Responsibility: Deterministic test suite covering retail sentiment crowding,
Donchian breakdown/breakout triggers, H4 ranging regime gating, Bollinger mean reversion,
Wilder RSI filters, and strict R:R >= 2.0 invariant verification.
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportAttributeAccessIssue=false
from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from engine.analysis_engine.python.indicators import MarketRegime
from engine.analysis_engine.python.types import OandaSentimentRatio
from instruments.xauusd.strategies.mean_reversion import (
    MeanReversionRangingStrategy,
    SignalType,
)
from instruments.xauusd.strategies.positioning_contrarian import (
    PositioningContrarianStrategy,
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


def _create_contrarian_m15_dataframe(action: str = "none", bars: int = 25) -> pd.DataFrame:
    """Create deterministic M15 DataFrame for Donchian breakout/breakdown."""
    high = [2650.0] * (bars - 1)
    low = [2640.0] * (bars - 1)
    close = [2645.0] * (bars - 1)

    if action == "breakdown":
        # Close penetrates Donchian lower band (< 2640.0)
        high.append(2642.0)
        low.append(2630.0)
        close.append(2635.0)
    elif action == "breakout":
        # Close penetrates Donchian upper band (> 2650.0)
        high.append(2658.0)
        low.append(2648.0)
        close.append(2655.0)
    else:
        # Inside channel
        high.append(2648.0)
        low.append(2642.0)
        close.append(2645.0)

    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": [100] * bars,
        }
    )


def _create_mean_reversion_m15_dataframe(
    condition: str = "neutral",
    insufficient_rr: bool = False,
) -> pd.DataFrame:
    """Create deterministic M15 DataFrame for Mean Reversion testing."""
    # 20 bars oscillation around 2600.0
    close_prices = [2600.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(20)]

    if condition == "overbought":
        # 5 bars advancing sharply to trigger RSI >= 70 and High >= Upper Band
        close_prices.extend([2605.0, 2610.0, 2616.0, 2622.0, 2630.0])
        high_prices = [c + 2.0 for c in close_prices]
        if insufficient_rr:
            # Low spikes drastically on the last bar, ballooning ATR and making R:R < 2.0
            low_prices = [c - 2.0 for c in close_prices[:-1]] + [2550.0]
        else:
            low_prices = [c - 2.0 for c in close_prices]
    elif condition == "oversold":
        # 5 bars dropping sharply to trigger RSI <= 30 and Low <= Lower Band
        close_prices.extend([2595.0, 2590.0, 2584.0, 2578.0, 2570.0])
        high_prices = [c + 2.0 for c in close_prices]
        if insufficient_rr:
            # High spikes drastically, ballooning ATR
            high_prices = [c + 2.0 for c in close_prices[:-1]] + [2650.0]
            low_prices = [c - 2.0 for c in close_prices]
        else:
            low_prices = [c - 2.0 for c in close_prices]
    else:
        # 5 bars continuing gentle oscillation
        close_prices.extend([2600.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(5)])
        high_prices = [c + 2.0 for c in close_prices]
        low_prices = [c - 2.0 for c in close_prices]

    return pd.DataFrame(
        {
            "open": close_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "tick_volume": [100] * len(close_prices),
        }
    )


# ------------------------------------------------------------------------------
# Test 1: Positioning Contrarian - Extreme Long Crowding Triggers Sell
# ------------------------------------------------------------------------------
def test_contrarian_extreme_long_crowding_triggers_sell() -> None:
    """Verify SELL signal when Retail Long > 75% and M15 Donchian breakdown occurs (REQ-STR-004)."""
    m15_df = _create_contrarian_m15_dataframe(action="breakdown")
    sentiment = OandaSentimentRatio(
        timestamp_utc="2026-01-01T00:00:00Z",
        long_position_pct=80.0,
        short_position_pct=20.0,
        long_order_pct=50.0,
        short_order_pct=50.0,
        skew_ratio=0.6,
    )

    strategy = PositioningContrarianStrategy()
    signal = strategy.evaluate_signal(m15_df=m15_df, sentiment=sentiment)

    assert signal.signal_type == SignalType.SELL
    assert signal.entry_price == 2635.0
    assert signal.atr_value > 0.0

    # Stop loss must be entry + 1.5 * ATR
    expected_sl = signal.entry_price + (1.5 * signal.atr_value)
    assert signal.stop_loss == pytest.approx(expected_sl)

    # Take profit must be entry - 2.0 * (1.5 * ATR)
    expected_tp = signal.entry_price - (2.0 * 1.5 * signal.atr_value)
    assert signal.take_profit == pytest.approx(expected_tp)

    # Reward-to-Risk ratio must be >= 2.0
    rr_ratio = (signal.entry_price - signal.take_profit) / (
        signal.stop_loss - signal.entry_price
    )
    assert rr_ratio == pytest.approx(2.0, rel=1e-5)
    assert "retail long crowding" in signal.reason


# ------------------------------------------------------------------------------
# Test 2: Positioning Contrarian - Extreme Short Crowding Triggers Buy
# ------------------------------------------------------------------------------
def test_contrarian_extreme_short_crowding_triggers_buy() -> None:
    """Verify BUY signal when Retail Short > 75% and M15 Donchian breakout occurs (REQ-STR-004)."""
    m15_df = _create_contrarian_m15_dataframe(action="breakout")
    sentiment = OandaSentimentRatio(
        timestamp_utc="2026-01-01T00:00:00Z",
        long_position_pct=20.0,
        short_position_pct=80.0,
        long_order_pct=50.0,
        short_order_pct=50.0,
        skew_ratio=-0.6,
    )

    strategy = PositioningContrarianStrategy()
    signal = strategy.evaluate_signal(m15_df=m15_df, sentiment=sentiment)

    assert signal.signal_type == SignalType.BUY
    assert signal.entry_price == 2655.0
    assert signal.atr_value > 0.0

    # Stop loss must be entry - 1.5 * ATR
    expected_sl = signal.entry_price - (1.5 * signal.atr_value)
    assert signal.stop_loss == pytest.approx(expected_sl)

    # Take profit must be entry + 2.0 * (1.5 * ATR)
    expected_tp = signal.entry_price + (2.0 * 1.5 * signal.atr_value)
    assert signal.take_profit == pytest.approx(expected_tp)

    # Reward-to-Risk ratio must be >= 2.0
    rr_ratio = (signal.take_profit - signal.entry_price) / (
        signal.entry_price - signal.stop_loss
    )
    assert rr_ratio == pytest.approx(2.0, rel=1e-5)
    assert "retail short crowding" in signal.reason


# ------------------------------------------------------------------------------
# Test 3: Positioning Contrarian - Neutral Sentiment Returns NO_SIGNAL
# ------------------------------------------------------------------------------
def test_contrarian_neutral_sentiment_no_signal() -> None:
    """Verify NO_SIGNAL when retail sentiment is neutral (55% long) despite breakdown."""
    m15_df = _create_contrarian_m15_dataframe(action="breakdown")
    sentiment = OandaSentimentRatio(
        timestamp_utc="2026-01-01T00:00:00Z",
        long_position_pct=55.0,
        short_position_pct=45.0,
        long_order_pct=50.0,
        short_order_pct=50.0,
        skew_ratio=0.1,
    )

    strategy = PositioningContrarianStrategy()
    signal = strategy.evaluate_signal(m15_df=m15_df, sentiment=sentiment)

    assert signal.signal_type == SignalType.NO_SIGNAL
    assert signal.entry_price == 0.0
    assert signal.reason == "Neutral sentiment"


# ------------------------------------------------------------------------------
# Test 4: Mean Reversion - Trending Regime Blocked
# ------------------------------------------------------------------------------
def test_mean_reversion_trending_regime_blocked() -> None:
    """Verify H4 BULLISH_TRENDING or BEARISH_TRENDING blocks mean reversion with REGIME_NOT_RANGING."""
    m15_df = _create_mean_reversion_m15_dataframe(condition="overbought")
    strategy = MeanReversionRangingStrategy()

    # 1. Blocked via enum
    sig_bull = strategy.evaluate_signal(
        m15_df=m15_df, h4_regime=MarketRegime.TRENDING_BULLISH
    )
    assert sig_bull.signal_type == SignalType.NO_SIGNAL
    assert sig_bull.reason == "REGIME_NOT_RANGING"

    # 2. Blocked via string literal "BULLISH_TRENDING"
    sig_str = strategy.evaluate_signal(
        m15_df=m15_df, h4_regime="BULLISH_TRENDING"
    )
    assert sig_str.signal_type == SignalType.NO_SIGNAL
    assert sig_str.reason == "REGIME_NOT_RANGING"

    # 3. Blocked via trending H4 DataFrame
    h4_bull = _create_h4_dataframe(regime="bullish")
    sig_df = strategy.evaluate_signal(m15_df=m15_df, h4_df=h4_bull)
    assert sig_df.signal_type == SignalType.NO_SIGNAL
    assert sig_df.reason == "REGIME_NOT_RANGING"


# ------------------------------------------------------------------------------
# Test 5: Mean Reversion - Overbought Sell Signal
# ------------------------------------------------------------------------------
def test_mean_reversion_overbought_sell_signal() -> None:
    """Verify SELL signal when H4 is RANGING + Price >= Upper Band + RSI >= 70 (REQ-STR-006)."""
    m15_df = _create_mean_reversion_m15_dataframe(condition="overbought")
    strategy = MeanReversionRangingStrategy()

    signal = strategy.evaluate_signal(
        m15_df=m15_df, h4_regime=MarketRegime.RANGING
    )

    assert signal.signal_type == SignalType.SELL
    assert signal.entry_price == 2630.0
    assert signal.h4_regime == MarketRegime.RANGING

    # SL must be entry + 1.5 * ATR
    expected_sl = signal.entry_price + (1.5 * signal.atr_value)
    assert signal.stop_loss == pytest.approx(expected_sl)

    # TP must be SMA 20 level
    close_series = pd.Series(m15_df["close"], dtype=float)
    expected_tp = float(pd.Series(close_series.rolling(window=20).mean()).iloc[-1])
    assert signal.take_profit == pytest.approx(expected_tp)

    # R:R must be >= 2.0
    rr_ratio = (signal.entry_price - signal.take_profit) / (
        signal.stop_loss - signal.entry_price
    )
    assert rr_ratio >= 2.0
    assert "Mean-reversion sell confirmed" in signal.reason


# ------------------------------------------------------------------------------
# Test 6: Mean Reversion - Oversold Buy Signal
# ------------------------------------------------------------------------------
def test_mean_reversion_oversold_buy_signal() -> None:
    """Verify BUY signal when H4 is RANGING + Price <= Lower Band + RSI <= 30 (REQ-STR-006)."""
    m15_df = _create_mean_reversion_m15_dataframe(condition="oversold")
    strategy = MeanReversionRangingStrategy()

    signal = strategy.evaluate_signal(
        m15_df=m15_df, h4_regime=MarketRegime.RANGING
    )

    assert signal.signal_type == SignalType.BUY
    assert signal.entry_price == 2570.0
    assert signal.h4_regime == MarketRegime.RANGING

    # SL must be entry - 1.5 * ATR
    expected_sl = signal.entry_price - (1.5 * signal.atr_value)
    assert signal.stop_loss == pytest.approx(expected_sl)

    # TP must be SMA 20 level
    close_series = pd.Series(m15_df["close"], dtype=float)
    expected_tp = float(pd.Series(close_series.rolling(window=20).mean()).iloc[-1])
    assert signal.take_profit == pytest.approx(expected_tp)

    # R:R must be >= 2.0
    rr_ratio = (signal.take_profit - signal.entry_price) / (
        signal.entry_price - signal.stop_loss
    )
    assert rr_ratio >= 2.0
    assert "Mean-reversion buy confirmed" in signal.reason


# ------------------------------------------------------------------------------
# Test 7: Mean Reversion - Insufficient R:R Rejected
# ------------------------------------------------------------------------------
def test_mean_reversion_insufficient_rr_rejected() -> None:
    """Verify rejection when Reward-to-Risk ratio < 2.0 with REWARD_RISK_RATIO_BELOW_MINIMUM."""
    m15_df = _create_mean_reversion_m15_dataframe(
        condition="overbought", insufficient_rr=True
    )
    strategy = MeanReversionRangingStrategy()

    signal = strategy.evaluate_signal(
        m15_df=m15_df, h4_regime=MarketRegime.RANGING
    )

    assert signal.signal_type == SignalType.NO_SIGNAL
    assert signal.entry_price == 0.0
    assert signal.reason == "REWARD_RISK_RATIO_BELOW_MINIMUM"


# ------------------------------------------------------------------------------
# Test 8: TradeSignal Immutability
# ------------------------------------------------------------------------------
def test_trade_signal_immutability() -> None:
    """Verify TradeSignal emitted by both strategies is frozen and immutable."""
    # From Contrarian
    strat_c = PositioningContrarianStrategy()
    m15_c = _create_contrarian_m15_dataframe(action="breakdown")
    sent = OandaSentimentRatio(
        timestamp_utc="2026-01-01T00:00:00Z",
        long_position_pct=80.0,
        short_position_pct=20.0,
        long_order_pct=50.0,
        short_order_pct=50.0,
        skew_ratio=0.6,
    )
    sig_c = strat_c.evaluate_signal(m15_df=m15_c, sentiment=sent)

    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        sig_c.entry_price = 2700.0  # type: ignore[misc]

    # From Mean Reversion
    strat_mr = MeanReversionRangingStrategy()
    m15_mr = _create_mean_reversion_m15_dataframe(condition="overbought")
    sig_mr = strat_mr.evaluate_signal(
        m15_df=m15_mr, h4_regime=MarketRegime.RANGING
    )

    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        sig_mr.take_profit = 2500.0  # type: ignore[misc]
