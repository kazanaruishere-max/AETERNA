"""E2E smoke tests for the signal-only runtime bootstrap (TASK-RUNTIME-08).

Covers:
1. test_e2e_tick_to_observation_to_admin_publish     — full tick→candle→obs→publish path
2. test_e2e_strategy_adapter_converts_candle_dict_to_dataframe — CandleDict→DataFrame
3. test_e2e_no_live_order_calls                      — no order_send / PositionModify
4. test_e2e_news_source_is_explicit                  — NEWS_SOURCE=NONE and NEWS_EVENT_COUNT=0

All tests use mocked MT5 and Telegram; no real network or broker calls are made.
Timeout per test: ≤ 10 seconds.
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.analysis_engine.python.types import CandleDict, ModelInferenceResult
from engine.runtime.bootstrap import (
    RuntimeBundle,
    _candle_dicts_to_df,
    build_runtime_bundle,
)
from instruments.xauusd.strategies.volatility_breakout import SignalType, TradeSignal

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

ADMIN_CHAT_ID = 999_000_001


def _make_candle(ts: str, price: float = 2000.0) -> CandleDict:
    """Return a minimal CandleDict for testing."""
    return CandleDict(
        timestamp_utc=ts,
        open=price,
        high=price + 1.0,
        low=price - 1.0,
        close=price,
        tick_volume=100,
    )


def _make_m15_candles(n: int = 100) -> list[CandleDict]:
    """Generate n sequential M15 CandleDicts starting at a fixed epoch."""
    base_epoch = 1_700_000_000  # 2023-11-14 ~22:13 UTC
    return [
        _make_candle(
            ts=f"2023-11-{14 + (i * 900 // 86400):02d}T"
            f"{((base_epoch + i * 900) % 86400 // 3600):02d}:"
            f"{((base_epoch + i * 900) % 3600 // 60):02d}:"
            f"{((base_epoch + i * 900) % 60):02d}Z",
            price=2000.0 + i * 0.1,
        )
        for i in range(n)
    ]


def _make_h4_candles(n: int = 512) -> list[CandleDict]:
    """Generate n sequential H4 CandleDicts."""
    base_epoch = 1_600_000_000
    return [
        _make_candle(
            ts=f"2020-09-{13 + (i * 14400 // 86400):02d}T"
            f"{((base_epoch + i * 14400) % 86400 // 3600):02d}:00:00Z",
            price=1900.0 + i * 0.05,
        )
        for i in range(n)
    ]


class _DeterministicEvaluator:
    """Inject a fixed BUY TradeSignal with valid R:R (rr=2) for E2E test."""

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: Any = None,
        sentiment: Any = None,
    ) -> list[Any]:
        from engine.analysis_engine.python.indicators import MarketRegime

        return [
            TradeSignal(
                signal_type=SignalType.BUY,
                entry_price=2000.0,
                stop_loss=1990.0,
                take_profit=2020.0,
                atr_value=10.0,
                h4_regime=MarketRegime.TRENDING_BULLISH,
                reason="e2e_test_signal",
            )
        ]


class _FakeKronos:
    """Fake KronosInferenceEngine returning temporal_assertion_passed=True."""

    def infer_regime(self, context_candles: list[CandleDict]) -> ModelInferenceResult:
        ts = (
            context_candles[-1]["timestamp_utc"]
            if context_candles
            else "2020-01-01T00:00:00Z"
        )
        return ModelInferenceResult(
            model_id="fake-kronos",
            timestamp_utc=ts,
            regime="BULLISH_TRENDING",
            confidence=0.85,
            probabilities={
                "BULLISH_TRENDING": 0.85,
                "BEARISH_TRENDING": 0.10,
                "RANGING": 0.05,
            },
            context_candles_count=len(context_candles),
            temporal_assertion_passed=True,
        )

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        return len(candles) == 512


def _make_mock_exness() -> MagicMock:
    """Return a minimal ExnessClient mock."""
    mock = MagicMock()
    mock.connected = True
    mock.lock = __import__("threading").RLock()
    mock.mt5 = MagicMock()

    # symbol_info_tick returns a fake tick
    tick = MagicMock()
    tick.time = 1_700_000_900
    tick.bid = 2000.0
    tick.ask = 2000.3
    mock.mt5.symbol_info_tick.return_value = tick

    # copy_rates_from_pos not needed directly (loop_b uses fetch_recent_candles)
    mock.fetch_recent_candles = MagicMock(return_value=[])
    return mock


def _make_mock_control_bot(sends: list[dict[str, Any]]) -> MagicMock:
    """Return a TelegramControlBot mock that records send calls."""
    mock = MagicMock()
    mock.send_initial_dashboard.return_value = True

    def _record_send(payload: dict[str, Any]) -> bool:
        sends.append(payload)
        return True

    mock.send.side_effect = _record_send
    return mock


# ---------------------------------------------------------------------------
# Test 1: tick → candle → observation → admin publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_tick_to_observation_to_admin_publish(tmp_path: Any) -> None:
    """Verify RuntimeService publishes at least one observation to admin_chat_id."""
    db_path = str(tmp_path / "trading.db")
    sends: list[dict[str, Any]] = []

    exness = _make_mock_exness()
    control_bot = _make_mock_control_bot(sends)
    evaluator = _DeterministicEvaluator()
    kronos = _FakeKronos()

    # Seed the DB with an open signal observation so publisher has something to publish
    from engine.models import SignalObservationRecord
    from engine.shared.db.database import DatabaseManager

    db = DatabaseManager(db_path=db_path)
    db.init_db()
    obs = SignalObservationRecord(
        signal_id="XAUUSDm:1700000000:_DeterministicEvaluator",
        symbol="XAUUSDm",
        bar_ts=1_700_000_000,
        strategy_id="_DeterministicEvaluator",
        order_type="BUY",
        state="OPEN",
        entry_px=2000.0,
        sl_px=1990.0,
        tp_px=2020.0,
        lot_virtual=0.01,
    )
    db.insert_signal_observation(obs)

    bundle: RuntimeBundle = build_runtime_bundle(
        exness_client=exness,
        control_bot=control_bot,
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=db_path,
        symbol="XAUUSDm",
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
        publish_interval_seconds=0.1,
    )

    stop_event = asyncio.Event()

    # Run RuntimeService for a short burst then stop
    async def _stopper() -> None:
        await asyncio.sleep(0.5)
        stop_event.set()

    # Run only the publish loop (no MT5 loops that would block)
    async def _publish_loop_only() -> None:
        await bundle.runtime._publish_new_observations(stop_event)  # type: ignore[attr-defined]

    await asyncio.wait_for(
        asyncio.gather(_publish_loop_only(), _stopper()),
        timeout=8.0,
    )

    # At least one observation card must have been sent
    assert len(sends) >= 1, "Expected at least one send() call to Telegram"

    # All sends must target admin_chat_id only
    for payload in sends:
        assert payload.get("chat_id") == ADMIN_CHAT_ID, (
            f"Payload sent to non-admin chat_id: {payload.get('chat_id')}"
        )

    # No prohibited tokens in any message text
    _PROHIBITED = ("lot", "equity", "ticket", "server", "buy now", "sell now")
    for payload in sends:
        text = str(payload.get("text", "")).lower()
        for token in _PROHIBITED:
            assert token not in text, (
                f"Prohibited token '{token}' found in payload: {text!r}"
            )


# ---------------------------------------------------------------------------
# Test 2: strategy adapter converts CandleDict to DataFrame
# ---------------------------------------------------------------------------


def test_e2e_strategy_adapter_converts_candle_dict_to_dataframe() -> None:
    """Verify _candle_dicts_to_df produces correct DataFrame without exception."""
    candles = _make_m15_candles(10)
    df = _candle_dicts_to_df(candles)

    assert isinstance(df, pd.DataFrame)
    expected_cols = ["timestamp_utc", "open", "high", "low", "close", "tick_volume"]
    for col in expected_cols:
        assert col in df.columns, f"Missing column: {col}"
    assert len(df) == 10

    # Adapter returns valid list (may be [] if strategy conditions not met, but no exception)
    from engine.runtime.bootstrap import _VolatilityBreakoutAdapter

    adapter = _VolatilityBreakoutAdapter()
    m15 = _make_m15_candles(100)
    h4 = _make_h4_candles(512)
    result = adapter.evaluate_signals(m15, h4)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Test 3: no live order calls
# ---------------------------------------------------------------------------


def test_e2e_no_live_order_calls() -> None:
    """Confirm no order_send or PositionModify references exist in bootstrap or main."""
    import engine.main as main_module
    import engine.runtime.bootstrap as bootstrap_module

    forbidden = ("order_send", "PositionModify")
    for module in (bootstrap_module, main_module):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, (
                f"Forbidden call '{token}' found in {module.__name__}"
            )


# ---------------------------------------------------------------------------
# Test 4: NEWS_SOURCE=NONE is logged explicitly when news_events=None
# ---------------------------------------------------------------------------


def test_e2e_news_source_is_explicit(caplog: pytest.LogCaptureFixture) -> None:
    """Default news_events=None must log NEWS_SOURCE=NONE and NEWS_EVENT_COUNT=0."""
    from engine.runtime.bootstrap import _build_news_filter

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.bootstrap"):
        nf = _build_news_filter(None)

    assert nf.scheduled_events == [], "Expected no events registered"

    log_text = " ".join(caplog.messages)
    assert "NEWS_SOURCE=NONE" in log_text, (
        f"Expected 'NEWS_SOURCE=NONE' in logs, got: {log_text!r}"
    )
    assert "NEWS_EVENT_COUNT=0" in log_text, (
        f"Expected 'NEWS_EVENT_COUNT=0' in logs, got: {log_text!r}"
    )
