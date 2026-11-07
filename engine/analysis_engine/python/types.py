"""
Module: engine.analysis_engine.python.types
Responsibility: TypedDict and Dataclass representations of backtest data in Python.
Owner: aeterna-backtest
Tier: B
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NotRequired, TypedDict


class CandleDict(TypedDict):
    """M1/M15/H1 candle data dictionary representation."""

    timestamp_utc: str
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    regime: NotRequired[str | None]

class OrderDict(TypedDict):
    """Order dictionary representation for backtest simulation."""

    id: str
    direction: str
    requested_price: float
    lot_size: float
    sl_price: float | None
    tp_price: float | None
    signal_timestamp_utc: str
    validity_window_seconds: NotRequired[int]
    execution_type: NotRequired[str]


class DiscardedOrderDict(TypedDict):
    """Discarded stale order dictionary representation."""

    order_id: str
    direction: str
    signal_timestamp_utc: str
    candle_timestamp_utc: str
    elapsed_seconds: int
    validity_window_seconds: int
    requested_price: float
    reason: str

class BacktestConfigDict(TypedDict, total=False):
    """Configuration dictionary representation for broker simulation parameters."""

    contract_size: float
    point_size: float
    pip_size: float
    leverage: float
    stop_level_points: float
    slippage_free_points: float
    default_spread_points: float
    max_holding_seconds: NotRequired[int]

class BacktestSummaryDict(TypedDict):
    """Performance metrics summary returned by simulation loop."""

    total_trades: int
    win_trades: int
    loss_trades: int
    gross_profit_usd: float
    gross_loss_usd: float
    net_pnl_usd: float
    profit_factor: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    total_spread_cost_usd: float
    total_slippage_cost_usd: float


class AuditRecordDict(TypedDict):
    """Trade execution audit record for determinism verification."""

    trade_id: str
    direction: str
    lot_size: float
    requested_entry: float
    executed_entry: float
    slippage_entry_usd: float
    requested_exit: float
    executed_exit: float
    slippage_exit_usd: float
    gross_pnl_usd: float
    pnl_pips: float
    spread_cost_usd: float
    net_pnl_usd: float
    margin_required_usd: float
    stop_level_checked: bool
    gap_rule_applied: bool
    exit_reason: str

class MonteCarloResultDict(TypedDict):
    """Monte Carlo trade sequence shuffling percentile results."""

    iterations: int
    median_max_dd_pct: float
    percentile_95_max_dd_pct: float
    percentile_99_max_dd_pct: float
    risk_of_ruin_10pct_dd: float


class PnlResultDict(TypedDict):
    """Pure mathematical PnL calculation breakdown."""

    gross_pnl_usd: float
    pnl_pips: float
    spread_cost_usd: float
    net_pnl_usd: float
    margin_required_usd: float


@dataclass(frozen=True)
class BacktestReport:
    """Immutable aggregate report of a completed backtest execution."""

    summary: BacktestSummaryDict
    trades: list[AuditRecordDict]
    discarded_orders: list[DiscardedOrderDict]
    monte_carlo: MonteCarloResultDict | None = None


# ==============================================================================
# Milestone 7: Advanced Layers & Zero-Leakage Machine Learning Contracts
# ==============================================================================


@dataclass(frozen=True)
class ScalerWindowStats:
    """Computed mean and standard deviation for features within an isolated window."""

    feature_name: str
    mean: float
    std: float


@dataclass(frozen=True)
class RollingFeatureScaler:
    """Zero-leakage rolling feature scaler operating strictly within an isolated window.

    Mandates:
    - Normalization of OHLCV and ATR is strictly confined to the isolated window (512 candles).
    - Global dataset scalers (e.g., sklearn StandardScaler across entire history) are strictly
      prohibited to prevent future lookahead leakage into historical bars.
    - Built-in epsilon prevents zero-division on flat price sequences.
    """

    window_size: int = 512
    epsilon: float = 1e-8

    def compute_stats(self, values: list[float], feature_name: str = "feature") -> ScalerWindowStats:
        """Compute mean and standard deviation strictly from values within the window."""
        if not values:
            raise ValueError(f"Cannot compute rolling stats on empty values for {feature_name}")
        if len(values) > self.window_size:
            raise ValueError(
                f"Window size exceeded: provided {len(values)} values, maximum allowed {self.window_size}"
            )
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance) + self.epsilon
        return ScalerWindowStats(feature_name=feature_name, mean=mean, std=std)

    def transform_value(self, value: float, stats: ScalerWindowStats) -> float:
        """Transform a single value using precomputed isolated window stats."""
        return (value - stats.mean) / stats.std

    def transform_series(self, values: list[float], stats: ScalerWindowStats) -> list[float]:
        """Transform an entire series using isolated window stats."""
        return [(v - stats.mean) / stats.std for v in values]


@dataclass(frozen=True)
class MacroFeatures:
    """Macroeconomic & intermarket indicators for XAUUSD (REQ-STR-005)."""

    timestamp_utc: str
    tips_10y_yield: float
    dxy_index: float
    cpi_yoy: float | None = None
    real_yield_change_20d: float | None = None
    dxy_change_20d: float | None = None


@dataclass(frozen=True)
class OandaSentimentRatio:
    """Positioning and order book sentiment breakdown (REQ-STR-004)."""

    timestamp_utc: str
    long_position_pct: float
    short_position_pct: float
    long_order_pct: float
    short_order_pct: float
    skew_ratio: float


@dataclass(frozen=True)
class ModelInferenceResult:
    """Deterministic H4 regime inference output from Kronos model (REQ-STR-007)."""

    model_id: str
    timestamp_utc: str
    regime: str
    confidence: float
    probabilities: dict[str, float]
    context_candles_count: int
    temporal_assertion_passed: bool


@dataclass(frozen=True)
class TemporalTensorPair:
    """Immutable tensor pair representation enforcing lookahead prevention.

    Mandates:
    - max(timestamp_utc in X) < timestamp_utc in y MUST hold absolutely.
    - Lookahead assertion gate prevents any future information leakage.
    """

    max_x_timestamp_utc: str
    y_timestamp_utc: str
    sequence_length: int
    feature_count: int
    features_x: list[list[float]]
    label_y: float

    def __post_init__(self) -> None:
        if self.max_x_timestamp_utc >= self.y_timestamp_utc:
            raise ValueError(
                f"Temporal lookahead violation detected: max(X) timestamp "
                f"({self.max_x_timestamp_utc}) >= y timestamp ({self.y_timestamp_utc})"
            )

