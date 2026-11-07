"""Data types and immutable models for system metrics aggregation and reporting.

Module: engine.monitoring.types
Responsibility: Defines immutable data structures for daily performance reporting,
win rate / PnL aggregation, drawdown metrics, and operational stability tracking.
Owner: aeterna-architect
Tier: Tier B
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DailyMetrics:
    """Consolidated daily operational and performance metrics.

    Enforces REQ-TEL-004:
    - Daily financial PnL, Win/Loss count, Win rate (historical hit rate).
    - Maximum daily drawdown in USD and percentage.
    - Accumulated duration spent in PAUSED state.
    - Active position count and current equity snapshot.
    """

    date_utc: str                      # Format: YYYY-MM-DD
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate_pct: float                # Calculated percentage (0.0 to 100.0)
    gross_profit_usd: float
    gross_loss_usd: float
    net_pnl_usd: float
    profit_factor: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    paused_duration_seconds: float     # Total seconds state machine was in PAUSED today
    active_positions_count: int
    current_account_equity: float
    myfxbook_url: str | None = None
