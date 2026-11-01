"""
Module: engine.analysis_engine.python.runner
Responsibility: High-level backtest facade & report generator wrapping PyO3 engine.
Owner: aeterna-backtest
Tier: B
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import aeterna_backtest  # pyright: ignore[reportMissingTypeStubs]

from engine.analysis_engine.python.loader import load_candles_from_db
from engine.analysis_engine.python.types import (
    AuditRecordDict,
    BacktestConfigDict,
    BacktestReport,
    BacktestSummaryDict,
    CandleDict,
    DiscardedOrderDict,
    MonteCarloResultDict,
    OrderDict,
)
from engine.models import BlockedSignalRecord, TradeDirection
from engine.shared.db.database import DatabaseManager

_backtest_module: Any = aeterna_backtest

class BacktestRunner:
    """High-level backtest simulation runner wrapping Rust PyO3 engine."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self.db_manager = db_manager or DatabaseManager()

    def run(
        self,
        candles: Sequence[CandleDict],
        orders: Sequence[OrderDict] | None = None,
        config: BacktestConfigDict | None = None,
        initial_balance: float = 10000.0,
        run_mc: bool = True,
        mc_simulations: int = 1000,
        mc_seed: int | None = None,
    ) -> BacktestReport:
        """Run backtest simulation loop with optional Monte Carlo analysis."""
        order_list = list(orders) if orders is not None else []
        summary_raw: Any
        audit_records_raw: Any
        discarded_orders_raw: Any
        summary_raw, audit_records_raw, discarded_orders_raw = (
            _backtest_module.py_run_backtest(
                list(candles),
                order_list,
                config,
                initial_balance,
            )
        )

        summary = cast(BacktestSummaryDict, summary_raw)
        audit_records = cast(list[AuditRecordDict], audit_records_raw)
        discarded_orders = cast(list[DiscardedOrderDict], discarded_orders_raw)

        mc_result: MonteCarloResultDict | None = None
        if run_mc and len(audit_records) > 0:
            mc_raw: Any = _backtest_module.py_run_monte_carlo(
                trades=audit_records,
                num_simulations=mc_simulations,
                seed=mc_seed,
                initial_equity=initial_balance,
            )
            mc_result = cast(MonteCarloResultDict, mc_raw)

        return BacktestReport(
            summary=summary,
            trades=audit_records,
            discarded_orders=discarded_orders,
            monte_carlo=mc_result,
        )

    def run_from_db(
        self,
        pair: str = "XAUUSD",
        timeframe: str = "M1",
        source: str = "exness_mt5",
        orders: Sequence[OrderDict] | None = None,
        config: BacktestConfigDict | None = None,
        initial_balance: float = 10000.0,
        start_time_utc: str | None = None,
        end_time_utc: str | None = None,
        run_mc: bool = True,
        mc_simulations: int = 1000,
        mc_seed: int | None = None,
    ) -> BacktestReport:
        """Load candles from SQLite and execute backtest simulation.

        Raises:
            RuntimeError: If SQLite database is locked, busy, or unreachable after timeout.
                This fail-fast fault-out behavior guarantees that callers and higher-level
                orchestrators never proceed with incomplete or corrupt candle datasets.
            ValueError: If no candles match the specified query criteria.
        """
        try:
            candles = load_candles_from_db(
                db_manager=self.db_manager,
                pair=pair,
                timeframe=timeframe,
                source=source,
                start_time_utc=start_time_utc,
                end_time_utc=end_time_utc,
            )
        except RuntimeError as exc:
            # Re-raise with domain-specific backtest context while preserving root cause
            raise RuntimeError(
                f"BacktestRunner failed to load candles due to database lock/timeout: {exc}"
            ) from exc

        report = self.run(
            candles=candles,
            orders=orders,
            config=config,
            initial_balance=initial_balance,
            run_mc=run_mc,
            mc_simulations=mc_simulations,
            mc_seed=mc_seed,
        )

        if report.discarded_orders:
            for discarded in report.discarded_orders:
                self.db_manager.insert_blocked_signal(
                    BlockedSignalRecord(
                        timestamp_utc=discarded["candle_timestamp_utc"],
                        pair=pair,
                        direction=cast(TradeDirection, discarded["direction"]),
                        strategy_selected="stale_signal_expired",
                        reason_blocked="stale_signal_expired",
                        confidence_at_time=1.0,
                        would_be_entry_price=discarded["requested_price"],
                        current_spread=0.0,
                        details=(
                            f"order_id={discarded['order_id']}, "
                            f"elapsed_seconds={discarded['elapsed_seconds']}, "
                            f"validity_window_seconds={discarded['validity_window_seconds']}"
                        ),
                    )
                )

        return report
