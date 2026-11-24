"""Module: engine.runtime.restart_replay
Responsibility: Detect M15 restart downtime gaps and orchestrate STRATEGY_ONLY replay.
Owner: aeterna-runtime
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, cast

import yaml

from engine.analysis_engine.python.interfaces import (
    KronosInferenceEngine,
    StrategyEvaluator,
)
from engine.analysis_engine.python.types import CandleDict
from engine.models import (
    BarCursorRecord,
    BlockedSignalRecord,
    CandleRecord,
    ReplayRunRecord,
    SignalObservationRecord,
    Timeframe,
    TradeDirection,
)
from engine.shared.db.database import DatabaseManager
from instruments.xauusd.strategies.volatility_breakout import SignalType

logger = logging.getLogger("aeterna.runtime.restart_replay")

M15_SECONDS = 900
H4_SECONDS = 14_400
RESTART_REPLAY_MAX_BARS_APPROVED = 32
DEFAULT_CANONICAL_CONFIG_PATH = Path("instruments/xauusd/config/parameters.yaml")


class GapStatus(str, Enum):
    """Lifecycle status emitted by gap detection and recovery."""

    NO_BASELINE = "NO_BASELINE"
    NO_GAP = "NO_GAP"
    NEGATIVE_GAP = "NEGATIVE_GAP"
    GAP_TOO_LARGE = "GAP_TOO_LARGE"
    CONFIG_DRIFT = "CONFIG_DRIFT"
    MISSING_CANDLES = "MISSING_CANDLES"
    REPLAY_REQUIRED = "REPLAY_REQUIRED"


class MissingCandlesError(Exception):
    """Raised when historical candles are incomplete or non-contiguous."""


class SignalLike(Protocol):
    """Minimal shape of a candidate trading signal from strategy evaluation."""

    signal_type: SignalType
    entry_price: float
    stop_loss: float
    take_profit: float


@dataclass(frozen=True)
class RestartReplayConfig:
    """Runtime configuration for restart gap detection and replay."""

    replay_mode: str
    max_bars: int

    def __post_init__(self) -> None:
        if self.replay_mode not in ("auto", "off", "dry_run"):
            raise ValueError(
                f"CONFIG_ERROR: RESTART_REPLAY_MODE must be explicit ('auto', 'off', 'dry_run'), "
                f"got {self.replay_mode!r}"
            )
        if self.max_bars != RESTART_REPLAY_MAX_BARS_APPROVED:
            raise ValueError(
                f"CONFIG_ERROR: RESTART_REPLAY_MAX_BARS policy mismatch. "
                f"Operator decision required. Expected {RESTART_REPLAY_MAX_BARS_APPROVED}, got {self.max_bars!r}"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RestartReplayConfig:
        """Parse configuration strictly from environment variables without inventing defaults."""
        source = os.environ if env is None else env
        mode = source.get("RESTART_REPLAY_MODE")
        if not mode:
            raise ValueError(
                "CONFIG_ERROR: RESTART_REPLAY_MODE is missing. Operator decision required."
            )
        raw_max = source.get("RESTART_REPLAY_MAX_BARS")
        if raw_max is None:
            raise ValueError(
                "CONFIG_ERROR: RESTART_REPLAY_MAX_BARS policy mismatch. Operator decision required."
            )
        try:
            max_bars = int(raw_max)
        except (ValueError, TypeError):
            raise ValueError(
                f"CONFIG_ERROR: RESTART_REPLAY_MAX_BARS policy mismatch. "
                f"Operator decision required. Expected {RESTART_REPLAY_MAX_BARS_APPROVED}, got {raw_max!r}"
            )
        return cls(replay_mode=mode, max_bars=max_bars)


@dataclass(frozen=True)
class GapDetectionResult:
    """Deterministic result of downtime gap evaluation."""

    status: GapStatus
    current_closed_bar_ts: int
    last_cursor_bar_ts: int | None
    first_missed_bar_ts: int | None
    last_missed_bar_ts: int | None
    missed_count: int
    config_hash: str
    error_text: str | None = None


@dataclass(frozen=True)
class ReplaySummary:
    """Execution summary emitted after restart recovery concludes."""

    symbol: str
    replay_id: str | None
    status: str
    missed_count: int
    replayed_count: int
    observations_created: int
    blocked_created: int
    replay_mode: str
    duration_seconds: float
    first_missed_bar_ts: int | None
    last_missed_bar_ts: int | None
    error_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert summary to dictionary for notifications or audit logs."""
        return {
            "symbol": self.symbol,
            "replay_id": self.replay_id,
            "status": self.status,
            "missed_count": self.missed_count,
            "replayed_count": self.replayed_count,
            "observations_created": self.observations_created,
            "blocked_created": self.blocked_created,
            "replay_mode": self.replay_mode,
            "duration_seconds": self.duration_seconds,
            "first_missed_bar_ts": self.first_missed_bar_ts,
            "last_missed_bar_ts": self.last_missed_bar_ts,
            "error_text": self.error_text,
        }

    def format_admin_message(self) -> str:
        """Format single Telegram summary message matching Contract §10."""
        first_str = (
            _iso_utc(self.first_missed_bar_ts) if self.first_missed_bar_ts else "N/A"
        )
        last_str = (
            _iso_utc(self.last_missed_bar_ts) if self.last_missed_bar_ts else "N/A"
        )
        return (
            f"[AETERNA REPLAY AUDIT]\n"
            f"Symbol: {self.symbol}\n"
            f"Downtime Gap: {first_str} -> {last_str}\n"
            f"Missed Bars: {self.missed_count}\n"
            f"Replayed: {self.replayed_count}\n"
            f"Observations Created: {self.observations_created}\n"
            f"Blocked Created: {self.blocked_created}\n"
            f"Replay Mode: {self.replay_mode}\n"
            f"Status: {self.status}\n"
            f"Duration: {self.duration_seconds:.2f}s"
        )


def _iso_utc(epoch_seconds: int) -> str:
    """Format epoch seconds as canonical UTC candle timestamp."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_to_epoch(ts: str) -> int:
    """Parse ISO UTC timestamp string into epoch seconds."""
    dt = datetime.fromisoformat(ts)
    return int(dt.timestamp())


def compute_config_hash(config_path: str | Path | None = None) -> str:
    """Compute deterministic SHA-256 digest of canonical configuration parameters."""
    target_path = Path(config_path) if config_path else DEFAULT_CANONICAL_CONFIG_PATH
    if not target_path.is_file():
        raise FileNotFoundError(f"Canonical parameters file not found at: {target_path}")
    raw_text = target_path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(raw_text)
        if isinstance(parsed, dict):
            canonical_json = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    except (yaml.YAMLError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Could not canonicalize yaml parameters: %s", exc)
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def compute_current_closed_bar(now_utc: float) -> int:
    """Calculate the latest fully closed M15 candle timestamp available at now_utc."""
    return (math.floor(now_utc / M15_SECONDS) * M15_SECONDS) - M15_SECONDS


def detect_gap(
    *,
    now_utc: float,
    last_cursor: BarCursorRecord | None,
    current_config_hash: str,
    max_replay_bars: int = RESTART_REPLAY_MAX_BARS_APPROVED,
) -> GapDetectionResult:
    """Pure mathematical detection of downtime gaps per Contract §2.3 and §3."""
    current_closed = compute_current_closed_bar(now_utc)
    if last_cursor is None:
        return GapDetectionResult(
            status=GapStatus.NO_BASELINE,
            current_closed_bar_ts=current_closed,
            last_cursor_bar_ts=None,
            first_missed_bar_ts=None,
            last_missed_bar_ts=None,
            missed_count=0,
            config_hash=current_config_hash,
        )

    last_ts = last_cursor.last_closed_bar_ts
    if current_closed < last_ts:
        return GapDetectionResult(
            status=GapStatus.NEGATIVE_GAP,
            current_closed_bar_ts=current_closed,
            last_cursor_bar_ts=last_ts,
            first_missed_bar_ts=None,
            last_missed_bar_ts=None,
            missed_count=0,
            config_hash=current_config_hash,
            error_text=f"Negative gap detected: current_closed={current_closed} < cursor={last_ts}",
        )

    if (
        last_cursor.config_hash is not None
        and last_cursor.config_hash != current_config_hash
    ):
        first_missed = last_ts + M15_SECONDS
        last_missed = current_closed
        count = max(0, ((last_missed - first_missed) // M15_SECONDS) + 1)
        return GapDetectionResult(
            status=GapStatus.CONFIG_DRIFT,
            current_closed_bar_ts=current_closed,
            last_cursor_bar_ts=last_ts,
            first_missed_bar_ts=first_missed if count > 0 else None,
            last_missed_bar_ts=last_missed if count > 0 else None,
            missed_count=count,
            config_hash=current_config_hash,
            error_text=(
                f"Config drift detected: cursor.config_hash={last_cursor.config_hash} "
                f"!= current_config_hash={current_config_hash}"
            ),
        )

    if current_closed == last_ts:
        return GapDetectionResult(
            status=GapStatus.NO_GAP,
            current_closed_bar_ts=current_closed,
            last_cursor_bar_ts=last_ts,
            first_missed_bar_ts=None,
            last_missed_bar_ts=None,
            missed_count=0,
            config_hash=current_config_hash,
        )

    first_missed = last_ts + M15_SECONDS
    last_missed = current_closed
    missed_count = ((last_missed - first_missed) // M15_SECONDS) + 1

    if missed_count > max_replay_bars:
        return GapDetectionResult(
            status=GapStatus.GAP_TOO_LARGE,
            current_closed_bar_ts=current_closed,
            last_cursor_bar_ts=last_ts,
            first_missed_bar_ts=first_missed,
            last_missed_bar_ts=last_missed,
            missed_count=missed_count,
            config_hash=current_config_hash,
            error_text=(
                f"Gap too large: missed_count={missed_count} exceeds "
                f"max_replay_bars={max_replay_bars}"
            ),
        )

    return GapDetectionResult(
        status=GapStatus.REPLAY_REQUIRED,
        current_closed_bar_ts=current_closed,
        last_cursor_bar_ts=last_ts,
        first_missed_bar_ts=first_missed,
        last_missed_bar_ts=last_missed,
        missed_count=missed_count,
        config_hash=current_config_hash,
    )


def _to_candle_record(c: Any) -> CandleRecord:
    """Normalize input candle object or mapping into a domain CandleRecord."""
    if isinstance(c, CandleRecord):
        return c
    if isinstance(c, dict):
        return CandleRecord(
            pair=str(c.get("pair") or "XAUUSDm"),
            timeframe=cast(Timeframe, c.get("timeframe") or "M15"),
            timestamp_utc=str(c.get("timestamp_utc") or ""),
            source="exness_mt5",
            open=float(cast(float, c.get("open", 0.0))),
            high=float(cast(float, c.get("high", 0.0))),
            low=float(cast(float, c.get("low", 0.0))),
            close=float(cast(float, c.get("close", 0.0))),
            tick_volume=int(cast(int, c.get("tick_volume", 0))),
        )
    return CandleRecord(
        pair=str(getattr(c, "pair", "XAUUSDm")),
        timeframe=cast(Timeframe, getattr(c, "timeframe", "M15")),
        timestamp_utc=str(getattr(c, "timestamp_utc", "")),
        source="exness_mt5",
        open=float(cast(float, getattr(c, "open", 0.0))),
        high=float(cast(float, getattr(c, "high", 0.0))),
        low=float(cast(float, getattr(c, "low", 0.0))),
        close=float(cast(float, getattr(c, "close", 0.0))),
        tick_volume=int(cast(int, getattr(c, "tick_volume", 0))),
    )


def _to_candle_dict(candle: CandleRecord) -> CandleDict:
    """Convert a domain CandleRecord into a CandleDict for inference."""
    return CandleDict(
        timestamp_utc=candle.timestamp_utc,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        tick_volume=candle.tick_volume,
    )


class RestartReplayEngine:
    """Deterministic STRATEGY_ONLY restart gap replay engine."""

    def __init__(
        self,
        exness_client: Any,
        db_manager: DatabaseManager,
        kronos_engine: KronosInferenceEngine,
        strategy_evaluator: StrategyEvaluator,
        config: RestartReplayConfig,
        symbol: str = "XAUUSDm",
        bar_lookback_m15: int = 100,
        bar_lookback_h4: int = 512,
        min_rr_ratio: float = 2.0,
        virtual_lot: float = 0.01,
        config_path: str | Path | None = None,
    ) -> None:
        if bar_lookback_m15 <= 0 or bar_lookback_h4 <= 0:
            raise ValueError("Lookback counts must be positive")
        if min_rr_ratio <= 0.0:
            raise ValueError("min_rr_ratio must be positive")

        self.exness_client = exness_client
        self.db_manager = db_manager
        self.kronos_engine = kronos_engine
        self.strategy_evaluator = strategy_evaluator
        self.config = config
        self.symbol = symbol
        self.bar_lookback_m15 = int(bar_lookback_m15)
        self.bar_lookback_h4 = int(bar_lookback_h4)
        self.min_rr_ratio = float(min_rr_ratio)
        self.virtual_lot = float(virtual_lot)
        self.config_path = config_path
        self.config_hash = compute_config_hash(config_path)
        self.strategy_id = type(strategy_evaluator).__name__
        self.model_id = str(getattr(kronos_engine, "model_id", "kronos_h4"))

    def cleanup_interrupted_runs(self, now_utc: float | None = None) -> int:
        """Transition any previously dangling RUNNING runs to INTERRUPTED."""
        ts = int(time.time()) if now_utc is None else int(now_utc)
        iso_ts = _iso_utc(ts)
        running_runs = self.db_manager.list_replay_runs_by_status("RUNNING")
        for run in running_runs:
            self.db_manager.update_replay_run_status(
                replay_id=run.replay_id,
                status="INTERRUPTED",
                finished_at_utc=iso_ts,
                error_text="Process interrupted prior to completion",
            )
            logger.warning(
                "Dangling replay run %s transitioned to INTERRUPTED",
                run.replay_id,
            )
        return len(running_runs)

    def detect_gap(self, now_utc: float | None = None) -> GapDetectionResult:
        """Run pure gap detection using current database cursor and config fingerprint."""
        now_ts = float(time.time() if now_utc is None else now_utc)
        cursor = self.db_manager.get_bar_cursor(self.symbol, "M15")
        return detect_gap(
            now_utc=now_ts,
            last_cursor=cursor,
            current_config_hash=self.config_hash,
            max_replay_bars=self.config.max_bars,
        )

    def _summary(
        self,
        status: str,
        missed: int,
        replayed: int,
        obs: int,
        blocked: int,
        start_mono: float,
        first_missed: int | None,
        last_missed: int | None,
        err: str | None = None,
        replay_id: str | None = None,
    ) -> ReplaySummary:
        """Construct immutable ReplaySummary dataclass instance."""
        return ReplaySummary(
            symbol=self.symbol,
            replay_id=replay_id,
            status=status,
            missed_count=missed,
            replayed_count=replayed,
            observations_created=obs,
            blocked_created=blocked,
            replay_mode=self.config.replay_mode,
            duration_seconds=time.monotonic() - start_mono,
            first_missed_bar_ts=first_missed,
            last_missed_bar_ts=last_missed,
            error_text=err,
        )

    def run_recovery(self, now_utc: float | None = None) -> ReplaySummary:
        """Execute full startup gap recovery routine before Loop B starts live."""
        start_mono = time.monotonic()
        now_ts = float(time.time() if now_utc is None else now_utc)
        self.cleanup_interrupted_runs(now_ts)

        detection = self.detect_gap(now_ts)
        if detection.status == GapStatus.NO_BASELINE:
            self.db_manager.advance_bar_cursor_with_config_hash(
                symbol=self.symbol,
                timeframe="M15",
                last_closed_bar_ts=detection.current_closed_bar_ts,
                config_hash=self.config_hash,
            )
            logger.warning(
                "NO_BASELINE_INITIALIZED symbol=%s baseline_ts=%d",
                self.symbol,
                detection.current_closed_bar_ts,
            )
            return self._summary(
                GapStatus.NO_BASELINE.value, 0, 0, 0, 0, start_mono, None, None
            )

        if detection.status == GapStatus.NO_GAP:
            return self._summary(
                GapStatus.NO_GAP.value, 0, 0, 0, 0, start_mono, None, None
            )

        if detection.status in (
            GapStatus.NEGATIVE_GAP,
            GapStatus.GAP_TOO_LARGE,
            GapStatus.CONFIG_DRIFT,
        ):
            logger.error(
                "Replay recovery blocked status=%s error=%s",
                detection.status,
                detection.error_text,
            )
            return self._summary(
                detection.status.value,
                detection.missed_count,
                0,
                0,
                0,
                start_mono,
                detection.first_missed_bar_ts,
                detection.last_missed_bar_ts,
                detection.error_text,
            )

        if self.config.replay_mode == "off":
            err = "REPLAY_REQUIRED but RESTART_REPLAY_MODE is 'off'"
            logger.error("%s", err)
            return self._summary(
                "BLOCKED",
                detection.missed_count,
                0,
                0,
                0,
                start_mono,
                detection.first_missed_bar_ts,
                detection.last_missed_bar_ts,
                err,
            )

        return self._execute_replay(detection, start_mono)

    def _execute_replay(
        self, detection: GapDetectionResult, start_mono: float
    ) -> ReplaySummary:
        """Orchestrate bar-by-bar chronological replay from oldest to newest."""
        replay_id = f"replay:{self.symbol}:{int(time.time())}:{uuid.uuid4().hex[:8]}"
        first_missed = detection.first_missed_bar_ts
        last_missed = detection.last_missed_bar_ts
        if first_missed is None or last_missed is None:
            raise ValueError("first_missed and last_missed must not be None")

        if self.config.replay_mode != "dry_run":
            record = ReplayRunRecord(
                replay_id=replay_id,
                symbol=self.symbol,
                timeframe="M15",
                last_cursor_ts=detection.last_cursor_bar_ts or 0,
                first_missed_bar_ts=first_missed,
                last_missed_bar_ts=last_missed,
                missed_count=detection.missed_count,
                started_at_utc=_iso_utc(int(time.time())),
                status="RUNNING",
                replay_mode="STRATEGY_ONLY",
                config_hash=self.config_hash,
                strategy_id=self.strategy_id,
                model_id=self.model_id,
            )
            self.db_manager.create_replay_run(record)

        replayed_count = 0
        obs_created = 0
        blocked_created = 0
        current_bar = first_missed

        while current_bar <= last_missed:
            try:
                obs_c, blk_c = self._replay_bar(current_bar, replay_id)
                obs_created += obs_c
                blocked_created += blk_c
                replayed_count += 1
            except MissingCandlesError as exc:
                return self._abort_replay(
                    replay_id,
                    GapStatus.MISSING_CANDLES.value,
                    f"MISSING_CANDLES: {exc}",
                    detection.missed_count,
                    replayed_count,
                    obs_created,
                    blocked_created,
                    first_missed,
                    last_missed,
                    start_mono,
                )
            except Exception as exc:  # noqa: BLE001
                return self._abort_replay(
                    replay_id,
                    "BLOCKED",
                    f"Error replaying bar {current_bar}: {exc}",
                    detection.missed_count,
                    replayed_count,
                    obs_created,
                    blocked_created,
                    first_missed,
                    last_missed,
                    start_mono,
                )
            current_bar += M15_SECONDS

        if self.config.replay_mode != "dry_run":
            self.db_manager.update_replay_run_status(
                replay_id=replay_id,
                status="COMPLETED",
                finished_at_utc=_iso_utc(int(time.time())),
                observations_created=obs_created,
                blocked_created=blocked_created,
            )

        return self._summary(
            "COMPLETED",
            detection.missed_count,
            replayed_count,
            obs_created,
            blocked_created,
            start_mono,
            first_missed,
            last_missed,
            replay_id=replay_id,
        )

    def _abort_replay(
        self,
        replay_id: str,
        status: str,
        error_text: str,
        missed: int,
        replayed: int,
        obs: int,
        blocked: int,
        first_missed: int,
        last_missed: int,
        start_mono: float,
    ) -> ReplaySummary:
        """Halt replay, persist failure status, and leave cursor at last success."""
        logger.error("Replay aborted status=%s: %s", status, error_text)
        if self.config.replay_mode != "dry_run":
            self.db_manager.update_replay_run_status(
                replay_id=replay_id,
                status="BLOCKED",
                finished_at_utc=_iso_utc(int(time.time())),
                error_text=error_text,
                observations_created=obs,
                blocked_created=blocked,
            )
        return self._summary(
            status,
            missed,
            replayed,
            obs,
            blocked,
            start_mono,
            first_missed,
            last_missed,
            err=error_text,
            replay_id=replay_id,
        )

    def _replay_bar(self, bar_ts: int, replay_id: str) -> tuple[int, int]:
        """Evaluate a single missed M15 bar under STRATEGY_ONLY semantics."""
        m15_candles, h4_candles = self._fetch_context(bar_ts)

        regime = self.kronos_engine.infer_regime(h4_candles)
        if not regime.temporal_assertion_passed:
            logger.warning("Replay temporal assertion failed at bar_ts=%d", bar_ts)
            self._advance_bar_cursor_after_success(bar_ts)
            return (0, 0)

        signals = cast(
            list[SignalLike],
            self.strategy_evaluator.evaluate_signals(m15_candles, h4_candles),
        )
        obs_created = 0
        blocked_created = 0

        for sig in signals:
            if sig.signal_type not in (SignalType.BUY, SignalType.SELL):
                continue
            if sig.stop_loss <= 0.0 or sig.take_profit <= 0.0:
                continue

            risk = abs(sig.entry_price - sig.stop_loss)
            reward = abs(sig.take_profit - sig.entry_price)
            rr_ratio = reward / risk if risk > 0.0 else 0.0
            direction: TradeDirection = (
                "LONG" if sig.signal_type is SignalType.BUY else "SHORT"
            )

            if rr_ratio < self.min_rr_ratio:
                if self.config.replay_mode != "dry_run":
                    blocked_rec = BlockedSignalRecord(
                        timestamp_utc=_iso_utc(bar_ts),
                        pair=self.symbol,
                        direction=direction,
                        strategy_selected=self.strategy_id,
                        reason_blocked="stale_signal_expired",
                        confidence_at_time=0.0,
                        would_be_entry_price=sig.entry_price,
                        current_spread=0.0,
                        details=f"replay_id={replay_id} gate=min_rr rr_ratio={rr_ratio:.2f}",
                        origin="REPLAY",
                        replay_id=replay_id,
                    )
                    if self.db_manager.insert_replay_blocked_signal(blocked_rec):
                        blocked_created += 1
                else:
                    blocked_created += 1
                continue

            if self.config.replay_mode != "dry_run":
                obs_rec = SignalObservationRecord(
                    signal_id=f"{self.symbol}:{bar_ts}:{self.strategy_id}",
                    symbol=self.symbol,
                    bar_ts=bar_ts,
                    strategy_id=self.strategy_id,
                    order_type=sig.signal_type.value,
                    state="OPEN",
                    entry_px=sig.entry_price,
                    sl_px=sig.stop_loss,
                    tp_px=sig.take_profit,
                    lot_virtual=self.virtual_lot,
                    origin="REPLAY",
                    replay_id=replay_id,
                )
                if self.db_manager.insert_replay_observation(obs_rec):
                    obs_created += 1
            else:
                obs_created += 1
            break

        self._advance_bar_cursor_after_success(bar_ts)
        return (obs_created, blocked_created)

    def _advance_bar_cursor_after_success(self, bar_ts: int) -> None:
        """Advance cursor with fingerprint only after successful bar evaluation."""
        if self.config.replay_mode != "dry_run":
            self.db_manager.advance_bar_cursor_with_config_hash(
                symbol=self.symbol,
                timeframe="M15",
                last_closed_bar_ts=bar_ts,
                config_hash=self.config_hash,
            )

    def _fetch_context(
        self, bar_ts: int
    ) -> tuple[list[CandleDict], list[CandleDict]]:
        """Fetch historical M15 and H4 candles with strict zero lookahead."""
        h4_cutoff = ((bar_ts + M15_SECONDS) // H4_SECONDS) * H4_SECONDS - H4_SECONDS
        m15_cutoff_str = _iso_utc(bar_ts)
        h4_cutoff_str = _iso_utc(h4_cutoff)

        fetch_m15 = self.bar_lookback_m15 + self.config.max_bars + 10
        fetch_h4 = self.bar_lookback_h4 + 10
        lock = getattr(self.exness_client, "lock", None)

        if lock is not None:
            with lock:
                m15_raw = self.exness_client.fetch_recent_candles("M15", fetch_m15)
                h4_raw = self.exness_client.fetch_recent_candles("H4", fetch_h4)
        else:
            m15_raw = self.exness_client.fetch_recent_candles("M15", fetch_m15)
            h4_raw = self.exness_client.fetch_recent_candles("H4", fetch_h4)

        if not m15_raw or not h4_raw:
            raise MissingCandlesError("ExnessClient returned empty candle records")

        m15_records = [
            _to_candle_record(c)
            for c in m15_raw
            if _to_candle_record(c).timestamp_utc <= m15_cutoff_str
        ]
        h4_records = [
            _to_candle_record(c)
            for c in h4_raw
            if _to_candle_record(c).timestamp_utc <= h4_cutoff_str
        ]

        if len(m15_records) < self.bar_lookback_m15:
            raise MissingCandlesError(
                f"insufficient M15 candles: {len(m15_records)} < {self.bar_lookback_m15}"
            )
        if len(h4_records) < self.bar_lookback_h4:
            raise MissingCandlesError(
                f"insufficient H4 candles: {len(h4_records)} < {self.bar_lookback_h4}"
            )

        m15_window = m15_records[-self.bar_lookback_m15 :]
        h4_window = h4_records[-self.bar_lookback_h4 :]

        if m15_window[-1].timestamp_utc != m15_cutoff_str:
            raise MissingCandlesError(
                f"missing M15 candle for bar_ts {bar_ts} "
                f"(expected {m15_cutoff_str}, got {m15_window[-1].timestamp_utc})"
            )

        for i in range(len(m15_window) - 1):
            t1 = _iso_to_epoch(m15_window[i].timestamp_utc)
            t2 = _iso_to_epoch(m15_window[i + 1].timestamp_utc)
            if t2 - t1 != M15_SECONDS:
                raise MissingCandlesError(
                    f"non-contiguous M15 candles between {m15_window[i].timestamp_utc} "
                    f"and {m15_window[i+1].timestamp_utc}"
                )

        m15_dicts = [_to_candle_dict(c) for c in m15_window]
        h4_dicts = [_to_candle_dict(c) for c in h4_window]
        return (m15_dicts, h4_dicts)
