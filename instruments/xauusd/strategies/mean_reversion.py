"""Strategy Category 4: Mean-Reversion in Ranging Regime on M15.

Module: instruments.xauusd.strategies.mean_reversion
Responsibility: M15 mean reversion with adaptive volatility bands (Bollinger)
and Wilder RSI confirmation in confirmed H4 ranging market regime.
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

import numpy as np
import pandas as pd

from engine.analysis_engine.python.indicators import (
    MarketRegime,
    calculate_adx,
    calculate_atr,
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
    "MeanReversionRangingStrategy",
    "SignalType",
    "TradeSignal",
    "calculate_bollinger_bands",
    "calculate_rsi",
    "calculate_sma",
]


def calculate_sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Calculate Simple Moving Average (SMA) over specified period."""
    return pd.Series(series.rolling(window=period).mean())


def calculate_bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands (middle SMA, upper band, lower band).

    Returns tuple of (sma, upper_band, lower_band).
    """
    sma = calculate_sma(series, period=period)
    std = pd.Series(series.rolling(window=period).std(ddof=0))
    upper = pd.Series(sma + (num_std * std))
    lower = pd.Series(sma - (num_std * std))
    return sma, upper, lower


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI) using Wilder's smoothing."""
    res = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) <= period:
        return res

    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    # Initial average gain/loss over first `period` diff bars (indices 1 to period)
    init_gain = float(gain.iloc[1 : period + 1].mean())
    init_loss = float(loss.iloc[1 : period + 1].mean())

    avg_gain = init_gain
    avg_loss = init_loss

    if avg_loss == 0.0:
        res.iloc[period] = 100.0 if avg_gain > 0.0 else 50.0
    else:
        rs = avg_gain / avg_loss
        res.iloc[period] = 100.0 - (100.0 / (1.0 + rs))

    for t in range(period + 1, len(series)):
        g = float(gain.iloc[t])
        l = float(loss.iloc[t])
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period

        if avg_loss == 0.0:
            res.iloc[t] = 100.0 if avg_gain > 0.0 else 50.0
        elif avg_gain == 0.0:
            res.iloc[t] = 0.0
        else:
            rs = avg_gain / avg_loss
            res.iloc[t] = 100.0 - (100.0 / (1.0 + rs))

    return res


class MeanReversionRangingStrategy:
    """M15 Mean-Reversion Strategy in Confirmed Ranging Regime (REQ-STR-006)."""

    def __init__(
        self,
        sma_period: int = 20,
        bb_std_dev: float = 2.0,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        atr_period: int = 14,
        atr_multiplier_sl: float = 1.5,
        min_rr_ratio: float = 2.0,
        **kwargs: Any,
    ) -> None:
        self.sma_period = sma_period
        self.bb_std_dev = float(
            kwargs.get("bb_multiplier", kwargs.get("std_dev", bb_std_dev))
        )
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.atr_period = atr_period
        self.atr_multiplier_sl = atr_multiplier_sl
        self.min_rr_ratio = min_rr_ratio

    def evaluate_signal(
        self,
        m15_df: pd.DataFrame,
        h4_df: pd.DataFrame | None = None,
        h4_regime: MarketRegime | str | None = None,
    ) -> TradeSignal:
        """Evaluate latest M15 bar under confirmed H4 ranging regime.

        Hard Regime Gate: Rejects any non-RANGING regime with 'REGIME_NOT_RANGING'.
        R:R Validation Gate: Rejects any setup with R:R < 2.0 with 'REWARD_RISK_RATIO_BELOW_MINIMUM'.
        """
        # 1. Resolve H4 market regime
        current_regime: MarketRegime | None = None
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

        # 2. Hard Regime Gate: Must be strictly MarketRegime.RANGING
        if current_regime != MarketRegime.RANGING:
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=current_regime or MarketRegime.RANGING,
                reason="REGIME_NOT_RANGING",
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
                h4_regime=MarketRegime.RANGING,
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
                h4_regime=MarketRegime.RANGING,
                reason="Insufficient data: missing required OHLC columns",
            )

        min_m15_bars = (
            max(self.sma_period, self.rsi_period, self.atr_period) + 1
        )
        if len(m15_df) < min_m15_bars:
            return TradeSignal(
                signal_type=SignalType.NO_SIGNAL,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                atr_value=0.0,
                h4_regime=MarketRegime.RANGING,
                reason="Insufficient data",
            )

        # 4. Calculate Indicators (Bollinger, RSI, ATR)
        m15_high = pd.Series(m15_df["high"], dtype=float)
        m15_low = pd.Series(m15_df["low"], dtype=float)
        m15_close = pd.Series(m15_df["close"], dtype=float)

        sma_series, upper_series, lower_series = calculate_bollinger_bands(
            m15_close, period=self.sma_period, num_std=self.bb_std_dev
        )
        rsi_series = calculate_rsi(m15_close, period=self.rsi_period)
        atr_series = calculate_atr(
            m15_high, m15_low, m15_close, period=self.atr_period
        )

        high_last = float(m15_high.iloc[-1])
        low_last = float(m15_low.iloc[-1])
        close_last = float(m15_close.iloc[-1])
        sma_val = float(sma_series.iloc[-1])
        upper_val = float(upper_series.iloc[-1])
        lower_val = float(lower_series.iloc[-1])
        rsi_val = float(rsi_series.iloc[-1])
        atr_val = float(atr_series.iloc[-1])

        if (
            math.isnan(high_last)
            or math.isnan(low_last)
            or math.isnan(close_last)
            or math.isnan(sma_val)
            or math.isnan(upper_val)
            or math.isnan(lower_val)
            or math.isnan(rsi_val)
            or math.isnan(atr_val)
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

        # 5. Evaluate Mean Reversion Triggers
        is_sell_setup = (high_last >= upper_val) and (
            rsi_val >= self.rsi_overbought
        )
        is_buy_setup = (low_last <= lower_val) and (
            rsi_val <= self.rsi_oversold
        )

        sl_distance = self.atr_multiplier_sl * atr_val

        # SELL (Overbought Reversion to SMA 20)
        if is_sell_setup and not is_buy_setup:
            entry_price = close_last
            target_tp = sma_val
            stop_loss = entry_price + sl_distance
            reward = entry_price - target_tp
            risk = sl_distance

            # R:R Validation Gate
            if risk <= 0.0 or reward <= 0.0 or ((reward / risk) < (self.min_rr_ratio - 1e-9)):
                return TradeSignal(
                    signal_type=SignalType.NO_SIGNAL,
                    entry_price=0.0,
                    stop_loss=0.0,
                    take_profit=0.0,
                    atr_value=atr_val,
                    h4_regime=MarketRegime.RANGING,
                    reason="REWARD_RISK_RATIO_BELOW_MINIMUM",
                )

            return TradeSignal(
                signal_type=SignalType.SELL,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=target_tp,
                atr_value=atr_val,
                h4_regime=MarketRegime.RANGING,
                reason="Mean-reversion sell confirmed: overbought upper band rejection",
            )

        # BUY (Oversold Reversion to SMA 20)
        if is_buy_setup and not is_sell_setup:
            entry_price = close_last
            target_tp = sma_val
            stop_loss = entry_price - sl_distance
            reward = target_tp - entry_price
            risk = sl_distance

            # R:R Validation Gate
            if risk <= 0.0 or reward <= 0.0 or ((reward / risk) < (self.min_rr_ratio - 1e-9)):
                return TradeSignal(
                    signal_type=SignalType.NO_SIGNAL,
                    entry_price=0.0,
                    stop_loss=0.0,
                    take_profit=0.0,
                    atr_value=atr_val,
                    h4_regime=MarketRegime.RANGING,
                    reason="REWARD_RISK_RATIO_BELOW_MINIMUM",
                )

            return TradeSignal(
                signal_type=SignalType.BUY,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=target_tp,
                atr_value=atr_val,
                h4_regime=MarketRegime.RANGING,
                reason="Mean-reversion buy confirmed: oversold lower band rejection",
            )

        # No setup detected or conflicting
        return TradeSignal(
            signal_type=SignalType.NO_SIGNAL,
            entry_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            atr_value=atr_val,
            h4_regime=MarketRegime.RANGING,
            reason="No mean reversion setup detected",
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
        signal = self.evaluate_signal(m15_df=m15_df, h4_df=h4_df)
        return [signal] if signal.signal_type != SignalType.NO_SIGNAL else []
