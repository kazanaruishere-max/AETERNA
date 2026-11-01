"""Online tick volume filter and DST-aware rollover protection.

Enforces financial invariants:
- REQ-RSK-003: Online tick volume rolling mean and Z-score filter for graduated sizing.
- REQ-RSK-006: 15-minute rollover buffer prior to broker daily break.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo


class TickVolumeFilter:
    """Rolling tick volume filter computing online mean and Z-score.

    Formula:
        Z_volume(t) = (V(t) - mu_V(t)) / max(sigma_V(t), 1e-4)
        If |V(t) - mu_V(t)| < 1e-6 => Z_volume(t) = 0.0.
        Warm-up: Z-score is None while read_count < warmup_reads (default 20).
    """

    def __init__(self, window_size: int = 60, warmup_reads: int = 20) -> None:
        if window_size <= 0:
            raise ValueError(f"window_size must be positive, got {window_size}")
        if warmup_reads <= 0:
            raise ValueError(f"warmup_reads must be positive, got {warmup_reads}")

        self.window_size = int(window_size)
        self.warmup_reads = int(warmup_reads)
        self._window: deque[float] = deque(maxlen=self.window_size)
        self._mean: float | None = None
        self._std_dev: float = 0.0
        self._z_score: float | None = None
        self._read_count: int = 0

    @property
    def mean(self) -> float | None:
        """Current rolling mean tick volume."""
        return self._mean

    @property
    def std_dev(self) -> float:
        """Current rolling standard deviation."""
        return self._std_dev

    @property
    def z_score(self) -> float | None:
        """Current Z-score, or None during warm-up."""
        return self._z_score

    @property
    def read_count(self) -> int:
        """Total number of tick volume reads processed."""
        return self._read_count

    @property
    def is_warmed_up(self) -> bool:
        """Whether warmup_reads threshold has been satisfied."""
        return self._read_count >= self.warmup_reads

    def update(self, tick_volume: float) -> tuple[float, float, float | None]:
        """Process a new tick volume observation.

        Args:
            tick_volume: Observed tick volume count.

        Returns:
            Tuple of (rolling_mean, rolling_std_dev, z_score).
            z_score is None when read_count < warmup_reads.
        """
        vol = float(tick_volume)
        self._read_count += 1
        self._window.append(vol)

        n = len(self._window)
        self._mean = sum(self._window) / n
        variance = sum((x - self._mean) ** 2 for x in self._window) / n
        self._std_dev = math.sqrt(max(0.0, variance))

        if self._read_count < self.warmup_reads:
            self._z_score = None
            return (self._mean, self._std_dev, None)

        diff = vol - self._mean
        if abs(diff) < 1e-6:
            self._z_score = 0.0
        else:
            denom = max(self._std_dev, 1e-4)
            self._z_score = diff / denom

        return (self._mean, self._std_dev, self._z_score)

    def get_liquidity_scale(self) -> float:
        """Get sizing scale based on tick volume Z-score.

        Returns:
            1.0 (100% sizing) if Z >= -2.0 or still in warmup.
            0.5 (50% sizing) if Z < -2.0 (thin liquidity).
        """
        if self._z_score is None or self._z_score >= -2.0:
            return 1.0
        return 0.5


class RolloverFilter:
    """Filter detecting daily broker rollover window and break buffer.

    Enforces REQ-RSK-006:
    US Summer (EDT): Buffer 20:44:00 UTC to 22:01:00 UTC.
    US Winter (EST): Buffer 21:44:00 UTC to 23:01:00 UTC.
    """

    @staticmethod
    def is_in_rollover_buffer(current_utc: datetime) -> bool:
        """Check if current UTC datetime falls inside the 15-minute pre-rollover buffer or break."""
        if current_utc.tzinfo is None:
            utc_dt = current_utc.replace(tzinfo=UTC)
        else:
            utc_dt = current_utc.astimezone(UTC)

        ny_dt = utc_dt.astimezone(ZoneInfo("America/New_York"))
        is_summer = bool(ny_dt.dst())

        t = utc_dt.time()
        if is_summer:
            return time(20, 44, 0) <= t <= time(22, 1, 0)
        return time(21, 44, 0) <= t <= time(23, 1, 0)
