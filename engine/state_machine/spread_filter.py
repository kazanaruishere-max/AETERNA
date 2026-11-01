"""Online EWMA spread baseline and rolling standard deviation Z-score filter.

Enforces financial invariant REQ-RSK-002:
S_baseline(t) = alpha * S(t) + (1 - alpha) * S_baseline(t - 1)
Z(t) = (S(t) - S_baseline(t)) / max(sigma_S(t), 1e-4)
If |S(t) - S_baseline(t)| < 1e-6 => Z(t) = 0.0.
Warm-up: Z-score is None while t < warmup_reads (default 30).
"""

from __future__ import annotations

import math
from collections import deque


class SpreadFilter:
    """Online EWMA spread baseline and rolling Z-score filter."""

    def __init__(
        self,
        alpha: float = 0.08,
        window_size: int = 60,
        warmup_reads: int = 30,
    ) -> None:
        if not (0.0 < alpha < 1.0):
            raise ValueError(f"alpha must be between 0 and 1, got {alpha}")
        if window_size <= 0:
            raise ValueError(f"window_size must be positive, got {window_size}")
        if warmup_reads <= 0:
            raise ValueError(f"warmup_reads must be positive, got {warmup_reads}")

        self.alpha = float(alpha)
        self.window_size = int(window_size)
        self.warmup_reads = int(warmup_reads)

        self._window: deque[float] = deque(maxlen=self.window_size)
        self._baseline: float | None = None
        self._std_dev: float = 0.0
        self._z_score: float | None = None
        self._read_count: int = 0

    @property
    def baseline(self) -> float | None:
        """Current EWMA baseline value in pips."""
        return self._baseline

    @property
    def std_dev(self) -> float:
        """Current rolling standard deviation in pips."""
        return self._std_dev

    @property
    def z_score(self) -> float | None:
        """Current Z-score, or None if in warm-up period."""
        return self._z_score

    @property
    def read_count(self) -> int:
        """Total number of spread updates processed."""
        return self._read_count

    @property
    def is_warmed_up(self) -> bool:
        """Whether warmup_reads threshold has been satisfied."""
        return self._read_count >= self.warmup_reads

    def update(self, current_spread_pips: float) -> tuple[float, float, float | None]:
        """Process a new spread observation and compute online EWMA and Z-score.

        Args:
            current_spread_pips: Raw spread measurement in pips.

        Returns:
            Tuple of (baseline, rolling_std_dev, z_score).
            z_score is None when read_count < warmup_reads.
        """
        spread = float(current_spread_pips)
        self._read_count += 1
        self._window.append(spread)

        # 1. Update EWMA baseline
        if self._baseline is None:
            self._baseline = spread
        else:
            self._baseline = self.alpha * spread + (1.0 - self.alpha) * self._baseline

        # 2. Rolling standard deviation from last window_size reads
        n = len(self._window)
        mean = sum(self._window) / n
        variance = sum((x - mean) ** 2 for x in self._window) / n
        self._std_dev = math.sqrt(max(0.0, variance))

        # 3. Warm-up suppression
        if self._read_count < self.warmup_reads:
            self._z_score = None
            return (self._baseline, self._std_dev, None)

        # 4. Anti Div-by-Zero Epsilon & delta check
        diff = spread - self._baseline
        if abs(diff) < 1e-6:
            self._z_score = 0.0
        else:
            denom = max(self._std_dev, 1e-4)
            self._z_score = diff / denom

        return (self._baseline, self._std_dev, self._z_score)
