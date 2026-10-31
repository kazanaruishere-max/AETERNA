"""
Module: engine.analysis_engine.python.indicators
Responsibility: Technical indicators (Wilder ATR, ADX, EMA, Donchian) and H4 market regime classifier.
Owner: aeterna-quant
Tier: B
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

import math
from enum import Enum

import numpy as np
import pandas as pd


class MarketRegime(str, Enum):
    """Market regime classification for H4 timeframe continuum."""

    TRENDING_BULLISH = "TRENDING_BULLISH"
    TRENDING_BEARISH = "TRENDING_BEARISH"
    RANGING = "RANGING"
    TRANSITIONING = "TRANSITIONING"


def calculate_true_range(
    high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """Calculate True Range according to Wilder's original definition.

    TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|).
    For bar 0 (t=0): TR_0 = High_0 - Low_0.
    """
    hl = high - low
    prev_close = close.shift(1)
    hc = (high - prev_close).abs()
    lc = (low - prev_close).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    if len(tr) > 0:
        tr.iloc[0] = hl.iloc[0]
    return pd.Series(tr)


def wilder_smoothing(series: pd.Series, period: int = 14) -> pd.Series:
    """Recursive Wilder's Smoothing (RMA) with initial SMA.

    Initial value at first_valid + period - 1 is the SMA of first period bars.
    Subsequent values: WS_t = (WS_{t-1} * (period - 1) + X_t) / period.
    Values before initialization are NaN.
    """
    res = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < period:
        return res

    valid_mask = series.notna()
    if not bool(valid_mask.any()):
        return res

    first_valid_pos = int(np.argmax(valid_mask.to_numpy()))
    init_end_pos = first_valid_pos + period - 1
    if init_end_pos >= len(series):
        return res

    init_window = series.iloc[first_valid_pos : init_end_pos + 1]
    if bool(init_window.isna().any()):
        return res

    res.iloc[init_end_pos] = float(init_window.mean())

    for t in range(init_end_pos + 1, len(series)):
        val = float(series.iloc[t])
        if math.isnan(val):
            res.iloc[t] = np.nan
        else:
            prev = float(res.iloc[t - 1])
            if math.isnan(prev):
                res.iloc[t] = np.nan
            else:
                res.iloc[t] = (prev * (period - 1) + val) / period

    return res


def calculate_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Calculate Average True Range (ATR) using Wilder's Smoothing.

    Wilder 1978: initial accumulation starts from bar 2 (index 1) to bar 15 (index period)
    because bar 1 has no previous close.
    """
    tr = calculate_true_range(high, low, close)
    tr_calc = tr.copy()
    if len(tr_calc) > 0:
        tr_calc.iloc[0] = np.nan
    return wilder_smoothing(tr_calc, period)


def calculate_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Calculate Directional Indicators (+DI, -DI), DX, and ADX.

    Returns tuple of (plus_di, minus_di, dx, adx).
    """
    atr = calculate_atr(high, low, close, period)

    up_move = high.diff()
    down_move = -low.diff()

    cond_plus = (up_move > down_move) & (up_move > 0)
    cond_minus = (down_move > up_move) & (down_move > 0)

    plus_dm = up_move.where(cond_plus, 0.0)
    minus_dm = down_move.where(cond_minus, 0.0)

    if len(plus_dm) > 0:
        plus_dm.iloc[0] = np.nan
        minus_dm.iloc[0] = np.nan

    plus_dm_smooth = wilder_smoothing(plus_dm, period)
    minus_dm_smooth = wilder_smoothing(minus_dm, period)

    # Directional Indicators
    plus_di = (100.0 * (plus_dm_smooth / atr)).replace([np.inf, -np.inf], np.nan)
    minus_di = (100.0 * (minus_dm_smooth / atr)).replace([np.inf, -np.inf], np.nan)

    # Directional Index (DX) with fail-fast anti-silent-swallowing
    sum_di = plus_di + minus_di
    diff_di = (plus_di - minus_di).abs()

    dx = (100.0 * diff_di / sum_di).where(sum_di != 0.0, np.nan)
    dx = dx.replace([np.inf, -np.inf], np.nan)

    adx = wilder_smoothing(dx, period)

    return pd.Series(plus_di), pd.Series(minus_di), pd.Series(dx), pd.Series(adx)


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average (EMA) with span parameter."""
    return pd.Series(series.ewm(span=period, adjust=False).mean())


def calculate_donchian_channel(
    high: pd.Series, low: pd.Series, period: int = 20
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Donchian Channel with shift(1) to eliminate lookahead bias.

    Returns tuple of (upper, middle, lower).
    """
    upper = pd.Series(high.rolling(window=period).max().shift(1))
    lower = pd.Series(low.rolling(window=period).min().shift(1))
    middle = pd.Series((upper + lower) / 2.0)
    return upper, middle, lower


def classify_h4_regime(adx: float, ema_fast: float, ema_slow: float) -> MarketRegime:
    """Classify H4 market regime based on ADX strength and EMA crossover.

    Raises ValueError on NaN or None values (Pilar 2 Fail-Fast).
    """
    try:
        if math.isnan(adx) or math.isnan(ema_fast) or math.isnan(ema_slow):
            raise ValueError("Indicator values contain NaN; cannot classify regime.")
    except TypeError as err:
        raise ValueError(
            "Indicator values contain NaN; cannot classify regime."
        ) from err

    if adx >= 25.0:
        if ema_fast > ema_slow:
            return MarketRegime.TRENDING_BULLISH
        if ema_fast < ema_slow:
            return MarketRegime.TRENDING_BEARISH
        return MarketRegime.TRANSITIONING

    if adx >= 20.0:
        return MarketRegime.TRANSITIONING

    return MarketRegime.RANGING
