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
from engine.execution.broker_bridge import ExnessBrokerBridge, PartialCloseResult
from engine.execution.position_manager import PositionManager, PositionState
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


def _make_mock_control_bot(
    sends: list[dict[str, Any]],
    photos: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Return a TelegramControlBot mock that records send and send_photo calls."""
    mock = MagicMock()
    mock.send_initial_dashboard.return_value = True

    def _record_send(payload: dict[str, Any]) -> bool:
        sends.append(payload)
        return True

    def _record_send_photo(chat_id: int, photo: bytes, caption: str) -> bool:
        payload = {
            "method": "sendPhoto",
            "chat_id": chat_id,
            "photo": photo,
            "caption": caption,
            "text": caption,
        }
        sends.append(payload)
        if photos is not None:
            photos.append(payload)
        return True

    mock.send.side_effect = _record_send
    mock.send_photo.side_effect = _record_send_photo
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
        assert payload.get("method") == "sendPhoto"
        photo_bytes = payload.get("photo")
        assert isinstance(photo_bytes, bytes)
        assert photo_bytes != b"fake_image"
        assert photo_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert b"IHDR" in photo_bytes
        assert b"IDAT" in photo_bytes
        assert b"IEND" in photo_bytes
        assert b"XAUUSD OBSERVATION" in photo_bytes

        text = str(payload.get("text", "")).lower()
        for token in PROHIBITED_TOKENS:
            assert token not in text, f"Prohibited token '{token}' in payload: {text!r}"
        orig_text = str(payload.get("text", ""))
        assert "REASONING:" in orig_text
        assert "REGIME=" in orig_text
        assert "STRATEGY=" in orig_text
        assert "RR=" in orig_text
        assert "STATE=" in orig_text
        assert "NEWS=" in orig_text
        assert "SPREAD_Z=" in orig_text


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


@pytest.mark.asyncio
async def test_e2e_calendar_snapshot_injected_and_reasoning_blackout(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Calendar snapshot injected via bootstrap loads events and wires blackout reasoning."""
    import json
    from pathlib import Path

    snapshot_file = Path(tmp_path) / "mql5_calendar.json"
    snapshot_data = {
        "schema_version": 1,
        "source": "MQL5_CALENDAR",
        "source_timezone": "TRADE_SERVER",
        "exported_at_utc": "2023-11-14T00:00:00Z",
        "events": [
            {
                "event_id": "ev_001",
                "currency": "USD",
                "impact": "HIGH",
                "timestamp_utc": _iso_utc(BAR_TS),
                "name": "CPI m/m",
            },
            {
                "event_id": "ev_002",
                "currency": "USD",
                "impact": "HIGH",
                "timestamp_utc": _iso_utc(BAR_TS + 7200),
                "name": "FOMC Statement",
            },
        ],
    }
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    sends: list[dict[str, Any]] = []
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot(sends)
    evaluator = _DeterministicEvaluator(SignalType.BUY)
    kronos = _FakeKronos("TRENDING_BULLISH")

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.bootstrap"):
        bundle = build_runtime_bundle(
            exness_client=exness,
            control_bot=control_bot,
            admin_chat_id=ADMIN_CHAT_ID,
            db_path=str(tmp_path / "trading_snap.db"),
            symbol="XAUUSDm",
            strategy_evaluator=evaluator,  # type: ignore[arg-type]
            kronos_engine=kronos,  # type: ignore[arg-type]
            calendar_snapshot_path=str(snapshot_file),
            reasoning_enabled=True,
            publish_interval_seconds=0.1,
        )

    assert "NEWS_SOURCE=MQL5_SNAPSHOT" in caplog.text
    assert "NEWS_EVENT_COUNT=2" in caplog.text
    assert len(bundle.news_filter.scheduled_events) == 2

    obs = await bundle.loop_b.run_once(BAR_TS)
    assert obs is not None

    await _run_publish_burst(bundle.runtime)
    assert len(sends) >= 1
    for payload in sends:
        msg = str(payload.get("text", ""))
        assert "REASONING:" in msg
        assert "REGIME=TRENDING_BULLISH" in msg
        assert f"STRATEGY={type(evaluator).__name__}" in msg
        assert "RR=2.00" in msg
        assert "STATE=NORMAL" in msg
        assert "NEWS=BLACKOUT" in msg
        assert "SPREAD_Z=0.00" in msg
        msg_lower = msg.lower()
        for token in PROHIBITED_TOKENS:
            assert token not in msg_lower, f"Prohibited token '{token}' in msg: {msg!r}"


@pytest.mark.asyncio
async def test_e2e_reasoning_disabled_omits_reasoning(tmp_path: Any) -> None:
    """When reasoning_enabled=False, published card omits reasoning facts and shows NONE."""
    sends: list[dict[str, Any]] = []
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot(sends)
    evaluator = _DeterministicEvaluator(SignalType.BUY)
    kronos = _FakeKronos("TRENDING_BULLISH")

    bundle = build_runtime_bundle(
        exness_client=exness,
        control_bot=control_bot,
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=str(tmp_path / "trading_no_reas.db"),
        symbol="XAUUSDm",
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
        reasoning_enabled=False,
        publish_interval_seconds=0.1,
    )

    obs = await bundle.loop_b.run_once(BAR_TS)
    assert obs is not None

    await _run_publish_burst(bundle.runtime)
    assert len(sends) >= 1
    for payload in sends:
        msg = str(payload.get("text", ""))
        assert "REASONING: NONE" in msg
        assert "REGIME=" not in msg
        msg_lower = msg.lower()
        for token in PROHIBITED_TOKENS:
            assert token not in msg_lower, f"Prohibited token '{token}' in msg: {msg!r}"


def test_e2e_calendar_snapshot_missing_fallback(
    caplog: pytest.LogCaptureFixture, tmp_path: Any
) -> None:
    """Missing snapshot path logs NEWS_SOURCE=NONE and keeps runtime bundle valid."""
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot([])
    missing_file = str(tmp_path / "does_not_exist.json")

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.bootstrap"):
        bundle = build_runtime_bundle(
            exness_client=exness,
            control_bot=control_bot,
            admin_chat_id=ADMIN_CHAT_ID,
            db_path=str(tmp_path / "trading_missing.db"),
            symbol="XAUUSDm",
            calendar_snapshot_path=missing_file,
        )

    assert "NEWS_SOURCE=NONE" in caplog.text
    assert len(bundle.news_filter.scheduled_events) == 0


@pytest.mark.asyncio
async def test_e2e_chart_provider_excludes_forming_bar(tmp_path: Any) -> None:
    """Chart candle provider must filter out forming bar and keep only closed bars <= bar_ts."""
    db_path = str(tmp_path / "trading_forming.db")
    sends: list[dict[str, Any]] = []

    # _make_mock_exness returns 100 closed bars + 1 forming bar at bar_ts + 900
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot(sends)
    evaluator = _DeterministicEvaluator(SignalType.BUY)
    kronos = _FakeKronos("TRENDING_BULLISH")

    bundle = build_runtime_bundle(
        exness_client=exness,
        control_bot=control_bot,
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=db_path,
        symbol="XAUUSDm",
        strategy_evaluator=evaluator,  # type: ignore[arg-type]
        kronos_engine=kronos,  # type: ignore[arg-type]
        publish_interval_seconds=0.1,
    )

    assert bundle.runtime.chart_candle_provider is not None
    candles = bundle.runtime.chart_candle_provider(BAR_TS)
    assert len(candles) <= 120
    assert len(candles) == 100
    forming_ts_str = _iso_utc(BAR_TS + 900)
    for c in candles:
        assert c["timestamp_utc"] <= _iso_utc(BAR_TS)
        assert c["timestamp_utc"] != forming_ts_str


@pytest.mark.asyncio
async def test_e2e_chart_provider_empty_falls_back_to_text(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """When chart provider returns empty list, fallback to text and log CHART_UNAVAILABLE."""
    db_path = str(tmp_path / "trading_empty.db")
    sends: list[dict[str, Any]] = []

    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot(sends)
    evaluator = _DeterministicEvaluator(SignalType.BUY)
    kronos = _FakeKronos("TRENDING_BULLISH")

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.runtime_service"):
        bundle = build_runtime_bundle(
            exness_client=exness,
            control_bot=control_bot,
            admin_chat_id=ADMIN_CHAT_ID,
            db_path=db_path,
            symbol="XAUUSDm",
            strategy_evaluator=evaluator,  # type: ignore[arg-type]
            kronos_engine=kronos,  # type: ignore[arg-type]
            chart_candle_provider=lambda _ts: [],
            publish_interval_seconds=0.1,
        )

        obs = await bundle.loop_b.run_once(BAR_TS)
        assert obs is not None
        await _run_publish_burst(bundle.runtime)

    assert len(sends) >= 1
    assert "CHART_UNAVAILABLE=FALLBACK_TEXT" in caplog.text
    for payload in sends:
        assert payload.get("method") == "sendMessage"
        assert "photo" not in payload
        assert payload.get("chat_id") == ADMIN_CHAT_ID
        text = str(payload.get("text", "")).lower()
        for token in PROHIBITED_TOKENS:
            assert token not in text


@pytest.mark.asyncio
async def test_e2e_chart_provider_exception_falls_back_to_text(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """When chart provider raises an exception, fallback to text and log CHART_UNAVAILABLE."""
    db_path = str(tmp_path / "trading_exc.db")
    sends: list[dict[str, Any]] = []

    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot(sends)
    evaluator = _DeterministicEvaluator(SignalType.BUY)
    kronos = _FakeKronos("TRENDING_BULLISH")

    def _broken_provider(_ts: int) -> list[CandleDict]:
        raise RuntimeError("MT5 connection drop")

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.runtime_service"):
        bundle = build_runtime_bundle(
            exness_client=exness,
            control_bot=control_bot,
            admin_chat_id=ADMIN_CHAT_ID,
            db_path=db_path,
            symbol="XAUUSDm",
            strategy_evaluator=evaluator,  # type: ignore[arg-type]
            kronos_engine=kronos,  # type: ignore[arg-type]
            chart_candle_provider=_broken_provider,
            publish_interval_seconds=0.1,
        )

        obs = await bundle.loop_b.run_once(BAR_TS)
        assert obs is not None
        await _run_publish_burst(bundle.runtime)

    assert len(sends) >= 1
    assert "CHART_UNAVAILABLE=FALLBACK_TEXT" in caplog.text
    for payload in sends:
        assert payload.get("method") == "sendMessage"
        assert "photo" not in payload
        assert payload.get("chat_id") == ADMIN_CHAT_ID
        text = str(payload.get("text", "")).lower()
        for token in PROHIBITED_TOKENS:
            assert token not in text


# ---------------------------------------------------------------------------
# PositionManager M15 Closed Bar Wiring (TASK-RUNTIME-22)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_position_manager_default_disabled_no_bridge_call(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Default mode must keep execution_enabled=False, log DISABLED, and never call bridge."""
    db_path = str(tmp_path / "trading_pm_disabled.db")
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot([])

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = exness
    custom_pm = PositionManager(bridge=mock_bridge)
    test_pos = PositionState(
        ticket=1001,
        position_identifier=9001,
        symbol="XAUUSDm",
        direction="BUY",
        open_price=2000.0,
        current_lot=0.02,
        initial_sl=1990.0,
        current_sl=1990.0,
        tp=2020.0,
        initial_r_pts=10.0,
        spread_at_entry_usd=0.35,
        elapsed_bars_m15=7,
    )
    custom_pm.track_position(test_pos)

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.bootstrap"):
        bundle = build_runtime_bundle(
            exness_client=exness,
            control_bot=control_bot,
            admin_chat_id=ADMIN_CHAT_ID,
            db_path=db_path,
            symbol="XAUUSDm",
            position_manager=custom_pm,
            # execution_enabled left at default False
        )

    assert bundle.execution_enabled is False
    assert bundle.runtime.execution_enabled is False
    assert "POSITION_MANAGER_WIRING=DISABLED" in caplog.text

    # When evaluate_positions_once is called (even with bar_closed=True), disabled mode blocks execution
    results = await bundle.runtime.evaluate_positions_once(bar_closed=True)
    assert results == []
    mock_bridge.modify_position_sltp.assert_not_called()
    mock_bridge.close_partial_position.assert_not_called()


@pytest.mark.asyncio
async def test_e2e_position_manager_enabled_wiring_m15_close_only(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """When execution_enabled=True, evaluation occurs strictly on M15 close and liquidates at bar 8."""
    db_path = str(tmp_path / "trading_pm_enabled.db")
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot([])

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = exness
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=True,
        closed_ticket=1001,
        new_ticket=None,
        closed_lot=0.02,
        remaining_lot=0.0,
        executed_price=2000.0,
    )

    custom_pm = PositionManager(bridge=mock_bridge)
    test_pos = PositionState(
        ticket=1001,
        position_identifier=9001,
        symbol="XAUUSDm",
        direction="BUY",
        open_price=2000.0,
        current_lot=0.02,
        initial_sl=1990.0,
        current_sl=1990.0,
        tp=2020.0,
        initial_r_pts=10.0,
        spread_at_entry_usd=0.35,
        elapsed_bars_m15=6,
    )
    custom_pm.track_position(test_pos)

    with caplog.at_level(logging.INFO, logger="aeterna.runtime.bootstrap"):
        bundle = build_runtime_bundle(
            exness_client=exness,
            control_bot=control_bot,
            admin_chat_id=ADMIN_CHAT_ID,
            db_path=db_path,
            symbol="XAUUSDm",
            position_manager=custom_pm,
            execution_enabled=True,
        )

    assert bundle.execution_enabled is True
    assert bundle.runtime.execution_enabled is True
    assert "POSITION_MANAGER_WIRING=ENABLED" in caplog.text

    # 1. Regular tick (bar_closed=False): must NOT evaluate or increment counter
    res_tick = await bundle.runtime.evaluate_positions_once(bar_closed=False)
    assert res_tick == []
    active = custom_pm.get_active_positions()
    assert len(active) == 1
    assert active[0].elapsed_bars_m15 == 6
    mock_bridge.close_partial_position.assert_not_called()

    # 2. 7th bar closes (bar_closed=True): increments counter to 7, no liquidation
    res_bar7 = await bundle.runtime.evaluate_positions_once(bar_closed=True)
    assert len(res_bar7) == 1
    pos_7, _, close_7 = res_bar7[0]
    assert pos_7.elapsed_bars_m15 == 7
    assert close_7 is None
    assert PositionManager.is_time_invalidated(pos_7.elapsed_bars_m15) is False
    mock_bridge.close_partial_position.assert_not_called()

    # 3. 8th bar closes (bar_closed=True): increments to 8, triggers liquidation
    res_bar8 = await bundle.runtime.evaluate_positions_once(bar_closed=True)
    assert len(res_bar8) == 1
    pos_8, _, close_8 = res_bar8[0]
    assert pos_8.elapsed_bars_m15 == 8
    assert PositionManager.is_time_invalidated(pos_8.elapsed_bars_m15) is True
    assert close_8 is not None and close_8.success is True
    assert pos_8.current_lot == 0.0
    mock_bridge.close_partial_position.assert_called_once_with(
        ticket=1001,
        position_identifier=9001,
        symbol="XAUUSDm",
        direction="BUY",
        close_lot=0.02,
    )
    # Position untracked post full close
    assert len(custom_pm.get_active_positions()) == 0


@pytest.mark.asyncio
async def test_e2e_position_manager_m15_event_loop_a_integration(
    tmp_path: Any,
) -> None:
    """Verify _run_position_manager wakes up when loop_a.m15_event is signaled."""
    db_path = str(tmp_path / "trading_pm_event.db")
    exness = _make_mock_exness(BAR_TS)
    control_bot = _make_mock_control_bot([])

    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.client = exness
    custom_pm = PositionManager(bridge=mock_bridge)
    test_pos = PositionState(
        ticket=1001,
        position_identifier=9001,
        symbol="XAUUSDm",
        direction="BUY",
        open_price=2000.0,
        current_lot=0.02,
        initial_sl=1990.0,
        current_sl=1990.0,
        tp=2020.0,
        initial_r_pts=10.0,
        spread_at_entry_usd=0.35,
        elapsed_bars_m15=0,
    )
    custom_pm.track_position(test_pos)

    bundle = build_runtime_bundle(
        exness_client=exness,
        control_bot=control_bot,
        admin_chat_id=ADMIN_CHAT_ID,
        db_path=db_path,
        symbol="XAUUSDm",
        position_manager=custom_pm,
        execution_enabled=True,
    )

    stop_event = asyncio.Event()
    pm_task = asyncio.create_task(
        bundle.runtime._run_position_manager(bundle.loop_a.m15_event, stop_event)
    )

    # Let task enter wait
    await asyncio.sleep(0.05)
    assert custom_pm.get_active_positions()[0].elapsed_bars_m15 == 0

    # Signal M15 close from Loop A
    bundle.loop_a.m15_event.set()
    await asyncio.sleep(0.05)

    # Position should have advanced by 1 bar
    assert custom_pm.get_active_positions()[0].elapsed_bars_m15 == 1

    # Cleanup
    stop_event.set()
    bundle.loop_a.m15_event.set()
    await asyncio.wait_for(pm_task, timeout=2.0)
