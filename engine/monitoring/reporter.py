"""Daily performance aggregation over the hot-tier SQLite WAL ledger (REQ-TEL-004).

Module: engine.monitoring.reporter
Responsibility: Implements DailyMetricsCollector and the Telegram daily dashboard
report assembled from the trades and system_state tables.
Owner: aeterna-architect
Tier: Tier B

Notes:
- Day window uses a half-open interval [target_date, next_date) to capture all
  timestamps (including sub-second and non-uniform ISO formats) without dropping
  exits at the end of the day.
- Drawdown is intraday peak-to-trough of the cumulative closed-trade PnL curve; the
  percentage denominator is the implied start-of-day balance (current equity - net PnL).
- Protection events are counted from blocked_signals (architecture §6.3) and trades
  tagged in protection states.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta

from engine.monitoring.types import DailyMetrics
from engine.shared.db import DatabaseManager
from engine.telegram_bot.templates import DailyDashboardData, format_daily_dashboard

PROTECTION_STATES: tuple[str, ...] = ("PAUSED", "PRE_NEWS_WATCH")
_EMPTY_URL_LABEL = "N/A"

_DAY_ROWS_SQL = """
SELECT pnl_usd, pnl_pips, spread_at_entry, state_machine_state,
       timestamp_entry_utc, timestamp_exit_utc
FROM trades
WHERE timestamp_exit_utc >= ? AND timestamp_exit_utc < ?
ORDER BY timestamp_exit_utc, trade_id
"""

_BLOCKED_COUNT_SQL = """
SELECT COUNT(*) FROM blocked_signals
WHERE reason_blocked IN ('state_machine_paused', 'state_machine_pre_news')
  AND timestamp_utc >= ? AND timestamp_utc < ?
"""

_STATE_SQL = "SELECT active_positions_count, equity_usd FROM system_state WHERE id = 1"


class DailyMetricsReporter:
    """Compiles daily metrics and renders the Telegram daily dashboard (REQ-TEL-004)."""

    def __init__(
        self, db_manager: DatabaseManager, myfxbook_url: str | None = None
    ) -> None:
        self.db_manager = db_manager
        self.myfxbook_url = myfxbook_url

    def collect_daily_metrics(self, target_date: str | None = None) -> DailyMetrics:
        """Compile consolidated metrics for the given UTC date (default: today)."""
        date_utc = self._resolve_date(target_date)
        rows, state, _ = self._load_day(date_utc)
        return self._build_metrics(date_utc, rows, state)

    def generate_dashboard_report(self, target_date: str | None = None) -> str:
        """Render the sterile Daily Dashboard Markdown for the given UTC date."""
        date_utc = self._resolve_date(target_date)
        rows, state, blocked_count = self._load_day(date_utc)
        metrics = self._build_metrics(date_utc, rows, state)
        trade_protection_events = sum(
            1 for row in rows if row["state_machine_state"] in PROTECTION_STATES
        )
        paused_events = blocked_count + trade_protection_events
        pips = [row["pnl_pips"] for row in rows if row["pnl_pips"] is not None]
        spreads = [
            row["spread_at_entry"] for row in rows if row["spread_at_entry"] is not None
        ]

        data = DailyDashboardData(
            date_str=date_utc,
            session_pnl_usd=metrics.net_pnl_usd,
            session_pnl_pips=float(sum(pips)),
            total_trades=metrics.total_trades,
            wins=metrics.win_trades,
            losses=metrics.loss_trades,
            max_drawdown_pct=metrics.max_drawdown_pct,
            paused_events_count=paused_events,
            avg_spread_pips=float(sum(spreads)) / len(spreads) if spreads else 0.0,
            myfxbook_url=self.myfxbook_url or _EMPTY_URL_LABEL,
        )
        return format_daily_dashboard(data)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_date(target_date: str | None) -> str:
        return target_date or datetime.now(UTC).strftime("%Y-%m-%d")

    def _load_day(
        self, date_utc: str
    ) -> tuple[list[sqlite3.Row], sqlite3.Row | None, int]:
        d = date.fromisoformat(date_utc)
        next_d = (d + timedelta(days=1)).isoformat()
        params = (date_utc, next_d)
        with self.db_manager.get_connection() as conn:
            rows: list[sqlite3.Row] = conn.execute(_DAY_ROWS_SQL, params).fetchall()
            state: sqlite3.Row | None = conn.execute(_STATE_SQL).fetchone()
            blocked_cursor = conn.execute(_BLOCKED_COUNT_SQL, params)
            blocked_row = blocked_cursor.fetchone()
            blocked_count = int(blocked_row[0]) if blocked_row else 0
        return rows, state, blocked_count

    def _build_metrics(
        self,
        date_utc: str,
        rows: list[sqlite3.Row],
        state: sqlite3.Row | None,
    ) -> DailyMetrics:
        pnls: list[float] = [
            row["pnl_usd"] for row in rows if row["pnl_usd"] is not None
        ]

        total_trades = len(rows)
        win_trades = sum(1 for pnl in pnls if pnl > 0)
        loss_trades = sum(1 for pnl in pnls if pnl < 0)
        gross_profit = float(sum(pnl for pnl in pnls if pnl > 0))
        gross_loss = float(-sum(pnl for pnl in pnls if pnl < 0))
        net_pnl = gross_profit - gross_loss
        win_rate = (win_trades / total_trades * 100.0) if total_trades > 0 else 0.0
        if gross_loss > 0.0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = float("inf") if gross_profit > 0.0 else 0.0

        equity = float(state["equity_usd"]) if state is not None else 0.0
        active_positions = (
            int(state["active_positions_count"]) if state is not None else 0
        )
        drawdown_usd, drawdown_pct = self._drawdown(
            pnls, equity, net_pnl, state is not None
        )
        # ponytail: state machine transition history table not in schema v1.0; upgrade path: state_transitions log table.
        paused_seconds = 0.0

        return DailyMetrics(
            date_utc=date_utc,
            total_trades=total_trades,
            win_trades=win_trades,
            loss_trades=loss_trades,
            win_rate_pct=win_rate,
            gross_profit_usd=gross_profit,
            gross_loss_usd=gross_loss,
            net_pnl_usd=net_pnl,
            profit_factor=profit_factor,
            max_drawdown_usd=drawdown_usd,
            max_drawdown_pct=drawdown_pct,
            paused_duration_seconds=paused_seconds,
            active_positions_count=active_positions,
            current_account_equity=equity,
            myfxbook_url=self.myfxbook_url,
        )

    @staticmethod
    def _drawdown(
        pnls: list[float],
        equity: float,
        net_pnl: float,
        equity_known: bool,
    ) -> tuple[float, float]:
        running = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for pnl in pnls:
            running += pnl
            peak = max(peak, running)
            max_drawdown = max(max_drawdown, peak - running)

        start_balance = (equity - net_pnl) if equity_known else 0.0
        peak_balance = start_balance + peak
        pct = (max_drawdown / peak_balance * 100.0) if peak_balance > 0.0 else 0.0
        return max_drawdown, pct
