"""Kronos H4 Regime Inference Engine & Lazy Zero-Leakage Pipeline (REQ-STR-007)."""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportMissingImports=false
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from engine.analysis_engine.python.interfaces import KronosInferenceEngine
from engine.analysis_engine.python.types import (
    CandleDict,
    ModelInferenceResult,
    RollingFeatureScaler,
)

try:
    import onnxruntime as ort  # pyright: ignore[reportMissingImports]
except ImportError:
    ort = None  # type: ignore[assignment]


class KronosH4RegimeEngine(KronosInferenceEngine):
    """Deterministic H4 regime inference engine implementing KronosInferenceEngine (REQ-STR-007)."""

    model_path: str | None
    window_size: int
    confidence_threshold: float
    model_id: str
    scaler: RollingFeatureScaler

    def __init__(
        self,
        model_path: str | None = None,
        window_size: int = 512,
        confidence_threshold: float = 0.60,
    ) -> None:
        self.model_path = model_path
        self.window_size = window_size
        self.confidence_threshold = confidence_threshold
        self.scaler = RollingFeatureScaler(window_size=window_size)
        self.model_id = Path(model_path).name if model_path else "kronos-h4-v1.0"
        self._session: Any = None

        if model_path is not None:
            path = Path(model_path)
            if not path.is_file():
                raise FileNotFoundError(f"Model file not found: {model_path}")
            if ort is None:
                raise RuntimeError(
                    "onnxruntime is required when model_path is provided"
                )
            self._session = ort.InferenceSession(
                str(path), providers=["CPUExecutionProvider"]
            )

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        """Verify that context window contains exactly 512 chronologically ascending candles."""
        if len(candles) != self.window_size:
            return False

        for i in range(len(candles) - 1):
            t_curr = candles[i].get("timestamp_utc")
            t_next = candles[i + 1].get("timestamp_utc")
            if not t_curr or not t_next or t_curr >= t_next:
                return False

        return True

    def infer_regime(self, context_candles: list[CandleDict]) -> ModelInferenceResult:
        """Infer H4 market regime from 512 context candles with zero lookahead leakage."""
        if not self.validate_context_window(context_candles):
            raise ValueError(
                "Context window must contain exactly 512 chronologically ascending H4 candles"
            )

        # Zero-leakage rolling normalization strictly confined to isolated 512-bar window
        closes = [float(c["close"]) for c in context_candles]
        stats = self.scaler.compute_stats(closes, feature_name="close")
        normalized_closes = self.scaler.transform_series(closes, stats)

        if self._session is not None:
            import numpy as np

            input_meta = self._session.get_inputs()[0]
            input_name = input_meta.name
            arr = np.array(normalized_closes, dtype=np.float32)
            if len(input_meta.shape) == 3:
                arr = arr.reshape(1, self.window_size, 1)
            elif len(input_meta.shape) == 2:
                arr = arr.reshape(1, self.window_size)
            raw_out = self._session.run(None, {input_name: arr})
            logits = np.array(raw_out[0], dtype=np.float64).flatten()
            exp_logits = np.exp(logits - np.max(logits))
            probs = exp_logits / np.sum(exp_logits)
            p_bull = float(probs[0])
            p_bear = float(probs[1]) if len(probs) > 1 else 0.0
            p_range = (
                float(probs[2]) if len(probs) > 2 else max(0.0, 1.0 - (p_bull + p_bear))
            )
        else:
            # ponytail: benchmark momentum heuristic; upgrade to calibrated transformer weights when ONNX artifact deployed
            p_bull, p_bear, p_range = self._evaluate_benchmark_momentum(
                normalized_closes
            )

        # Ensure probabilities strictly sum to 1.0
        p_sum = p_bull + p_bear + p_range
        p_bull = p_bull / p_sum
        p_bear = p_bear / p_sum
        p_range = 1.0 - (p_bull + p_bear)

        probabilities: dict[str, float] = {
            "BULLISH_TRENDING": p_bull,
            "BEARISH_TRENDING": p_bear,
            "RANGING": p_range,
        }

        # Hard Confidence Gate Mandate:
        # A directional trending regime is confirmed ONLY if mathematical confidence >= 0.60.
        # If the model is uncertain or hesitating (max_prob < 0.60), the regime is strictly
        # forced to "RANGING" to ensure ZERO TRADES are opened on Kronos ambiguity.
        if p_bull >= self.confidence_threshold and p_bull > p_bear and p_bull > p_range:
            regime = "BULLISH_TRENDING"
            confidence = p_bull
        elif p_bear >= self.confidence_threshold and p_bear > p_bull and p_bear > p_range:
            regime = "BEARISH_TRENDING"
            confidence = p_bear
        else:
            regime = "RANGING"
            # In ranging fallback, confidence reflects either ranging probability or residual certainty
            confidence = p_range if p_range >= self.confidence_threshold else max(p_range, 1.0 - max(p_bull, p_bear))

        return ModelInferenceResult(
            model_id=self.model_id,
            timestamp_utc=context_candles[-1]["timestamp_utc"],
            regime=regime,
            confidence=confidence,
            probabilities=probabilities,
            context_candles_count=len(context_candles),
            temporal_assertion_passed=True,
        )

    def _evaluate_benchmark_momentum(
        self, normalized_closes: list[float]
    ) -> tuple[float, float, float]:
        """Evaluate H4 regime probabilities via normalized window slope and correlation.

        Returns (p_bull, p_bear, p_range) where sum == 1.0.
        """
        n = len(normalized_closes)
        x_mean = (n - 1) / 2.0
        y_mean = sum(normalized_closes) / n

        num = 0.0
        den_x = 0.0
        den_y = 0.0
        for i, y in enumerate(normalized_closes):
            dx = i - x_mean
            dy = y - y_mean
            num += dx * dy
            den_x += dx * dx
            den_y += dy * dy

        den = math.sqrt(den_x * den_y)
        r = (num / den) if den > 0.0 else 0.0
        r = max(-1.0, min(1.0, r))

        # Map correlation to regime logits:
        # High positive r -> Bullish trend
        # High negative r -> Bearish trend
        # Near zero r -> Oscillating / Ranging
        z_bull = max(0.0, r) * 4.0
        z_bear = max(0.0, -r) * 4.0
        z_range = (1.0 - abs(r)) * 2.0

        exp_bull = math.exp(z_bull)
        exp_bear = math.exp(z_bear)
        exp_range = math.exp(z_range)
        total = exp_bull + exp_bear + exp_range

        p_bull = exp_bull / total
        p_bear = exp_bear / total
        p_range = 1.0 - (p_bull + p_bear)

        return p_bull, p_bear, p_range
