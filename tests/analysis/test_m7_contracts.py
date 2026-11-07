"""Unit tests for Milestone 7 Contracts, Interfaces, and Invariants.

Module: tests.analysis.test_m7_contracts
Responsibility: Verifies the 3 architectural safeguards:
1. RollingFeatureScaler: Zero lookahead data leakage; isolated window normalization only.
2. Temporal Assertion Gate: Strict validation max(timestamp(X)) < timestamp(y).
3. Lazy-Loading Pipeline: pyarrow chunked iteration preventing OOM.
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from engine.analysis_engine.python.interfaces import (
    KronosDataset,
    KronosInferenceEngine,
    MacroFeatureProvider,
    OandaSentimentProvider,
    StrategyEvaluator,
    TemporalGateValidator,
)
from engine.analysis_engine.python.types import (
    MacroFeatures,
    ModelInferenceResult,
    OandaSentimentRatio,
    RollingFeatureScaler,
    ScalerWindowStats,
    TemporalTensorPair,
)


def test_rolling_feature_scaler_zero_leakage() -> None:
    """Verify that RollingFeatureScaler computes stats strictly per window."""
    scaler = RollingFeatureScaler(window_size=5)

    # Window 1: values 10, 20, 30
    window_1 = [10.0, 20.0, 30.0]
    stats_1 = scaler.compute_stats(window_1, feature_name="close")
    assert stats_1.mean == pytest.approx(20.0)
    assert stats_1.std > 0

    scaled = scaler.transform_series(window_1, stats_1)
    assert scaled[1] == pytest.approx(0.0)  # Mean value scales to 0
    assert scaled[0] < 0.0
    assert scaled[2] > 0.0

    # Ensure window limit enforced
    with pytest.raises(ValueError, match="Window size exceeded"):
        scaler.compute_stats([1.0] * 6)

    # Ensure empty list rejected
    with pytest.raises(ValueError, match="empty values"):
        scaler.compute_stats([])


def test_rolling_feature_scaler_immutability() -> None:
    """Verify that RollingFeatureScaler and ScalerWindowStats are immutable."""
    scaler = RollingFeatureScaler(window_size=512)
    with pytest.raises(FrozenInstanceError):
        scaler.window_size = 256  # type: ignore[misc]

    stats = ScalerWindowStats(feature_name="close", mean=2000.0, std=15.0)
    with pytest.raises(FrozenInstanceError):
        stats.mean = 2050.0  # type: ignore[misc]


def test_temporal_tensor_pair_lookahead_gate() -> None:
    """Verify that TemporalTensorPair strictly rejects lookahead bias."""
    # Valid pair: max(X) is strictly before y
    pair = TemporalTensorPair(
        max_x_timestamp_utc="2026-01-01T12:00:00Z",
        y_timestamp_utc="2026-01-01T16:00:00Z",
        sequence_length=1,
        feature_count=1,
        features_x=[[2000.0]],
        label_y=2005.0,
    )
    assert pair.max_x_timestamp_utc < pair.y_timestamp_utc

    # Lookahead violation: max(X) == y
    with pytest.raises(ValueError, match="Temporal lookahead violation detected"):
        TemporalTensorPair(
            max_x_timestamp_utc="2026-01-01T16:00:00Z",
            y_timestamp_utc="2026-01-01T16:00:00Z",
            sequence_length=1,
            feature_count=1,
            features_x=[[2000.0]],
            label_y=2005.0,
        )

    # Lookahead violation: max(X) > y
    with pytest.raises(ValueError, match="Temporal lookahead violation detected"):
        TemporalTensorPair(
            max_x_timestamp_utc="2026-01-01T20:00:00Z",
            y_timestamp_utc="2026-01-01T16:00:00Z",
            sequence_length=1,
            feature_count=1,
            features_x=[[2000.0]],
            label_y=2005.0,
        )


def test_kronos_dataset_lazy_parquet_pipeline() -> None:
    """Verify KronosDataset reads chunked Parquet lazily with temporal gate."""
    # Create synthetic parquet file
    data_rows = 15
    window_sz = 5
    chunk_sz = 5

    timestamps = [f"2026-01-01T{h:02d}:00:00Z" for h in range(data_rows)]
    closes = [2000.0 + float(i) for i in range(data_rows)]

    table = pa.Table.from_arrays(
        [pa.array(timestamps), pa.array(closes)],
        names=["timestamp_utc", "close"],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        pq_path = Path(tmpdir) / "test_h4_candles.parquet"
        pq.write_table(table, str(pq_path))

        dataset = KronosDataset(
            parquet_path=str(pq_path),
            window_size=window_sz,
            chunk_size=chunk_sz,
        )

        pairs = list(dataset)
        assert len(pairs) == data_rows - window_sz

        # Verify temporal assertion holds on every pair
        for p in pairs:
            assert p.max_x_timestamp_utc < p.y_timestamp_utc
            assert p.sequence_length == window_sz


def test_kronos_dataset_temporal_rejection() -> None:
    """Verify KronosDataset.validate_temporal_order rejects unordered data."""
    with pytest.raises(ValueError, match="not strictly before"):
        KronosDataset.validate_temporal_order(
            x_timestamps=["2026-01-01T10:00:00Z", "2026-01-01T12:00:00Z"],
            y_timestamp="2026-01-01T11:00:00Z",
        )

    with pytest.raises(ValueError, match="cannot be empty"):
        KronosDataset.validate_temporal_order([], "2026-01-01T12:00:00Z")


def test_m7_dataclass_contracts() -> None:
    """Verify initialization and immutability of M7 dataclasses."""
    macro = MacroFeatures(
        timestamp_utc="2026-01-01T00:00:00Z",
        tips_10y_yield=1.85,
        dxy_index=103.45,
        cpi_yoy=2.8,
        real_yield_change_20d=-0.12,
        dxy_change_20d=0.45,
    )
    assert macro.tips_10y_yield == 1.85
    with pytest.raises(FrozenInstanceError):
        macro.tips_10y_yield = 1.90  # type: ignore[misc]

    sentiment = OandaSentimentRatio(
        timestamp_utc="2026-01-01T00:00:00Z",
        long_position_pct=42.5,
        short_position_pct=57.5,
        long_order_pct=48.0,
        short_order_pct=52.0,
        skew_ratio=-0.15,
    )
    assert sentiment.skew_ratio == -0.15
    with pytest.raises(FrozenInstanceError):
        sentiment.skew_ratio = 0.0  # type: ignore[misc]

    inference = ModelInferenceResult(
        model_id="kronos-small-v1",
        timestamp_utc="2026-01-01T00:00:00Z",
        regime="BULLISH_TRENDING",
        confidence=0.88,
        probabilities={"BULLISH_TRENDING": 0.88, "RANGING": 0.12},
        context_candles_count=512,
        temporal_assertion_passed=True,
    )
    assert inference.confidence == 0.88
    with pytest.raises(FrozenInstanceError):
        inference.regime = "RANGING"  # type: ignore[misc]


def test_protocol_structural_subtyping() -> None:
    """Verify that mock implementations conform to M7 Protocols."""

    class MockKronosEngine:
        def infer_regime(self, context_candles: list[dict[str, object]]) -> ModelInferenceResult:
            return ModelInferenceResult(
                model_id="kronos-test",
                timestamp_utc="2026-01-01T00:00:00Z",
                regime="RANGING",
                confidence=0.95,
                probabilities={"RANGING": 0.95},
                context_candles_count=512,
                temporal_assertion_passed=True,
            )

        def validate_context_window(self, candles: list[dict[str, object]]) -> bool:
            return len(candles) == 512

    class MockMacroProvider:
        def get_latest_macro_features(self) -> MacroFeatures:
            return MacroFeatures(
                timestamp_utc="2026-01-01T00:00:00Z",
                tips_10y_yield=1.8,
                dxy_index=102.0,
            )

        def get_historical_macro_features(
            self, start_utc: str, end_utc: str
        ) -> list[MacroFeatures]:
            return [self.get_latest_macro_features()]

    class MockOandaProvider:
        def get_latest_sentiment(self) -> OandaSentimentRatio:
            return OandaSentimentRatio(
                timestamp_utc="2026-01-01T00:00:00Z",
                long_position_pct=50.0,
                short_position_pct=50.0,
                long_order_pct=50.0,
                short_order_pct=50.0,
                skew_ratio=0.0,
            )

    class MockStrategyEvaluator:
        def evaluate_signals(
            self,
            m15_candles: list[dict[str, object]],
            h4_candles: list[dict[str, object]],
            macro: MacroFeatures | None = None,
            sentiment: OandaSentimentRatio | None = None,
        ) -> list[object]:
            return []

    class MockTemporalValidator:
        def validate_temporal_order(
            self,
            x_timestamps: list[str],
            y_timestamp: str,
        ) -> bool:
            return max(x_timestamps) < y_timestamp

    assert isinstance(MockKronosEngine(), KronosInferenceEngine)
    assert isinstance(MockMacroProvider(), MacroFeatureProvider)
    assert isinstance(MockOandaProvider(), OandaSentimentProvider)
    assert isinstance(MockStrategyEvaluator(), StrategyEvaluator)
    assert isinstance(MockTemporalValidator(), TemporalGateValidator)
