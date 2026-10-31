"""Strategy Category 1: Volatility Breakout (ATR expansion) on M15 with H4 Regime Filter.

Module: instruments.xauusd.strategies.volatility_breakout
Responsibility: M15 Donchian channel breakout strategy with ATR volatility expansion
filter and H4 market regime direction gate.
Architecture: Single Source of Truth indicators, zero lookahead bias, strict R:R bracket.
"""
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnnecessaryComparison=false
# pyright: reportUnnecessaryIsInstance=false
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from engine.analysis_engine.python.indicators import (
    MarketRegime,
    calculate_adx,
    calculate_atr,
    calculate_donchian_channel,
    calculate_ema,
    classify_h4_regime,
)


class SignalType(str, Enum):
    """Trading signal classification."""

    BUY = "BUY"
    SELL = "SELL"
    NO_SIGNAL = "NO_SIGNAL"


@dataclass(frozen=True)
class TradeSignal:
    """Immutable trade signal emitted by the volatility breakout strategy."""

    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float
    atr_value: float
    h4_regime: MarketRegime
    reason: str


class VolatilityBreakoutStrategy:
    """M15 Volatility Breakout Strategy with H4 Market Regime Filter."""

    def __init__(
        self,
        donchian_period: int = 20,
        atr_period: int = 14,
        atr_multiplier_sl: float = 1.5,
        min_rr_ratio: float = 2.0,
        atr_expansion_multiplier: float = 1.2,
    ) -> None:
        self.donchian_period = donchian_period
        self.atr_period = atr_period
        self.atr_multiplier_sl = atr_multiplier_sl
        self.min_rr_ratio = min_rr_ratio
        self.atr_expansion_multiplier = atr_expansion_multiplier

    def evaluate_signal(
        self,
        m15_df: pd.DataFrame,
        h4_df: pd.DataFrame,
    ) -> TradeSignal:
        """Evaluate the latest bar of M15 and H4 data to generate a TradeSignal.

        m15_df and h4_df must contain at least ['high', 'low', 'close'] columns.
        """
        # 1. Fail-safe validation for input DataFrames
        if (
            m15_df is None
            or h4_df is None
            or not isinstance(m15_df, pd.DataFrame)
            or not isinstance(h4_df, pd.DataFrame)
            or m15_df.empty
            or h4_df.empty
        ):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=MarketRegime.RANGING,
                reason="Insufficient data",
            )

        required_cols = ("high", "low", "close")
        if not all(col in m15_df.columns for col in required_cols) or not all(
            col in h4_df.columns for col in required_cols
        ):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=MarketRegime.RANGING,
                reason="Insufficient data: missing required OHLC columns",
            )

        min_m15_bars = max(self.donchian_period, self.atr_period) + 1
        if len(m15_df) < min_m15_bars or len(h4_df) < 28:
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=MarketRegime.RANGING,
                reason="Insufficient data",
            )

        # 2. Evaluate H4 Regime using ADX(14), EMA(50), and EMA(200)
        h4_high = pd.Series(h4_df["high"], dtype=float)
        h4_low = pd.Series(h4_df["low"], dtype=float)
        h4_close = pd.Series(h4_df["close"], dtype=float)

        _, _, _, adx_series = calculate_adx(h4_high, h4_low, h4_close, period=14)
        ema_fast_series = calculate_ema(h4_close, period=50)
        ema_slow_series = calculate_ema(h4_close, period=200)

        adx_val = float(adx_series.iloc[-1])
        ema_fast_val = float(ema_fast_series.iloc[-1])
        ema_slow_val = float(ema_slow_series.iloc[-1])

        if math.isnan(adx_val) or math.isnan(ema_fast_val) or math.isnan(ema_slow_val):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=MarketRegime.RANGING,
                reason="Insufficient data",
            )

        h4_regime = classify_h4_regime(
            adx=adx_val, ema_fast=ema_fast_val, ema_slow=ema_slow_val
        )

        # 3. Calculate M15 Donchian Channel and ATR
        m15_high = pd.Series(m15_df["high"], dtype=float)
        m15_low = pd.Series(m15_df["low"], dtype=float)
        m15_close = pd.Series(m15_df["close"], dtype=float)

        upper_series, _, lower_series = calculate_donchian_channel(
            m15_high, m15_low, period=self.donchian_period
        )
        atr_series = calculate_atr(
            m15_high, m15_low, m15_close, period=self.atr_period
        )

        upper_val = float(upper_series.iloc[-1])
        lower_val = float(lower_series.iloc[-1])
        atr_val = float(atr_series.iloc[-1])
        close_last = float(m15_close.iloc[-1])
        high_last = float(m15_high.iloc[-1])
        low_last = float(m15_low.iloc[-1])

        if (
            math.isnan(upper_val)
            or math.isnan(lower_val)
            or math.isnan(atr_val)
            or math.isnan(close_last)
            or math.isnan(high_last)
            or math.isnan(low_last)
        ):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=h4_regime,
                reason="Insufficient data",
            )

        # 4. H4 Regime Gate: Block RANGING and TRANSITIONING
        if h4_regime in (MarketRegime.RANGING, MarketRegime.TRANSITIONING):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=atr_val,
                h4_regime=h4_regime,
                reason="Blocked by H4 regime",
            )

        # 5. Check M15 Donchian Breakout
        is_bullish_breakout = close_last > upper_val
        is_bearish_breakout = close_last < lower_val

        if not is_bullish_breakout and not is_bearish_breakout:
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=atr_val,
                h4_regime=h4_regime,
                reason="No breakout detected",
            )

        # 6. Counter-trend filter: breakout direction must match H4 trending regime
        if (
            is_bullish_breakout and h4_regime != MarketRegime.TRENDING_BULLISH
        ) or (
            is_bearish_breakout and h4_regime != MarketRegime.TRENDING_BEARISH
        ):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=atr_val,
                h4_regime=h4_regime,
                reason="Counter-trend breakout blocked by H4 regime",
            )

        # 7. Volatility Expansion Confirmation: High - Low >= multiplier * ATR
        bar_range = high_last - low_last
        if bar_range < (self.atr_expansion_multiplier * atr_val):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=atr_val,
                h4_regime=h4_regime,
                reason="ATR expansion not met",
            )

        # 8. Valid Breakout Signal Generation with SL and TP
        sl_distance = self.atr_multiplier_sl * atr_val
        tp_distance = self.min_rr_ratio * sl_distance

        if is_bullish_breakout:
            stop_loss = close_last - sl_distance
            take_profit = close_last + tp_distance
            return TradeSignal(
                signal_type=SignalType.BUY,
                entry_price=close_last,
                stop_loss=stop_loss,
                take_profit=take_profit,
                atr_value=atr_val,
                h4_regime=h4_regime,
                reason="Bullish breakout confirmed",
            )

        stop_loss = close_last + sl_distance
        take_profit = close_last - tp_distance
        return TradeSignal(
            signal_type=SignalType.SELL,
            entry_price=close_last,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr_value=atr_val,
            h4_regime=h4_regime,
            reason="Bearish breakout confirmed",
        )
