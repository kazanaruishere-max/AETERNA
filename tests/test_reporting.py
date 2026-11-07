"""Unit tests for SQLite WAL Daily Metrics Aggregator & Automated Reporting (TASK-M6-STREAM-B).

Covers REQ-TEL-004:
- test_empty_trades_daily_metrics: zero division safety on empty days.
- test_profitable_day_metrics: 3 trades (2 wins, 1 loss) -> 66.67% win rate, PF 2.50.
- test_losing_day_metrics: 2 loss trades -> 0.0% win rate, PF 0.0.
- test_intraday_drawdown_calculation: peak-to-trough curve drawdown validation.
- test_dashboard_template_integration: output passes strict text purity and template match.
"""

from pathlib import Path

import pytest

from engine.models import (
    BlockedSignalRecord,
    StateMachineState,
    SystemStateRecord,
    TradeRecord,
)
from engine.monitoring.reporter import DailyMetricsReporter
from engine.shared.db import DatabaseManager
from engine.telegram_bot.interfaces import DailyMetricsCollector
from engine.telegram_bot.templates import validate_text_purity

MODEL_VERSION = "v1.0.0-rulebased"
TARGET_DATE = "2026-11-06"


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    """Create a temporary initialized SQLite database with WAL mode."""
    db_file = tmp_path / "test_reporting.db"
    manager = DatabaseManager(db_file)
    manager.init_db()
    return manager


def _create_trade(
    trade_id: str,
    pnl_usd: float,
    pnl_pips: float,
    exit_time: str,
    state: StateMachineState = "NORMAL",
    entry_time: str = "2026-11-06T10:00:00Z",
    spread: float = 1.5,
) -> TradeRecord:
    """Helper to construct a valid TradeRecord."""
    return TradeRecord(
        trade_id=trade_id,
        timestamp_entry_utc=entry_time,
        timestamp_exit_utc=exit_time,
        pair="XAUUSD",
        direction="LONG",
        data_tag="live_production",
        state_machine_state=state,
        regime_detected="TRENDING_UP",
        strategy_selected="M15_MOMENTUM",
        confidence_score=85.0,
        hypothesis="Quantitative momentum breakout",
        entry_price=2740.0,
        exit_price=2745.0,
        sl=2735.0,
        tp=2750.0,
        lot_size=0.1,
        spread_at_entry=spread,
        model_version_id=MODEL_VERSION,
        exit_reason="tp_hit" if pnl_usd > 0 else "sl_hit",
        pnl_usd=pnl_usd,
        pnl_pips=pnl_pips,
    )


def _create_blocked_signal(timestamp_utc: str) -> BlockedSignalRecord:
    """Helper to construct a state-machine protection block record."""
    return BlockedSignalRecord(
        timestamp_utc=timestamp_utc,
        pair="XAUUSD",
        direction="LONG",
        strategy_selected="M15_MOMENTUM",
        reason_blocked="state_machine_paused",
        confidence_at_time=82.0,
        would_be_entry_price=2741.0,
        current_spread=4.2,
    )


def test_protocol_conformance(db: DatabaseManager) -> None:
    """Verify DailyMetricsReporter conforms structurally to DailyMetricsCollector."""
    reporter = DailyMetricsReporter(db_manager=db)
    assert isinstance(reporter, DailyMetricsCollector)


def test_empty_trades_daily_metrics(db: DatabaseManager) -> None:
    """Matrix 1: Zero trades yields zeroed metrics without division by zero error."""
    reporter = DailyMetricsReporter(db_manager=db)
    metrics = reporter.collect_daily_metrics(target_date=TARGET_DATE)

    assert metrics.date_utc == TARGET_DATE
    assert metrics.total_trades == 0
    assert metrics.win_trades == 0
    assert metrics.loss_trades == 0
    assert metrics.win_rate_pct == 0.0
    assert metrics.gross_profit_usd == 0.0
    assert metrics.gross_loss_usd == 0.0
    assert metrics.net_pnl_usd == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.max_drawdown_usd == 0.0
    assert metrics.max_drawdown_pct == 0.0
    assert metrics.paused_duration_seconds == 0.0
    assert metrics.active_positions_count == 0
    assert metrics.current_account_equity == 0.0


def test_profitable_day_metrics(db: DatabaseManager) -> None:
    """Matrix 2: 3 trades (2 wins +$50, 1 loss -$20) -> Win rate 66.67%, Net PnL +$30, PF 2.50."""
    trades = [
        _create_trade(
            "TRD-01", pnl_usd=30.0, pnl_pips=15.0, exit_time="2026-11-06T11:00:00Z"
        ),
        _create_trade(
            "TRD-02", pnl_usd=20.0, pnl_pips=10.0, exit_time="2026-11-06T12:00:00Z"
        ),
        _create_trade(
            "TRD-03", pnl_usd=-20.0, pnl_pips=-10.0, exit_time="2026-11-06T13:00:00Z"
        ),
    ]
    for trade in trades:
        db.insert_trade(trade)

    db.set_system_state(
        SystemStateRecord(
            state="NORMAL",
            current_spread=1.2,
            spread_baseline=1.5,
            spread_z_score=0.2,
            active_positions_count=0,
            equity_usd=10030.0,
            daily_pnl_usd=30.0,
            trades_today_count=3,
            last_news_event=None,
            last_updated_utc="2026-11-06T13:05:00Z",
        )
    )

    reporter = DailyMetricsReporter(
        db_manager=db,
        myfxbook_url="https://myfxbook.com/members/aeterna/xauusd",
    )
    metrics = reporter.collect_daily_metrics(target_date=TARGET_DATE)

    assert metrics.date_utc == TARGET_DATE
    assert metrics.total_trades == 3
    assert metrics.win_trades == 2
    assert metrics.loss_trades == 1
    assert round(metrics.win_rate_pct, 2) == 66.67
    assert metrics.gross_profit_usd == 50.0
    assert metrics.gross_loss_usd == 20.0
    assert metrics.net_pnl_usd == 30.0
    assert round(metrics.profit_factor, 2) == 2.50
    assert metrics.active_positions_count == 0
    assert metrics.current_account_equity == 10030.0
    assert metrics.myfxbook_url == "https://myfxbook.com/members/aeterna/xauusd"


def test_losing_day_metrics(db: DatabaseManager) -> None:
    """Matrix 3: 2 trades (loss -$40 total) -> Win rate 0.0%, Net PnL -$40, PF 0.0."""
    trades = [
        _create_trade(
            "TRD-L1", pnl_usd=-25.0, pnl_pips=-12.5, exit_time="2026-11-06T09:00:00Z"
        ),
        _create_trade(
            "TRD-L2", pnl_usd=-15.0, pnl_pips=-7.5, exit_time="2026-11-06T10:00:00Z"
        ),
    ]
    for trade in trades:
        db.insert_trade(trade)

    reporter = DailyMetricsReporter(db_manager=db)
    metrics = reporter.collect_daily_metrics(target_date=TARGET_DATE)

    assert metrics.total_trades == 2
    assert metrics.win_trades == 0
    assert metrics.loss_trades == 2
    assert metrics.win_rate_pct == 0.0
    assert metrics.gross_profit_usd == 0.0
    assert metrics.gross_loss_usd == 40.0
    assert metrics.net_pnl_usd == -40.0
    assert metrics.profit_factor == 0.0


def test_intraday_drawdown_calculation(db: DatabaseManager) -> None:
    """Matrix 4: Validate peak-to-trough intraday drawdown calculation on equity curve.

    Sequence:
    Trade 1: +100 (cumulative: +100, peak: +100, dd: 0)
    Trade 2: -50  (cumulative: +50,  peak: +100, dd: 50)
    Trade 3: -30  (cumulative: +20,  peak: +100, dd: 80)  <-- Max Drawdown = $80
    Trade 4: +70  (cumulative: +90,  peak: +100, dd: 10)
    Start balance = $1,000. Peak balance = $1,100.
    Max DD USD = $80. Max DD % = 80 / 1100 * 100 = 7.27%.
    """
    trades = [
        _create_trade(
            "TRD-DD1", pnl_usd=100.0, pnl_pips=50.0, exit_time="2026-11-06T08:00:00Z"
        ),
        _create_trade(
            "TRD-DD2", pnl_usd=-50.0, pnl_pips=-25.0, exit_time="2026-11-06T09:00:00Z"
        ),
        _create_trade(
            "TRD-DD3", pnl_usd=-30.0, pnl_pips=-15.0, exit_time="2026-11-06T10:00:00Z"
        ),
        _create_trade(
            "TRD-DD4", pnl_usd=70.0, pnl_pips=35.0, exit_time="2026-11-06T11:00:00Z"
        ),
    ]
    for trade in trades:
        db.insert_trade(trade)

    db.set_system_state(
        SystemStateRecord(
            state="NORMAL",
            current_spread=1.2,
            spread_baseline=1.5,
            spread_z_score=0.1,
            active_positions_count=0,
            equity_usd=1090.0,  # 1000 + 90 net PnL
            daily_pnl_usd=90.0,
            trades_today_count=4,
            last_news_event=None,
            last_updated_utc="2026-11-06T11:05:00Z",
        )
    )

    reporter = DailyMetricsReporter(db_manager=db)
    metrics = reporter.collect_daily_metrics(target_date=TARGET_DATE)

    assert metrics.net_pnl_usd == 90.0
    assert metrics.max_drawdown_usd == 80.0
    assert round(metrics.max_drawdown_pct, 2) == 7.27


def test_dashboard_template_integration(db: DatabaseManager) -> None:
    """Matrix 5: Dashboard string matches canonical format and satisfies purity rules."""
    trades = [
        _create_trade(
            "TRD-D1",
            pnl_usd=50.0,
            pnl_pips=25.0,
            exit_time="2026-11-06T09:00:00Z",
            state="NORMAL",
            entry_time="2026-11-06T08:30:00Z",
            spread=2.0,
        ),
        _create_trade(
            "TRD-D2",
            pnl_usd=-10.0,
            pnl_pips=-5.0,
            exit_time="2026-11-06T14:00:00Z",
            state="NORMAL",
            entry_time="2026-11-06T13:40:00Z",
            spread=1.4,
        ),
    ]
    for trade in trades:
        db.insert_trade(trade)
    db.insert_blocked_signal(_create_blocked_signal("2026-11-06T07:30:00Z"))

    db.set_system_state(
        SystemStateRecord(
            state="NORMAL",
            current_spread=1.4,
            spread_baseline=1.5,
            spread_z_score=0.0,
            active_positions_count=0,
            equity_usd=10040.0,
            daily_pnl_usd=40.0,
            trades_today_count=2,
            last_news_event=None,
            last_updated_utc="2026-11-06T14:05:00Z",
        )
    )

    url = "https://www.myfxbook.com/members/example/123456"
    reporter = DailyMetricsReporter(db_manager=db, myfxbook_url=url)
    report = reporter.generate_dashboard_report(target_date=TARGET_DATE)

    # Must pass strict text purity (no OpenAI, GPT, SMC/ICT jargon, raw win rate claims)
    validate_text_purity(report)

    # Must contain expected key sections
    assert "DAILY DASHBOARD" in report
    assert "2026-11-06" in report
    assert "+$40.00" in report
    assert "+20.0 pips" in report
    assert "Trades: 2 (Win: 1 | Loss: 1)" in report
    assert "Realized Session Win Ratio: 50.0%" in report
    assert "Engine PAUSED Events: 1" in report
    assert "Average Session Spread: 1.7 pips" in report
    assert url in report
    assert "Deterministic SQLite Audit Ledger" in report


def test_fractional_second_exit_timestamp(db: DatabaseManager) -> None:
    """Verify trades exiting in the final second with sub-second timestamps are not dropped."""
    late_trade = _create_trade(
        "TRD-LATE",
        pnl_usd=15.0,
        pnl_pips=7.5,
        exit_time="2026-11-06T23:59:59.852Z",
    )
    db.insert_trade(late_trade)

    reporter = DailyMetricsReporter(db_manager=db)
    metrics = reporter.collect_daily_metrics(target_date=TARGET_DATE)

    assert metrics.total_trades == 1
    assert metrics.win_trades == 1
    assert metrics.net_pnl_usd == 15.0
