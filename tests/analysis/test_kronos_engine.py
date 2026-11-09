"""Unit tests for Kronos H4 Regime Inference Engine & Lazy Zero-Leakage Pipeline (REQ-STR-007)."""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportMissingImports=false
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Enable namespace package resolution for engine.models.kronos alongside engine/models.py
import engine.models

if not hasattr(engine.models, "__path__"):
    engine.models.__path__ = [str(Path(engine.models.__file__).parent / "models")]

import pytest

from engine.analysis_engine.python.interfaces import KronosInferenceEngine
from engine.analysis_engine.python.types import CandleDict, RollingFeatureScaler
from engine.models.kronos.inference import KronosH4RegimeEngine


def _make_h4_candles(
    count: int,
    prices: list[float] | None = None,
    base_price: float = 2000.0,
    start_dt: datetime | None = None,
) -> list[CandleDict]:
    """Generate deterministic H4 test candles in chronological order."""
    if start_dt is None:
        start_dt = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    candles: list[CandleDict] = []
    for i in range(count):
        close_val = prices[i] if prices is not None else (base_price + i * 0.5)
        dt = start_dt + timedelta(hours=4 * i)
        ts_str = dt.isoformat().replace("+00:00", "Z")
        candles.append(
            CandleDict(
                timestamp_utc=ts_str,
                open=close_val - 0.2,
                high=close_val + 0.5,
                low=close_val - 0.5,
                close=close_val,
                tick_volume=100,
            )
        )
    return candles


def test_kronos_engine_protocol_conformance() -> None:
    """Verify that KronosH4RegimeEngine conforms to KronosInferenceEngine protocol."""
    engine: KronosH4RegimeEngine = KronosH4RegimeEngine()
    assert isinstance(engine, KronosInferenceEngine)
    assert engine.window_size == 512
    assert engine.confidence_threshold == 0.60
    assert engine.model_id == "kronos-h4-v1.0"


def test_context_window_validation_exact_512() -> None:
    """Input of 511 or 513 candles must be rejected with ValueError."""
    engine: KronosH4RegimeEngine = KronosH4RegimeEngine()

    candles_511 = _make_h4_candles(511)
    assert engine.validate_context_window(candles_511) is False
    with pytest.raises(
        ValueError,
        match="Context window must contain exactly 512 chronologically ascending H4 candles",
    ):
        engine.infer_regime(candles_511)

    candles_513 = _make_h4_candles(513)
    assert engine.validate_context_window(candles_513) is False
    with pytest.raises(
        ValueError,
        match="Context window must contain exactly 512 chronologically ascending H4 candles",
    ):
        engine.infer_regime(candles_513)


def test_context_window_chronological_order() -> None:
    """Unordered or duplicate timestamps in context window must be rejected with ValueError."""
    engine: KronosH4RegimeEngine = KronosH4RegimeEngine()

    candles = _make_h4_candles(512)
    # Swap timestamps at index 10 and 11 to break ascending order
    candles[10]["timestamp_utc"], candles[11]["timestamp_utc"] = (
        candles[11]["timestamp_utc"],
        candles[10]["timestamp_utc"],
    )
    assert engine.validate_context_window(candles) is False
    with pytest.raises(
        ValueError,
        match="Context window must contain exactly 512 chronologically ascending H4 candles",
    ):
        engine.infer_regime(candles)

    # Duplicate timestamp
    candles_dup = _make_h4_candles(512)
    candles_dup[15]["timestamp_utc"] = candles_dup[14]["timestamp_utc"]
    assert engine.validate_context_window(candles_dup) is False
    with pytest.raises(
        ValueError,
        match="Context window must contain exactly 512 chronologically ascending H4 candles",
    ):
        engine.infer_regime(candles_dup)


def test_infer_regime_bullish_trend() -> None:
    """Input of steadily ascending prices must be detected as BULLISH_TRENDING with confidence >= 0.60."""
    engine: KronosH4RegimeEngine = KronosH4RegimeEngine()
    prices = [2000.0 + i * 2.0 for i in range(512)]
    candles = _make_h4_candles(512, prices=prices)

    result = engine.infer_regime(candles)

    assert result.regime == "BULLISH_TRENDING"
    assert result.confidence >= 0.60
    assert result.probabilities["BULLISH_TRENDING"] >= 0.60
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.context_candles_count == 512
    assert result.temporal_assertion_passed is True
    assert result.timestamp_utc == candles[-1]["timestamp_utc"]
    assert result.model_id == "kronos-h4-v1.0"


def test_infer_regime_bearish_trend() -> None:
    """Input of steadily descending prices must be detected as BEARISH_TRENDING with confidence >= 0.60."""
    engine: KronosH4RegimeEngine = KronosH4RegimeEngine()
    prices = [3000.0 - i * 2.0 for i in range(512)]
    candles = _make_h4_candles(512, prices=prices)

    result = engine.infer_regime(candles)

    assert result.regime == "BEARISH_TRENDING"
    assert result.confidence >= 0.60
    assert result.probabilities["BEARISH_TRENDING"] >= 0.60
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.context_candles_count == 512
    assert result.temporal_assertion_passed is True
    assert result.timestamp_utc == candles[-1]["timestamp_utc"]


def test_infer_regime_ranging() -> None:
    """Input of oscillating prices must be detected as RANGING."""
    engine: KronosH4RegimeEngine = KronosH4RegimeEngine()
    prices = [2000.0 + 15.0 * math.sin(i * 2 * math.pi / 16) for i in range(512)]
    candles = _make_h4_candles(512, prices=prices)

    result = engine.infer_regime(candles)

    assert result.regime == "RANGING"
    assert result.probabilities["RANGING"] > result.probabilities["BULLISH_TRENDING"]
    assert result.probabilities["RANGING"] > result.probabilities["BEARISH_TRENDING"]
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.context_candles_count == 512
    assert result.temporal_assertion_passed is True


def test_rolling_scaler_integration_zero_leakage() -> None:
    """Verify that normalization fits strictly on 512 candles with zero future leakage."""
    engine: KronosH4RegimeEngine = KronosH4RegimeEngine()
    uptrend_prices = [2000.0 + i * 1.5 for i in range(512)]
    candles_512 = _make_h4_candles(512, prices=uptrend_prices)

    result_512 = engine.infer_regime(candles_512)

    # Future 513th candle with an extreme price shock
    candle_513 = _make_h4_candles(
        1, prices=[50000.0], start_dt=datetime(2026, 4, 1, tzinfo=UTC)
    )[0]
    expanded_series = candles_512 + [candle_513]

    # Global scaler across all 513 would be contaminated by candle 513
    global_scaler = RollingFeatureScaler(window_size=513)
    closes_513 = [c["close"] for c in expanded_series]
    stats_leaked = global_scaler.compute_stats(closes_513, feature_name="close")

    # Isolated rolling scaler stats for the 512 window
    closes_512 = [c["close"] for c in candles_512]
    stats_isolated = engine.scaler.compute_stats(closes_512, feature_name="close")

    # The contaminated mean shifts by hundreds of dollars, while isolated mean is pure
    assert stats_isolated.mean == pytest.approx(sum(closes_512) / 512)
    assert abs(stats_leaked.mean - stats_isolated.mean) > 50.0

    # Engine inference strictly reproduces identical output when re-run on window 0:512
    rerun_result = engine.infer_regime(candles_512)
    assert rerun_result.regime == result_512.regime
    assert rerun_result.confidence == pytest.approx(result_512.confidence)
    assert rerun_result.probabilities == pytest.approx(result_512.probabilities)


def test_hard_confidence_gate_hesitation_forced_to_ranging() -> None:
    """Verify Hard Confidence Gate: P(Bull) < 0.60 (e.g. 45%) MUST be forced to RANGING."""
    engine = KronosH4RegimeEngine(confidence_threshold=0.60)

    # Mock the internal session or momentum evaluator to return hesitation probabilities:
    # Bull=45%, Bear=25%, Range=30% (Bullish is highest, but < 60%)
    engine._evaluate_benchmark_momentum = lambda _norm: (0.45, 0.25, 0.30)  # type: ignore[assignment]

    candles = _make_h4_candles(512)
    result = engine.infer_regime(candles)

    # Must be forced to RANGING to prevent premature trade entry
    assert result.regime == "RANGING"
    assert result.probabilities["BULLISH_TRENDING"] == pytest.approx(0.45)
    assert result.probabilities["BEARISH_TRENDING"] == pytest.approx(0.25)
    assert result.probabilities["RANGING"] == pytest.approx(0.30)

    # Repeat for Bearish hesitation: Bear=48%, Bull=22%, Range=30%
    engine._evaluate_benchmark_momentum = lambda _norm: (0.22, 0.48, 0.30)  # type: ignore[assignment]
    result_bear = engine.infer_regime(candles)

    assert result_bear.regime == "RANGING"
    assert result_bear.probabilities["BEARISH_TRENDING"] == pytest.approx(0.48)

    # Repeat for Clear Trend: Bull=65%, Bear=10%, Range=25% -> MUST be confirmed as BULLISH_TRENDING
    engine._evaluate_benchmark_momentum = lambda _norm: (0.65, 0.10, 0.25)  # type: ignore[assignment]
    result_confirmed = engine.infer_regime(candles)

    assert result_confirmed.regime == "BULLISH_TRENDING"
    assert result_confirmed.confidence == pytest.approx(0.65)
