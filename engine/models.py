"""Core domain data models for Aeterna Quant Engine.

All models are immutable dataclasses (frozen=True) to guarantee thread safety
and data integrity across ingestion, risk gating, and storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Timeframe = Literal["M1", "M15", "H1", "H4"]
CandleSource = Literal["exness_mt5", "oanda_v20"]
TradeDirection = Literal["LONG", "SHORT"]
DataTag = Literal["training", "validation", "forward_test", "live_production"]
StateMachineState = Literal[
    "NORMAL", "PRE_NEWS_WATCH", "PAUSED", "RECOVERY_CHECK", "MANUAL_OVERRIDE"
]
ExitReason = Literal[
    "sl_hit",
    "tp_hit",
    "trailing_hit",
    "partial_close",
    "time_invalidation",
    "regime_invalidation",
    "pre_rollover_force",
    "manual_emergency",
]
BlockedReason = Literal[
    "risk_gate_daily_loss",
    "risk_gate_max_dd",
    "state_machine_paused",
    "state_machine_pre_news",
    "low_liquidity_extreme",
    "max_concurrent_exceeded",
    "stale_signal_expired",
]
ModelStatus = Literal["candidate", "active", "archived", "rejected"]


@dataclass(frozen=True)
class CandleRecord:
    """Historical or live OHLCV candle for hot-tier storage."""

    pair: str
    timeframe: Timeframe
    timestamp_utc: str  # ISO-8601 UTC format: YYYY-MM-DDTHH:MM:SSZ
    source: CandleSource
    open: float
    high: float
    low: float
    close: float
    tick_volume: int


@dataclass(frozen=True)
class TradeRecord:
    """Execution trade ledger entry."""

    trade_id: str
    timestamp_entry_utc: str
    pair: str
    direction: TradeDirection
    data_tag: DataTag
    state_machine_state: StateMachineState
    regime_detected: str
    strategy_selected: str
    confidence_score: float  # Range: 0.0 - 100.0
    hypothesis: str
    entry_price: float
    sl: float
    tp: float
    lot_size: float  # Min: 0.01
    spread_at_entry: float
    model_version_id: str
    timestamp_exit_utc: str | None = None
    exit_price: float | None = None
    exit_reason: ExitReason | None = None
    pnl_usd: float | None = None
    pnl_pips: float | None = None
    slippage_realized: float | None = None


@dataclass(frozen=True)
class BlockedSignalRecord:
    """Audit entry for signals rejected by risk gates or news state machine."""

    timestamp_utc: str
    pair: str
    direction: TradeDirection
    strategy_selected: str
    reason_blocked: BlockedReason
    confidence_at_time: float
    would_be_entry_price: float
    current_spread: float
    details: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class ModelRegistryRecord:
    """Model version tracking metadata."""

    model_version: str
    training_date_utc: str
    data_range: str
    hyperparameters: str
    backtest_metrics: str
    status: ModelStatus
    forward_test_metrics: str | None = None
    deployed_at_utc: str | None = None


@dataclass(frozen=True)
class SystemStateRecord:
    """IPC shared memory/state singleton record."""

    state: StateMachineState
    current_spread: float
    spread_baseline: float
    spread_z_score: float
    active_positions_count: int  # 0 or 1
    equity_usd: float
    daily_pnl_usd: float
    trades_today_count: int  # 0 to 5
    last_updated_utc: str
    last_news_event: str | None = None
    id: int = 1
