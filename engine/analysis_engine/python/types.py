"""
Module: engine.analysis_engine.python.types
Responsibility: TypedDict and Dataclass representations of backtest data in Python.
Owner: aeterna-backtest
Tier: B
"""

from __future__ import annotations

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


class OrderDict(TypedDict):
    """Order dictionary representation for backtest simulation."""

    id: str
    direction: str
    requested_price: float
    lot_size: float
    sl_price: float | None
    tp_price: float | None
    execution_type: NotRequired[str]


class BacktestConfigDict(TypedDict, total=False):
    """Configuration dictionary representation for broker simulation parameters."""

    contract_size: float
    point_size: float
    pip_size: float
    leverage: float
    stop_level_points: float
    slippage_free_points: float
    default_spread_points: float


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
    monte_carlo: MonteCarloResultDict | None = None
