"""E2E smoke tests for the signal-only runtime bootstrap (TASK-RUNTIME-08B).

Covers:
1. test_e2e_tick_to_observation_to_admin_publish       — Loop B run_once → observation +1 → admin publish
2. test_e2e_buy_regime_flip_to_trending_bearish_closes_regime  — BUY + TRENDING_BEARISH -> CLOSED_REGIME
3. test_e2e_sell_regime_flip_to_trending_bullish_closes_regime — SELL + TRENDING_BULLISH -> CLOSED_REGIME
4. test_e2e_strategy_adapter_converts_candle_dict_to_dataframe — CandleDict → DataFrame
5. test_e2e_no_live_order_calls                        — no order_send / PositionModify
6. test_e2e_news_source_is_explicit                    — NEWS_SOURCE=NONE and NEWS_EVENT_COUNT=0
7. test_e2e_regime_source_is_explicit                  — REGIME_SOURCE=KRONOS_MEMO

All tests use mocked MT5 and Telegram; no real network or broker calls are made.
Timeout per test: <= 10 seconds.
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
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.analysis_engine.python.indicators import MarketRegime
from engine.analysis_engine.python.types import CandleDict, ModelInferenceResult
from engine.models import CandleRecord, Timeframe
from engine.runtime.bootstrap import (
    RuntimeBundle,
    _candle_dicts_to_df,
    build_runtime_bundle,
)
from instruments.xauusd.strategies.volatility_breakout import SignalType, TradeSignal

ADMIN_CHAT_ID = 999_000_001
BAR_TS = 1_699_963_200  # 2023-11-14T12:00:00Z (M15-aligned, far outside rollover)
PROHIBITED_TOKENS = ("lot", "equity", "ticket", "server", "buy now", "sell now")


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _iso_utc(ts: int) -> str:
    """Format epoch seconds as ISO-8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_candle_record(
    tf: Timeframe, ts_str: str, price: float = 2000.0
) -> CandleRecord:
    """Create a minimal CandleRecord for context lookback."""
    return CandleRecord(
        pair="XAUUSDm",
        timeframe=tf,
        timestamp_utc=ts_str,
        source="exness_mt5",
        open=price,
        high=price + 2.0,
        low=price - 2.0,
        close=price,
        tick_volume=100,
    )


def _make_candle_records(
    tf: Timeframe, bar_ts: int, step: int, count: int
) -> list[CandleRecord]:
    """Generate count closed CandleRecords ending at bar_ts plus 1 forming bar."""
    timestamps = [bar_ts - step * i for i in range(count - 1, -1, -1)]
    timestamps.append(bar_ts + step)
    return [
        _make_candle_record(tf, _iso_utc(ts), price=2000.0 + i * 0.1)
        for i, ts in enumerate(timestamps)
    ]


def _make_tick(time_ts: int, bid: float = 2000.0, ask: float = 2000.2) -> Any:
    """Return a mocked tick object."""
    tick = MagicMock()
    tick.time = time_ts
    tick.bid = bid
    tick.ask = ask
    return tick


def _make_mock_exness(bar_ts: int = BAR_TS) -> MagicMock:
    """Return an ExnessClient mock returning context candles and valid ticks."""
    mock = MagicMock()
    mock.connected = True
    mock.lock = __import__("threading").RLock()
    mock.mt5 = MagicMock()
    mock.mt5.symbol_info_tick.return_value = _make_tick(bar_ts + 60)

    h4_cutoff = ((bar_ts + 900) // 14400) * 14400 - 14400

    def _fetch_candles(tf: str, count: int) -> list[CandleRecord]:
        if tf == "M15":
            return _make_candle_records("M15", bar_ts, 900, 100)
        return _make_candle_records("H4", h4_cutoff, 14400, 512)

    mock.fetch_recent_candles = MagicMock(side_effect=_fetch_candles)
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


class _DeterministicEvaluator:
    """Inject a deterministic TradeSignal with R:R >= 2.0 for E2E tests."""

    def __init__(self, signal_type: SignalType = SignalType.BUY) -> None:
        self.signal_type = signal_type

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: Any = None,
        sentiment: Any = None,
    ) -> list[Any]:
        if self.signal_type is SignalType.BUY:
            return [
                TradeSignal(
                    signal_type=SignalType.BUY,
                    entry_price=2000.0,
                    stop_loss=1990.0,
                    take_profit=2020.0,
                    atr_value=10.0,
                    h4_regime=MarketRegime.TRENDING_BULLISH,
                    reason="e2e_test_buy",
                )
            ]
        return [
            TradeSignal(
                signal_type=SignalType.SELL,
                entry_price=2000.0,
                stop_loss=2010.0,
                take_profit=1980.0,
                atr_value=10.0,
                h4_regime=MarketRegime.TRENDING_BEARISH,
                reason="e2e_test_sell",
            )
        ]


class _FakeKronos:
    """Fake KronosInferenceEngine with certified temporal assertion."""

    def __init__(self, regime: str = "TRENDING_BULLISH") -> None:
        self.regime = regime

    def infer_regime(self, context_candles: list[CandleDict]) -> ModelInferenceResult:
        ts = (
            context_candles[-1]["timestamp_utc"]
            if context_candles
            else "2020-01-01T00:00:00Z"
        )
        return ModelInferenceResult(
            model_id="fake-kronos",
            timestamp_utc=ts,
            regime=self.regime,
            confidence=0.85,
            probabilities={self.regime: 0.85},
            context_candles_count=len(context_candles),
            temporal_assertion_passed=True,
        )

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        return len(candles) == 512


async def _run_publish_burst(runtime: Any, duration: float = 0.3) -> None:
    """Run publisher loop for a brief duration then cleanly stop."""
    stop_event = asyncio.Event()

    async def _stopper() -> None:
        await asyncio.sleep(duration)
        stop_event.set()

    await asyncio.wait_for(
        asyncio.gather(runtime._publish_new_observations(stop_event), _stopper()),
        timeout=8.0,
    )


# ---------------------------------------------------------------------------
# Test 1: Loop B run_once -> observation +1 -> admin publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_tick_to_observation_to_admin_publish(tmp_path: Any) -> None:
    """Verify Loop B generates observation and RuntimeService publishes to admin."""
    db_path = str(tmp_path / "trading.db")
    sends: list[dict[str, Any]] = []

    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot(sends)
    evaluator = _DeterministicEvaluator(SignalType.BUY)
    kronos = _FakeKronos("TRENDING_BULLISH")

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

    # 1. Assert no pre-seeded observations exist
    assert len(bundle.db_manager.get_open_signal_observations("XAUUSDm")) == 0

    # 2. Assert nothing is published before observation is stored
    await bundle.runtime._poll_and_publish_once()  # type: ignore[attr-defined]
    assert len(sends) == 0

    # 3. Run Loop B on closed bar TS to create real observation
    obs = await bundle.loop_b.run_once(BAR_TS)
    assert obs is not None
    assert obs.order_type == "BUY"

    # 4. Assert open observation count increased by at least 1
    open_obs = bundle.db_manager.get_open_signal_observations("XAUUSDm")
    assert len(open_obs) >= 1

    # 5. Run publish cycle to push newly created observation
    await _run_publish_burst(bundle.runtime)

    # 6. Assert published observation reached admin with valid payload
    assert len(sends) >= 1
    for payload in sends:
        assert payload.get("chat_id") == ADMIN_CHAT_ID
        text = str(payload.get("text", "")).lower()
        for token in PROHIBITED_TOKENS:
            assert token not in text, f"Prohibited token '{token}' in payload: {text!r}"


# ---------------------------------------------------------------------------
# Test 2 & 3: Regime Invalidation Symmetry (CLOSED_REGIME)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_buy_regime_flip_to_trending_bearish_closes_regime(
    tmp_path: Any,
) -> None:
    """BUY observation must transition to CLOSED_REGIME when regime flips to TRENDING_BEARISH."""
    db_path = str(tmp_path / "trading.db")
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot([])
    evaluator = _DeterministicEvaluator(SignalType.BUY)
    kronos = _FakeKronos("TRENDING_BULLISH")

    bundle: RuntimeBundle = build_runtime_bundle(
        exness_client=exness,
        control_bot=control_bot,
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=db_path,
        symbol="XAUUSDm",
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
    )

    obs = await bundle.loop_b.run_once(BAR_TS)
    assert obs is not None and obs.order_type == "BUY" and obs.state == "OPEN"

    kronos.regime = "TRENDING_BEARISH"
    bundle.loop_b.kronos_engine.infer_regime([])

    tick = _make_tick(time_ts=BAR_TS + 60, bid=2000.0, ask=2000.2)
    changed = bundle.tracker.mark_to_market(obs, tick)
    assert changed is True

    with bundle.db_manager.get_connection() as conn:
        row = conn.execute(
            "SELECT state, exit_reason FROM signal_observations WHERE signal_id = ?",
            (obs.signal_id,),
        ).fetchone()
    assert row is not None
    assert row["state"] == "CLOSED_REGIME"
    assert row["exit_reason"] == "regime_invalidation"


@pytest.mark.asyncio
async def test_e2e_sell_regime_flip_to_trending_bullish_closes_regime(
    tmp_path: Any,
) -> None:
    """SELL observation must transition to CLOSED_REGIME when regime flips to TRENDING_BULLISH."""
    db_path = str(tmp_path / "trading.db")
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot([])
    evaluator = _DeterministicEvaluator(SignalType.SELL)
    kronos = _FakeKronos("TRENDING_BEARISH")

    bundle: RuntimeBundle = build_runtime_bundle(
        exness_client=exness,
        control_bot=control_bot,
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=db_path,
        symbol="XAUUSDm",
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
    )

    obs = await bundle.loop_b.run_once(BAR_TS)
    assert obs is not None and obs.order_type == "SELL" and obs.state == "OPEN"

    kronos.regime = "TRENDING_BULLISH"
    bundle.loop_b.kronos_engine.infer_regime([])

    tick = _make_tick(time_ts=BAR_TS + 60, bid=2000.0, ask=2000.2)
    changed = bundle.tracker.mark_to_market(obs, tick)
    assert changed is True

    with bundle.db_manager.get_connection() as conn:
        row = conn.execute(
            "SELECT state, exit_reason FROM signal_observations WHERE signal_id = ?",
            (obs.signal_id,),
        ).fetchone()
    assert row is not None
    assert row["state"] == "CLOSED_REGIME"
    assert row["exit_reason"] == "regime_invalidation"


# ---------------------------------------------------------------------------
# Test 4: Strategy adapter converts CandleDict to DataFrame
# ---------------------------------------------------------------------------


def test_e2e_strategy_adapter_converts_candle_dict_to_dataframe() -> None:
    """Verify _candle_dicts_to_df produces correct DataFrame without exception."""
    from engine.runtime.bootstrap import _VolatilityBreakoutAdapter

    candles = [
        CandleDict(
            timestamp_utc=_iso_utc(BAR_TS + i * 900),
            open=2000.0 + i,
            high=2002.0 + i,
            low=1998.0 + i,
            close=2001.0 + i,
            tick_volume=100,
        )
        for i in range(10)
    ]
    df = _candle_dicts_to_df(candles)

    assert isinstance(df, pd.DataFrame)
    expected_cols = ["timestamp_utc", "open", "high", "low", "close", "tick_volume"]
    for col in expected_cols:
        assert col in df.columns, f"Missing column: {col}"
    assert len(df) == 10

    adapter = _VolatilityBreakoutAdapter()
    result = adapter.evaluate_signals(candles, candles)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Test 5: No live order calls
# ---------------------------------------------------------------------------


def test_e2e_no_live_order_calls() -> None:
    """Confirm no order_send or PositionModify references exist in bootstrap or main."""
    import engine.main as main_module
    import engine.runtime.bootstrap as bootstrap_module

    forbidden = ("order_send", "PositionModify")
    for module in (bootstrap_module, main_module):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, f"Forbidden call '{token}' in {module.__name__}"


# ---------------------------------------------------------------------------
# Test 6 & 7: Logging audit assertions
# ---------------------------------------------------------------------------


def test_e2e_news_source_is_explicit(caplog: pytest.LogCaptureFixture) -> None:
    """Default news_events=None must log NEWS_SOURCE=NONE and NEWS_EVENT_COUNT=0."""
    from engine.runtime.bootstrap import _build_news_filter

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.bootstrap"):
        nf = _build_news_filter(None)

    assert nf.scheduled_events == []
    log_text = " ".join(caplog.messages)
    assert "NEWS_SOURCE=NONE" in log_text
    assert "NEWS_EVENT_COUNT=0" in log_text


def test_e2e_regime_source_is_explicit(
    caplog: pytest.LogCaptureFixture, tmp_path: Any
) -> None:
    """Bootstrap must log REGIME_SOURCE=KRONOS_MEMO."""
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot([])
    with caplog.at_level(logging.INFO, logger="aeterna.runtime.bootstrap"):
        build_runtime_bundle(
            exness_client=exness,
            control_bot=control_bot,
            admin_chat_id=ADMIN_CHAT_ID,
            db_path=str(tmp_path / "trading.db"),
            symbol="XAUUSDm",
        )
    assert "REGIME_SOURCE=KRONOS_MEMO" in caplog.text
