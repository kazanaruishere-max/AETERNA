"""Protocol interfaces and dataset contracts for Milestone 7 (Advanced Layers).

Module: engine.analysis_engine.python.interfaces
Responsibility: Defines abstract contracts (Protocols) and lazy dataset specifications
for Kronos H4 regime detection, macro intermarket features, OANDA sentiment ratios,
and zero-leakage rolling normalization.

Mandates:
1. Zero Data Leakage: Rolling normalization strictly confined to 512-bar window.
2. Temporal Assertion Gate: max(timestamp(X)) < timestamp(y) runtime verification.
3. Lazy-Loading Dataset: Chunked iteration via pyarrow/duckdb to prevent OOM errors.
Owner: aeterna-architect
Tier: Tier B
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportMissingImports=false
# pyright: reportUntypedBaseClass=false
# pyright: reportGeneralTypeIssues=false
# pyright: reportAssignmentType=false

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol, runtime_checkable

import pyarrow.parquet as pq

from engine.analysis_engine.python.types import (
    CandleDict,
    MacroFeatures,
    ModelInferenceResult,
    OandaSentimentRatio,
    RollingFeatureScaler,
    TemporalTensorPair,
)

# ------------------------------------------------------------------------------
# PyTorch IterableDataset Stub / Safe Import
# ------------------------------------------------------------------------------
# In live CPU execution / production environments, PyTorch might not be installed
# as inference is executed strictly via Kronos ONNX Runtime. A lightweight stub
# provides structural conformance without forcing a multi-gigabyte dependency.
try:
    import torch.utils.data as torch_data

    _BaseIterableDataset = torch_data.IterableDataset[TemporalTensorPair]
except (ImportError, AttributeError):

    class _BaseIterableDataset:  # type: ignore[no-redef]
        """Fallback base class when PyTorch is not installed in runtime environment."""


@runtime_checkable
class LazyParquetReader(Protocol):
    """Protocol for memory-safe chunked reading of Parquet time-series datasets."""

    def iter_batches(
        self,
        parquet_path: str,
        batch_size: int = 2048,
        columns: list[str] | None = None,
    ) -> Iterator[Any]:
        """Yield RecordBatch or DataFrame chunks without loading entire file into memory."""
        raise NotImplementedError


@runtime_checkable
class TemporalGateValidator(Protocol):
    """Protocol for temporal assertion gates to prevent lookahead bias."""

    def validate_temporal_order(
        self,
        x_timestamps: list[str],
        y_timestamp: str,
    ) -> bool:
        """Verify that max(x_timestamps) is strictly less than y_timestamp.

        Raises:
            ValueError: If max(x_timestamps) >= y_timestamp (lookahead violation).
        """
        raise NotImplementedError


class KronosDataset(_BaseIterableDataset):
    """Memory-safe chunked Parquet dataset with runtime Temporal Assertion Gate.

    Architectural Safeguards:
    1. Lazy-Loading: Reads .parquet via pyarrow chunked iteration (zero global in-memory DataFrame).
    2. Zero Leakage: RollingFeatureScaler computes stats strictly per 512-candle window.
    3. Temporal Gate: Asserts max(X.timestamp) < y.timestamp before yielding each pair.
    """

    def __init__(
        self,
        parquet_path: str,
        window_size: int = 512,
        chunk_size: int = 2048,
        scaler: RollingFeatureScaler | None = None,
    ) -> None:
        self.parquet_path = parquet_path
        self.window_size = window_size
        self.chunk_size = chunk_size
        self.scaler = scaler or RollingFeatureScaler(window_size=window_size)

    @staticmethod
    def validate_temporal_order(x_timestamps: list[str], y_timestamp: str) -> bool:
        """Enforce strict chronological isolation between input window and target label."""
        if not x_timestamps:
            raise ValueError("Input timestamp sequence X cannot be empty")
        max_x = max(x_timestamps)
        if max_x >= y_timestamp:
            raise ValueError(
                f"Temporal lookahead violation: max(X) timestamp ({max_x}) "
                f"is not strictly before y timestamp ({y_timestamp})"
            )
        return True

    def __iter__(self) -> Iterator[TemporalTensorPair]:
        """Iterate through Parquet file in chunks, yielding verified (X, y) pairs."""
        parquet_file = pq.ParquetFile(self.parquet_path)
        buffer: list[dict[str, Any]] = []

        for batch in parquet_file.iter_batches(batch_size=self.chunk_size):
            rows: list[dict[str, Any]] = batch.to_pylist()
            buffer.extend(rows)

            while len(buffer) > self.window_size:
                window = buffer[: self.window_size]
                target_row = buffer[self.window_size]

                x_timestamps = [str(r["timestamp_utc"]) for r in window]
                y_timestamp = str(target_row["timestamp_utc"])

                # Enforce temporal assertion gate
                self.validate_temporal_order(x_timestamps, y_timestamp)

                # Extract and scale features strictly within isolated window
                close_prices = [float(r["close"]) for r in window]
                stats = self.scaler.compute_stats(close_prices, feature_name="close")
                scaled_close = self.scaler.transform_series(close_prices, stats)

                pair = TemporalTensorPair(
                    max_x_timestamp_utc=max(x_timestamps),
                    y_timestamp_utc=y_timestamp,
                    sequence_length=self.window_size,
                    feature_count=1,
                    features_x=[[c] for c in scaled_close],
                    label_y=float(target_row["close"]),
                )
                yield pair
                buffer.pop(0)


@runtime_checkable
class KronosInferenceEngine(Protocol):
    """Protocol for deterministic H4 regime inference via Kronos ONNX Runtime CPU (REQ-STR-007)."""

    def infer_regime(self, context_candles: list[CandleDict]) -> ModelInferenceResult:
        """Infer H4 market regime from 512 context candles with zero external API calls."""
        raise NotImplementedError

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        """Verify that context window contains exactly 512 chronologically ascending candles."""
        raise NotImplementedError


@runtime_checkable
class MacroFeatureProvider(Protocol):
    """Protocol for fetching macroeconomic & intermarket signals (REQ-STR-005)."""

    def get_latest_macro_features(self) -> MacroFeatures:
        """Retrieve the latest US Real Yield (TIPS 10Y) and DXY proxy readings."""
        raise NotImplementedError

    def get_historical_macro_features(
        self,
        start_utc: str,
        end_utc: str,
    ) -> list[MacroFeatures]:
        """Query time-range of macro observations from SQLite cache."""
        raise NotImplementedError


@runtime_checkable
class OandaSentimentProvider(Protocol):
    """Protocol for querying OANDA Order and Position Book sentiment (REQ-STR-004)."""

    def get_latest_sentiment(self) -> OandaSentimentRatio:
        """Fetch current retail positioning long/short ratios and skew."""
        raise NotImplementedError


@runtime_checkable
class StrategyEvaluator(Protocol):
    """Protocol for evaluating multi-timeframe strategy setup candidates."""

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: MacroFeatures | None = None,
        sentiment: OandaSentimentRatio | None = None,
    ) -> list[Any]:
        """Evaluate strategy entry/exit conditions across multi-timeframe inputs."""
        raise NotImplementedError
