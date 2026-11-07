"""Strategy Category 2: Positioning-based Contrarian on M15.

Module: instruments.xauusd.strategies.positioning_contrarian
Responsibility: Contrarian execution based on OANDA retail order/position book
sentiment crowding combined with local Donchian channel breakout/breakdown.
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
from typing import Any

import pandas as pd

from engine.analysis_engine.python.indicators import (
    MarketRegime,
    calculate_adx,
    calculate_atr,
    calculate_donchian_channel,
    calculate_ema,
    classify_h4_regime,
)
from engine.analysis_engine.python.types import (
    CandleDict,
    MacroFeatures,
    OandaSentimentRatio,
)
from instruments.xauusd.strategies.volatility_breakout import SignalType, TradeSignal

__all__ = [
    "MarketRegime",
    "PositioningContrarianStrategy",
    "SignalType",
    "TradeSignal",
]


class PositioningContrarianStrategy:
    """M15 Positioning Contrarian Strategy based on OANDA Order/Position Book (REQ-STR-004)."""

    def __init__(
        self,
        donchian_period: int = 20,
        atr_period: int = 14,
        atr_multiplier_sl: float = 1.5,
        min_rr_ratio: float = 2.0,
        extreme_sentiment_threshold: float = 75.0,
        **kwargs: Any,
    ) -> None:
        self.donchian_period = donchian_period
        self.atr_period = atr_period
        self.atr_multiplier_sl = atr_multiplier_sl
        self.min_rr_ratio = min_rr_ratio
        self.extreme_sentiment_threshold = float(
            kwargs.get("sentiment_threshold", extreme_sentiment_threshold)
        )

    def evaluate_signal(
        self,
        m15_df: pd.DataFrame,
        sentiment: OandaSentimentRatio | dict[str, Any] | None = None,
        h4_df: pd.DataFrame | None = None,
        h4_regime: MarketRegime | str | None = None,
    ) -> TradeSignal:
        """Evaluate latest M15 bar and sentiment ratio to generate a contrarian TradeSignal.

        m15_df must contain ['high', 'low', 'close'] columns.
        """
        # Resolve H4 market regime if provided
        current_regime = MarketRegime.RANGING
        if h4_regime is not None:
            if isinstance(h4_regime, str):
                regime_map = {
                    "BULLISH_TRENDING": MarketRegime.TRENDING_BULLISH,
                    "TRENDING_BULLISH": MarketRegime.TRENDING_BULLISH,
                    "BEARISH_TRENDING": MarketRegime.TRENDING_BEARISH,
                    "TRENDING_BEARISH": MarketRegime.TRENDING_BEARISH,
                    "RANGING": MarketRegime.RANGING,
                    "TRANSITIONING": MarketRegime.TRANSITIONING,
                }
                current_regime = regime_map.get(
                    h4_regime.upper(), MarketRegime.RANGING
                )
            else:
                current_regime = h4_regime
        elif (
            h4_df is not None
            and isinstance(h4_df, pd.DataFrame)
            and len(h4_df) >= 28
            and all(col in h4_df.columns for col in ("high", "low", "close"))
        ):
            h4_h = pd.Series(h4_df["high"], dtype=float)
            h4_l = pd.Series(h4_df["low"], dtype=float)
            h4_c = pd.Series(h4_df["close"], dtype=float)
            _, _, _, adx_series = calculate_adx(h4_h, h4_l, h4_c, period=14)
            ema_fast = calculate_ema(h4_c, period=50)
            ema_slow = calculate_ema(h4_c, period=200)
            adx_val = float(adx_series.iloc[-1])
            ef_val = float(ema_fast.iloc[-1])
            es_val = float(ema_slow.iloc[-1])
            if not (math.isnan(adx_val) or math.isnan(ef_val) or math.isnan(es_val)):
                current_regime = classify_h4_regime(
                    adx=adx_val, ema_fast=ef_val, ema_slow=es_val
                )

        # 1. Validate sentiment input
        if sentiment is None:
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=current_regime,
                reason="Missing sentiment data",
            )

        if isinstance(sentiment, dict):
            long_pct = float(sentiment.get("long_position_pct", 0.0))
            short_pct = float(sentiment.get("short_position_pct", 0.0))
        else:
            long_pct = float(getattr(sentiment, "long_position_pct", 0.0))
            short_pct = float(getattr(sentiment, "short_position_pct", 0.0))

        # 2. Check if sentiment is in neutral zone
        if (
            long_pct <= self.extreme_sentiment_threshold
            and short_pct <= self.extreme_sentiment_threshold
        ):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=current_regime,
                reason="Neutral sentiment",
            )

        # 3. Validate M15 DataFrame
        if (
            m15_df is None
            or not isinstance(m15_df, pd.DataFrame)
            or m15_df.empty
        ):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=current_regime,
                reason="Insufficient data",
            )

        required_cols = ("high", "low", "close")
        if not all(col in m15_df.columns for col in required_cols):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=current_regime,
                reason="Insufficient data: missing required OHLC columns",
            )

        min_m15_bars = max(self.donchian_period, self.atr_period) + 1
        if len(m15_df) < min_m15_bars:
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=current_regime,
                reason="Insufficient data",
            )

        # 4. Calculate Donchian Channel and ATR
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

        if (
            math.isnan(upper_val)
            or math.isnan(lower_val)
            or math.isnan(atr_val)
            or math.isnan(close_last)
        ):
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=current_regime,
                reason="Insufficient data",
            )

        # 5. Evaluate Contrarian Trigger Conditions
        sl_distance = self.atr_multiplier_sl * atr_val
        tp_distance = self.min_rr_ratio * sl_distance

        # Long retail over-crowded (> 75%) -> Contrarian Short on Donchian breakdown
        if long_pct > self.extreme_sentiment_threshold:
            if close_last < lower_val:
                return TradeSignal(
                    signal_type=SignalType.SELL,
                    entry_price=close_last,
                    stop_loss=close_last + sl_distance,
                    take_profit=close_last - tp_distance,
                    atr_value=atr_val,
                    h4_regime=current_regime,
                    reason="Contrarian sell confirmed: retail long crowding + support breakdown",
                )
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=atr_val,
                h4_regime=current_regime,
                reason="No breakdown detected",
            )

        # Short retail over-crowded (> 75%) -> Contrarian Long on Donchian breakout
        if short_pct > self.extreme_sentiment_threshold:
            if close_last > upper_val:
                return TradeSignal(
                    signal_type=SignalType.BUY,
                    entry_price=close_last,
                    stop_loss=close_last - sl_distance,
                    take_profit=close_last + tp_distance,
                    atr_value=atr_val,
                    h4_regime=current_regime,
                    reason="Contrarian buy confirmed: retail short crowding + resistance breakout",
                )
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=atr_val,
                h4_regime=current_regime,
                reason="No breakout detected",
            )

        # Fallback (should not be reached due to step 2 check)
        return TradeSignal(
            signal_type=SignalType.NO_SIGNAL,
            entry_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            atr_value=atr_val,
            h4_regime=current_regime,
            reason="Neutral sentiment",
        )

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: MacroFeatures | None = None,
        sentiment: OandaSentimentRatio | None = None,
    ) -> list[TradeSignal]:
        """Protocol conformance implementation for StrategyEvaluator."""
        m15_df = pd.DataFrame(m15_candles)
        h4_df = pd.DataFrame(h4_candles) if h4_candles else None
        signal = self.evaluate_signal(
            m15_df=m15_df, sentiment=sentiment, h4_df=h4_df
        )
        return [signal] if signal.signal_type != SignalType.NO_SIGNAL else []
