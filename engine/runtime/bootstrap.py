"""Signal-only runtime dependency composition and bundle factory.

Module: engine.runtime.bootstrap
Responsibility: Compose all runtime dependencies (ExnessClient, DatabaseManager,
    SpreadFilter, NewsCalendarFilter, NewsStateMachine, KronosH4RegimeEngine,
    strategy adapter, Loop A/B, VirtualSignalTracker, SignalOnlyDashboard,
    RuntimeService) into an immutable RuntimeBundle via build_runtime_bundle().
Owner: aeterna-architect
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from engine.analysis_engine.python.interfaces import (
    KronosInferenceEngine,
    StrategyEvaluator,
)
from engine.analysis_engine.python.types import CandleDict
from engine.execution.broker_bridge import ExnessBrokerBridge
from engine.execution.position_manager import PositionManager
from engine.ingestion.python.exness_client import ExnessClient
from engine.models.kronos.inference import KronosH4RegimeEngine
from engine.runtime.dashboard import SignalOnlyDashboard
from engine.runtime.loop_a import FastTickLoopA
from engine.runtime.loop_b import AnalysisLoopB
from engine.runtime.news_sources import load_calendar_snapshot
from engine.runtime.runtime_service import RuntimeService
from engine.runtime.virtual_tracker import VirtualSignalTracker
from engine.shared.db.database import DatabaseManager
from engine.state_machine.news_filter import NewsCalendarFilter
from engine.state_machine.spread_filter import SpreadFilter
from engine.state_machine.state_machine import NewsStateMachine
from engine.telegram_bot.client import TelegramControlBot
from instruments.xauusd.strategies.volatility_breakout import (
    SignalType,
    VolatilityBreakoutStrategy,
)

logger = logging.getLogger("aeterna.runtime.bootstrap")

_REQUIRED_DF_COLUMNS = ["timestamp_utc", "open", "high", "low", "close", "tick_volume"]
_SPREAD_FILTER_MIN_STD_DEV = 0.5  # ADR-016
_REGIME_NORMALIZATION: dict[str, str] = {
    "BULLISH_TRENDING": "TRENDING_BULLISH",
    "BEARISH_TRENDING": "TRENDING_BEARISH",
}


# ---------------------------------------------------------------------------
# Strategy adapter
# ---------------------------------------------------------------------------


class _VolatilityBreakoutAdapter:
    """Adapts CandleDict lists to VolatilityBreakoutStrategy.evaluate_signal(DataFrame)."""

    def __init__(self) -> None:
        self._strategy = VolatilityBreakoutStrategy()

    def evaluate_signals(
        self,
        m15_candles: list[CandleDict],
        h4_candles: list[CandleDict],
        macro: Any = None,
        sentiment: Any = None,
    ) -> list[Any]:
        """Convert CandleDict → DataFrame, call evaluate_signal, filter NO_SIGNAL."""
        try:
            m15_df = _candle_dicts_to_df(m15_candles)
            h4_df = _candle_dicts_to_df(h4_candles)
            signal = self._strategy.evaluate_signal(m15_df, h4_df)
            if signal.signal_type is SignalType.NO_SIGNAL:
                return []
            return [signal]
        except Exception:
            logger.exception("strategy_adapter: evaluate_signal failed; returning []")
            return []


def _candle_dicts_to_df(candles: list[CandleDict]) -> pd.DataFrame:
    """Convert a list of CandleDict to a pandas DataFrame with canonical columns."""
    rows = [
        {
            "timestamp_utc": c["timestamp_utc"],
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "tick_volume": float(c["tick_volume"]),
        }
        for c in candles
    ]
    df = pd.DataFrame(rows, columns=_REQUIRED_DF_COLUMNS)
    return df.reset_index(drop=True)


def _iso_utc(epoch_seconds: int) -> str:
    """Format epoch seconds as canonical UTC candle timestamp."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_candle_dict(candle: Any) -> CandleDict:
    """Adapt a CandleRecord or mapping into a CandleDict."""
    if isinstance(candle, dict):
        return CandleDict(
            timestamp_utc=str(candle["timestamp_utc"]),
            open=float(candle["open"]),
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
            tick_volume=int(candle["tick_volume"]),
        )
    return CandleDict(
        timestamp_utc=str(candle.timestamp_utc),
        open=float(candle.open),
        high=float(candle.high),
        low=float(candle.low),
        close=float(candle.close),
        tick_volume=int(candle.tick_volume),
    )


def _build_chart_candle_provider(
    exness_client: Any,
) -> Callable[[int], list[CandleDict]]:
    """Build chart candle provider querying ExnessClient up to closed bar_ts."""

    def _provider(bar_ts: int) -> list[CandleDict]:
        cutoff_str = _iso_utc(bar_ts)
        lock = getattr(exness_client, "lock", None)
        if lock is not None:
            with lock:
                records = exness_client.fetch_recent_candles("M15", 121)
        else:
            records = exness_client.fetch_recent_candles("M15", 121)

        if not records:
            return []

        closed = [
            _to_candle_dict(c)
            for c in records
            if (
                c.get("timestamp_utc", "")
                if isinstance(c, dict)
                else getattr(c, "timestamp_utc", "")
            )
            <= cutoff_str
        ]
        return closed[-120:]

    return _provider


# ---------------------------------------------------------------------------
# Kronos regime memo wrapper
# ---------------------------------------------------------------------------


class _KronosRegimeMemoWrapper:
    """Memoizes the latest regime inferred by Kronos for downstream consumers."""

    def __init__(
        self,
        inner: KronosInferenceEngine,
        initial_regime: str = "RANGING",
    ) -> None:
        self._inner = inner
        self._last_regime: str = initial_regime

    @property
    def last_regime(self) -> str:
        return self._last_regime

    def get_regime(self) -> str:
        return self._last_regime

    def infer_regime(self, context_candles: list[CandleDict]) -> Any:
        result = self._inner.infer_regime(context_candles)
        raw_regime = str(result.regime)
        normalized = _REGIME_NORMALIZATION.get(raw_regime, raw_regime)
        self._last_regime = normalized
        return result

    def validate_context_window(self, candles: list[CandleDict]) -> bool:
        return self._inner.validate_context_window(candles)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# RuntimeBundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeBundle:
    """Immutable composition of all runtime components."""

    runtime: RuntimeService
    loop_a: FastTickLoopA
    loop_b: AnalysisLoopB
    tracker: VirtualSignalTracker
    dashboard: SignalOnlyDashboard
    db_manager: DatabaseManager
    state_machine: NewsStateMachine
    news_filter: NewsCalendarFilter
    position_manager: PositionManager | None = None
    execution_enabled: bool = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _build_loops_and_tracker(
    exness_client: ExnessClient,
    state_machine: NewsStateMachine,
    db_manager: DatabaseManager,
    effective_kronos: KronosInferenceEngine,
    effective_evaluator: StrategyEvaluator,
    symbol: str,
    poll_interval_seconds: float,
) -> tuple[FastTickLoopA, AnalysisLoopB, VirtualSignalTracker]:
    """Instantiate Loop A, Loop B, and VirtualSignalTracker with Kronos memo."""
    m15_event = asyncio.Event()
    kronos_memo = _KronosRegimeMemoWrapper(effective_kronos)
    logger.info("REGIME_SOURCE=KRONOS_MEMO")

    loop_a = FastTickLoopA(
        exness_client=exness_client,
        state_machine=state_machine,
        db_manager=db_manager,
        m15_event=m15_event,
        symbol=symbol,
        poll_interval_seconds=poll_interval_seconds,
    )
    loop_b = AnalysisLoopB(
        exness_client=exness_client,
        kronos_engine=kronos_memo,
        strategy_evaluator=effective_evaluator,
        state_machine=state_machine,
        db_manager=db_manager,
        symbol=symbol,
    )
    tracker = VirtualSignalTracker(
        exness_client=exness_client,
        db_manager=db_manager,
        regime_provider=kronos_memo.get_regime,
        symbol=symbol,
        poll_interval_seconds=poll_interval_seconds,
    )
    return loop_a, loop_b, tracker


_DEFAULT_PROVIDER: Any = object()


def build_runtime_bundle(
    *,
    exness_client: ExnessClient,
    control_bot: TelegramControlBot,
    admin_chat_id: int,
    db_path: str = "data/trading.db",
    symbol: str = "XAUUSDm",
    model_path: str = "data/models/kronos_h4.onnx",
    poll_interval_seconds: float = 2.0,
    publish_interval_seconds: float = 5.0,
    news_events: Sequence[datetime] | None = None,
    calendar_snapshot_path: str | None = None,
    reasoning_enabled: bool = True,
    strategy_evaluator: StrategyEvaluator | None = None,
    kronos_engine: KronosInferenceEngine | None = None,
    chart_candle_provider: Callable[[int], list[CandleDict]] | None = _DEFAULT_PROVIDER,
    position_manager: PositionManager | None = None,
    execution_enabled: bool = False,
) -> RuntimeBundle:
    """Compose and return the immutable signal-only RuntimeBundle.

    All dependencies are injected; tests can pass mocks for every component.
    No real order is ever sent; mode is strictly SIGNAL_ONLY.
    """
    logger.info(
        "POSITION_MANAGER_WIRING=%s",
        "ENABLED" if execution_enabled else "DISABLED",
    )
    news_filter = _build_news_filter(
        events=news_events,
        calendar_snapshot_path=calendar_snapshot_path,
    )
    spread_filter = SpreadFilter(min_std_dev=_SPREAD_FILTER_MIN_STD_DEV)
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_db()

    state_machine = NewsStateMachine(
        spread_filter=spread_filter,
        news_filter=news_filter,
        db_manager=db_manager,
    )
    effective_kronos = _build_kronos(kronos_engine, model_path)
    effective_evaluator: StrategyEvaluator = (
        strategy_evaluator
        if strategy_evaluator is not None
        else _VolatilityBreakoutAdapter()  # type: ignore[assignment]
    )

    loop_a, loop_b, tracker = _build_loops_and_tracker(
        exness_client=exness_client,
        state_machine=state_machine,
        db_manager=db_manager,
        effective_kronos=effective_kronos,
        effective_evaluator=effective_evaluator,
        symbol=symbol,
        poll_interval_seconds=poll_interval_seconds,
    )

    dashboard = SignalOnlyDashboard(
        client=control_bot,
        admin_chat_id=admin_chat_id,
        reasoning_enabled=reasoning_enabled,
        state_machine=state_machine,
        db_manager=db_manager,
        regime_provider=tracker.regime_provider,
    )
    effective_candle_provider: Callable[[int], list[CandleDict]] | None
    if chart_candle_provider is _DEFAULT_PROVIDER:
        effective_candle_provider = _build_chart_candle_provider(exness_client)
    else:
        effective_candle_provider = chart_candle_provider

    effective_position_manager: PositionManager
    if position_manager is not None:
        effective_position_manager = position_manager
    else:
        bridge = ExnessBrokerBridge(client=exness_client)
        effective_position_manager = PositionManager(bridge=bridge)

    runtime = RuntimeService(
        loop_a=loop_a,
        loop_b=loop_b,
        virtual_tracker=tracker,
        dashboard=dashboard,
        db_manager=db_manager,
        symbol=symbol,
        publish_interval_seconds=publish_interval_seconds,
        chart_candle_provider=effective_candle_provider,
        position_manager=effective_position_manager,
        execution_enabled=execution_enabled,
    )

    return RuntimeBundle(
        runtime=runtime,
        loop_a=loop_a,
        loop_b=loop_b,
        tracker=tracker,
        dashboard=dashboard,
        db_manager=db_manager,
        state_machine=state_machine,
        news_filter=news_filter,
        position_manager=effective_position_manager,
        execution_enabled=execution_enabled,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_news_filter(
    events: Sequence[datetime] | None = None,
    calendar_snapshot_path: str | None = None,
) -> NewsCalendarFilter:
    """Create NewsCalendarFilter; log NEWS_SOURCE and NEWS_EVENT_COUNT."""
    all_events: list[datetime] = []
    has_snapshot = False

    if calendar_snapshot_path is not None:
        snapshot_events = load_calendar_snapshot(calendar_snapshot_path)
        all_events.extend(snapshot_events)
        has_snapshot = True

    if events is not None:
        all_events.extend(events)

    if not all_events and not has_snapshot and events is None:
        logger.info("NEWS_SOURCE=NONE NEWS_EVENT_COUNT=0")
        return NewsCalendarFilter(events=None)

    news_filter = NewsCalendarFilter(events=all_events)
    count = len(news_filter.scheduled_events)
    if has_snapshot:
        if count > 0:
            logger.info("NEWS_SOURCE=MQL5_SNAPSHOT NEWS_EVENT_COUNT=%d", count)
        else:
            logger.info("NEWS_SOURCE=NONE NEWS_EVENT_COUNT=0")
    elif events is not None:
        logger.info("NEWS_SOURCE=INJECTED NEWS_EVENT_COUNT=%d", count)
    else:
        logger.info("NEWS_SOURCE=NONE NEWS_EVENT_COUNT=0")
    return news_filter


def _build_kronos(
    kronos_engine: KronosInferenceEngine | None,
    model_path: str,
) -> KronosInferenceEngine:
    """Return injected engine or build KronosH4RegimeEngine with fallback heuristic."""
    if kronos_engine is not None:
        return kronos_engine

    model_file = Path(model_path)
    if not model_file.is_file():
        logger.info(
            "MODEL_FALLBACK=HEURISTIC reason=model_file_not_found path=%s", model_path
        )
        return KronosH4RegimeEngine(model_path=None)

    try:
        engine = KronosH4RegimeEngine(model_path=str(model_file))
        logger.info("KronosH4RegimeEngine loaded model_path=%s", model_path)
        return engine
    except (FileNotFoundError, RuntimeError) as exc:
        logger.info("MODEL_FALLBACK=HEURISTIC reason=%s", exc)
        return KronosH4RegimeEngine(model_path=None)
