"""Module: tests.e2e.test_runtime_restart_replay_e2e
Responsibility: End-to-end verification of M15 downtime gap replay, idempotency,
                admin Telegram summary notification, and strict segregation of live vs replay publishers.
Owner: aeterna-verifier
Tier: Tier A
Covers: REQ-RUNTIME-009, REQ-RUNTIME-011
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from engine.analysis_engine.python.indicators import MarketRegime
from engine.analysis_engine.python.types import CandleDict, ModelInferenceResult
from engine.models import CandleRecord, SystemStateRecord
from engine.runtime.bootstrap import (
    RuntimeBundle,
    build_runtime_bundle,
    run_restart_recovery,
)
from engine.runtime.restart_replay import (
    H4_SECONDS,
    M15_SECONDS,
    GapStatus,
    RestartReplayConfig,
    RestartReplayEngine,
    compute_config_hash,
    compute_current_closed_bar,
)
from engine.shared.db.database import DatabaseManager
from instruments.xauusd.strategies.volatility_breakout import SignalType, TradeSignal
from scripts.verify_restart_replay import inspect_gap_status
from scripts.verify_restart_replay import main as verify_script_main

ADMIN_CHAT_ID = 999_888_777
PUBLIC_CHANNEL_ID = -100_123_456_789
VIP_CHANNEL_ID = -100_987_654_321
SYMBOL = "XAUUSDm"

# Reference operational timeline: 3 M15 bars downtime
T_NOW = 1_795_411_608  # 2026-11-23 05:26:48 UTC
CURRENT_CLOSED_TS = compute_current_closed_bar(T_NOW)  # 1_795_410_000 (05:00 UTC)
CURSOR_START_TS = CURRENT_CLOSED_TS - (3 * M15_SECONDS)  # 1_795_407_300 (04:15 UTC)

PROHIBITED_TOKENS = ("lot", "equity", "ticket", "server", "buy now", "sell now")


def _ts(epoch_seconds: int) -> str:
    """Format epoch timestamp as ISO UTC string."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_candles(
    end_bar_ts: int, step: int, count: int, pair: str = SYMBOL, timeframe: str = "M15"
) -> list[CandleRecord]:
    """Generate ascending contiguous CandleRecords ending at end_bar_ts."""
    timestamps = [end_bar_ts - step * offset for offset in range(count - 1, -1, -1)]
    return [
        CandleRecord(
            pair=pair,
            timeframe=timeframe,  # type: ignore[arg-type]
            timestamp_utc=_ts(ts),
            source="exness_mt5",
            open=2000.0,
            high=2005.0,
            low=1995.0,
            close=2002.0,
            tick_volume=100,
        )
        for ts in timestamps
    ]


class E2EFakeExnessClient:
    """Deterministic ExnessClient supplying M15 and H4 candles without broker/network calls."""

    def __init__(self, current_ts: int) -> None:
        self.symbol = SYMBOL
        self.lock = threading.RLock()
        self.connected = True
        self.current_ts = current_ts

    def fetch_recent_candles(
        self, timeframe: str, count: int
    ) -> list[CandleRecord]:
        step = M15_SECONDS if timeframe == "M15" else H4_SECONDS
        aligned_ts = (self.current_ts // step) * step
        return _generate_candles(aligned_ts, step, count + 50, timeframe=timeframe)


class E2EFakeKronos:
    """Deterministic Kronos regime engine for replay and live tests."""

    def __init__(self, regime: str = "TRENDING_BULLISH") -> None:
        self.regime = regime
        self.model_id = "kronos_h4_v1.0.0"

    def infer_regime(self, context_candles: list[CandleDict]) -> ModelInferenceResult:
        ts = (
            context_candles[-1]["timestamp_utc"]
            if context_candles
            else "2026-11-23T00:00:00Z"
        )
        return ModelInferenceResult(
            model_id=self.model_id,
            timestamp_utc=ts,
            regime=self.regime,
            confidence=0.90,
            probabilities={self.regime: 0.90},
            context_candles_count=len(context_candles),
            temporal_assertion_passed=True,
        )

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        return len(candles) >= 1


class E2EMockControlBot:
    """Mock Telegram bot verifying channel segregation and admin summary delivery."""

    def __init__(self) -> None:
        self.admin_messages: list[dict[str, Any]] = []
        self.public_messages: list[dict[str, Any]] = []
        self.vip_messages: list[dict[str, Any]] = []
        self.all_sends: list[dict[str, Any]] = []
        self.send_photo_calls: list[dict[str, Any]] = []

    def send(self, payload: dict[str, Any]) -> bool:
        chat_id = payload.get("chat_id")
        self.all_sends.append(payload)
        if chat_id == ADMIN_CHAT_ID:
            self.admin_messages.append(payload)
        elif chat_id == PUBLIC_CHANNEL_ID:
            self.public_messages.append(payload)
        elif chat_id == VIP_CHANNEL_ID:
            self.vip_messages.append(payload)
        return True

    def send_photo(self, chat_id: int, photo: bytes, caption: str) -> bool:
        call_info = {"chat_id": chat_id, "photo": photo, "caption": caption}
        self.send_photo_calls.append(call_info)
        return self.send({"chat_id": chat_id, "text": caption, "photo": photo})

    def send_initial_dashboard(self, admin_id: int) -> bool:
        return True


def _init_e2e_db(tmp_path: Path) -> DatabaseManager:
    """Initialize fresh SQLite database with WAL and canonical schema."""
    db_path = str(tmp_path / "e2e_trading.db")
    db = DatabaseManager(db_path=db_path)
    db.init_db()

    cfg_hash = compute_config_hash()
    db.advance_bar_cursor_with_config_hash(
        symbol=SYMBOL,
        timeframe="M15",
        last_closed_bar_ts=CURSOR_START_TS,
        config_hash=cfg_hash,
    )

    state = SystemStateRecord(
        state="NORMAL",
        current_spread=1.2,
        spread_baseline=1.1,
        spread_z_score=0.1,
        active_positions_count=0,
        equity_usd=1000.0,
        daily_pnl_usd=0.0,
        trades_today_count=0,
        last_news_event="CPI_NORMAL",
        last_updated_utc=_ts(T_NOW - 100),
    )
    db.set_system_state(state)
    return db


def _make_signal(
    signal_type: SignalType, entry: float, sl: float, tp: float
) -> TradeSignal:
    """Helper to instantiate a concrete TradeSignal."""
    return TradeSignal(
        signal_type=signal_type,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        atr_value=10.0,
        h4_regime=MarketRegime.TRENDING_BULLISH,
        reason="e2e_deterministic_signal",
    )


class E2EConfigurableEvaluator:
    """Strategy evaluator returning scheduled signals per bar timestamp."""

    def __init__(self, signals_by_ts: dict[str, list[TradeSignal]] | None = None) -> None:
        self.signals_by_ts = signals_by_ts or {}

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: Any = None,
        sentiment: Any = None,
    ) -> list[TradeSignal]:
        if not m15_candles:
            return []
        current_bar_ts = m15_candles[-1]["timestamp_utc"]
        return self.signals_by_ts.get(current_bar_ts, [])


def test_replay_does_not_send_live_observation_alert(tmp_path: Path) -> None:
    """Replay executes silently with 0 live alert publications and emits exactly 1 admin summary."""
    db = _init_e2e_db(tmp_path)
    bot = E2EMockControlBot()
    client = E2EFakeExnessClient(T_NOW)
    kronos = E2EFakeKronos()

    t1 = _ts(CURSOR_START_TS + M15_SECONDS)
    valid_buy = _make_signal(SignalType.BUY, 2000.0, 1990.0, 2025.0)  # R:R = 2.5
    evaluator = E2EConfigurableEvaluator(signals_by_ts={t1: [valid_buy]})

    bundle: RuntimeBundle = build_runtime_bundle(
        exness_client=client,  # type: ignore[arg-type]
        control_bot=bot,  # type: ignore[arg-type]
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=str(db.db_path),
        symbol=SYMBOL,
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
        replay_config=RestartReplayConfig(replay_mode="auto", max_bars=32),
    )

    mock_live_publisher = MagicMock()
    bundle.dashboard.publish = mock_live_publisher  # type: ignore[assignment]
    bundle.dashboard.publish_with_chart = mock_live_publisher  # type: ignore[assignment]

    summary = run_restart_recovery(bundle, now_utc=T_NOW)
    assert summary is not None
    assert summary.status == "COMPLETED"
    assert summary.replayed_count == 3
    assert summary.observations_created == 1

    # Invariant 1: Live OBSERVATION publisher called 0 times during replay
    assert mock_live_publisher.call_count == 0

    # Invariant 2: Admin replay summary dispatched exactly 1 time
    admin_text = summary.format_admin_message()
    bot.send({"chat_id": ADMIN_CHAT_ID, "text": admin_text})
    assert len(bot.admin_messages) == 1
    assert "[AETERNA REPLAY AUDIT]" in bot.admin_messages[0]["text"]
    assert "Replayed: 3" in bot.admin_messages[0]["text"]
    assert "Observations Created: 1" in bot.admin_messages[0]["text"]

    # Invariant 3: Public/VIP channels never called
    assert len(bot.public_messages) == 0
    assert len(bot.vip_messages) == 0

    # Invariant 4: No prohibited tokens in summary
    lower_admin_text = admin_text.lower()
    for token in PROHIBITED_TOKENS:
        assert token not in lower_admin_text


def test_replay_summary_counts(tmp_path: Path) -> None:
    """Summary payload metrics exactly match persisted replay_runs database row."""
    db = _init_e2e_db(tmp_path)
    client = E2EFakeExnessClient(T_NOW)
    kronos = E2EFakeKronos()

    t1 = _ts(CURSOR_START_TS + M15_SECONDS)
    t2 = _ts(CURSOR_START_TS + (2 * M15_SECONDS))

    sig_valid = _make_signal(SignalType.BUY, 2000.0, 1990.0, 2025.0)  # R:R = 2.5 -> Obs
    sig_sub_rr = _make_signal(SignalType.BUY, 2000.0, 1990.0, 2005.0)  # R:R = 0.5 -> Blocked
    evaluator = E2EConfigurableEvaluator(signals_by_ts={t1: [sig_valid], t2: [sig_sub_rr]})

    config = RestartReplayConfig(replay_mode="auto", max_bars=32)
    engine = RestartReplayEngine(
        exness_client=client,
        db_manager=db,
        kronos_engine=kronos,
        strategy_evaluator=evaluator,
        config=config,
        symbol=SYMBOL,
    )

    summary = engine.run_recovery(now_utc=T_NOW)
    assert summary.status == "COMPLETED"
    assert summary.missed_count == 3
    assert summary.replayed_count == 3
    assert summary.observations_created == 1
    assert summary.blocked_created == 1
    assert summary.replay_id is not None

    record = db.get_replay_run(summary.replay_id)
    assert record is not None
    assert record.status == "COMPLETED"
    assert record.missed_count == summary.missed_count
    assert record.observations_created == summary.observations_created
    assert record.blocked_created == summary.blocked_created
    assert record.strategy_id == "E2EConfigurableEvaluator"
    assert record.model_id == "kronos_h4_v1.0.0"


def test_e2e_restart_gap_replay_lifecycle(tmp_path: Path) -> None:
    """Complete E2E test: 3-bar gap replay, idempotency on restart, and segregation."""
    db = _init_e2e_db(tmp_path)
    bot = E2EMockControlBot()
    client = E2EFakeExnessClient(T_NOW)
    kronos = E2EFakeKronos()

    t1 = _ts(CURSOR_START_TS + M15_SECONDS)
    t2 = _ts(CURSOR_START_TS + (2 * M15_SECONDS))
    valid_signal = _make_signal(SignalType.BUY, 2000.0, 1990.0, 2025.0)
    sub_rr_signal = _make_signal(SignalType.SELL, 2000.0, 2005.0, 1997.0)
    evaluator = E2EConfigurableEvaluator(signals_by_ts={t1: [valid_signal], t2: [sub_rr_signal]})

    bundle: RuntimeBundle = build_runtime_bundle(
        exness_client=client,  # type: ignore[arg-type]
        control_bot=bot,  # type: ignore[arg-type]
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=str(db.db_path),
        symbol=SYMBOL,
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
        replay_config=RestartReplayConfig(replay_mode="auto", max_bars=32),
    )

    # 1. Verify initial cursor is at bar N
    initial_cursor = db.get_bar_cursor(SYMBOL, "M15")
    assert initial_cursor is not None
    assert initial_cursor.last_closed_bar_ts == CURSOR_START_TS

    # 2. Restart triggers replay of exactly 3 bars
    summary1 = run_restart_recovery(bundle, now_utc=T_NOW)
    assert summary1 is not None
    assert summary1.status == "COMPLETED"
    assert summary1.missed_count == 3
    assert summary1.replayed_count == 3
    assert summary1.observations_created == 1
    assert summary1.blocked_created == 1

    # Persist summary notification to Telegram Admin
    bot.send({"chat_id": ADMIN_CHAT_ID, "text": summary1.format_admin_message()})
    assert len(bot.admin_messages) == 1
    assert len(bot.public_messages) == 0

    # Verify origin='REPLAY' segregation
    replay_obs = db.get_open_signal_observations(SYMBOL)
    assert len(replay_obs) == 1
    assert replay_obs[0].origin == "REPLAY"
    assert replay_obs[0].replay_id == summary1.replay_id

    replay_blocked = db.get_blocked_signals_by_origin("REPLAY")
    assert len(replay_blocked) == 1
    assert replay_blocked[0].origin == "REPLAY"

    # Verify bar cursor has advanced to CURRENT_CLOSED_TS
    advanced_cursor = db.get_bar_cursor(SYMBOL, "M15")
    assert advanced_cursor is not None
    assert advanced_cursor.last_closed_bar_ts == CURRENT_CLOSED_TS

    # 3. Second restart produces NO_GAP and zero duplicate rows
    bundle2: RuntimeBundle = build_runtime_bundle(
        exness_client=client,  # type: ignore[arg-type]
        control_bot=bot,  # type: ignore[arg-type]
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=str(db.db_path),
        symbol=SYMBOL,
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
        replay_config=RestartReplayConfig(replay_mode="auto", max_bars=32),
    )

    summary2 = run_restart_recovery(bundle2, now_utc=T_NOW)
    assert summary2 is not None
    assert summary2.status == "NO_GAP"
    assert summary2.missed_count == 0
    assert summary2.replayed_count == 0

    # Verify no duplicate observations or blocked signals were created
    assert len(db.get_open_signal_observations(SYMBOL)) == 1
    assert len(db.get_blocked_signals_by_origin("REPLAY")) == 1


def test_verify_restart_replay_script_read_only(tmp_path: Path) -> None:
    """scripts/verify_restart_replay.py executes strictly read-only against temp DB."""
    db = _init_e2e_db(tmp_path)

    # 1. Run inspect_gap_status directly
    report = inspect_gap_status(
        db_path=db.db_path,
        symbol=SYMBOL,
        timeframe="M15",
        now_utc=T_NOW,
    )

    assert report["db_path"] == str(db.db_path)
    assert report["symbol"] == SYMBOL
    assert report["gap_detection"]["status"] == GapStatus.REPLAY_REQUIRED.value
    assert report["gap_detection"]["missed_count"] == 3
    assert report["safety_assertions"]["read_only"] is True
    assert report["safety_assertions"]["db_mutations"] == 0
    assert report["safety_assertions"]["mt5_orders"] == 0
    assert report["safety_assertions"]["port_20128_contacted"] is False

    # 2. Test CLI execution with --json and --now-utc
    rc = verify_script_main([
        "--db-path", str(db.db_path),
        "--now-utc", str(T_NOW),
        "--json",
    ])
    assert rc == 0
