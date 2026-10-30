"""Telegram message templates and formatting for AI Trading XAUUSD.

Provides two distinct streams:
- Stream 1: Daily Dashboard Session Report (§9.5)
- Stream 2: Per-Event Signal Alert with strict formatting & validation

Strictly enforces prohibition of:
1. Cloud AI provider wording (OpenAI, Claude, ChatGPT, etc.)
2. Raw win rate claims
3. SMC/ICT speculative jargon (CHOCH, BOS, Order Block, FVG, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# ============================================================================
# Prohibited Patterns Configuration (§9.5)
# ============================================================================

CLOUD_AI_PATTERNS: Final[tuple[str, ...]] = (
    "openai",
    "chatgpt",
    "claude",
    "gpt-4",
    "gpt-3",
    "deepseek",
    "anthropic",
    "gemini",
    "copilot",
    "llm provider",
)

RAW_WIN_RATE_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(?i)\bwin\s*rate\s*[:=]?\s*\d+([.,]\d+)?\s*%",
)

SMC_ICT_PATTERNS: Final[tuple[str, ...]] = (
    "choch",
    "bos",
    "change of character",
    "break of structure",
    "order block",
    "orderblock",
    "fair value gap",
    "fvg",
    "liquidity sweep",
    "judas swing",
    "swing low",
    "swing high",
    "smart money",
    "inner circle trader",
)


class TemplateValidationError(ValueError):
    """Raised when signal or report content violates strict wording rules."""


def validate_text_purity(text: str) -> None:
    """Validate that text does not contain prohibited marketing or speculative jargon."""
    lower_text = text.lower()

    for pattern in CLOUD_AI_PATTERNS:
        if pattern in lower_text:
            raise TemplateValidationError(
                f"Prohibited cloud AI wording detected: '{pattern}'. "
                "Attribution must reference native quantitative models (Kronos ONNX / Quant Engine)."
            )

    if RAW_WIN_RATE_REGEX.search(text):
        raise TemplateValidationError(
            "Prohibited raw win rate claim detected. "
            "Use historical hit rate per TP level based on backtest validation instead."
        )

    for pattern in SMC_ICT_PATTERNS:
        if re.search(rf"\b{re.escape(pattern)}\b", lower_text):
            raise TemplateValidationError(
                f"Prohibited SMC/ICT terminology detected: '{pattern}'. "
                "Use formal quantitative descriptions (e.g. ATR breakout, mean-reversion band)."
            )


# ============================================================================
# Data Models (Immutable)
# ============================================================================


@dataclass(frozen=True)
class DailyDashboardData:
    """Session summary metrics extracted from trades and blocked_signals tables."""

    date_str: str
    session_pnl_usd: float
    session_pnl_pips: float
    total_trades: int
    wins: int
    losses: int
    max_drawdown_pct: float
    paused_events_count: int
    avg_spread_pips: float
    myfxbook_url: str


@dataclass(frozen=True)
class SignalAlertData:
    """Signal parameters emitted upon entry qualification."""

    trade_id: str
    strategy_timeframe: str
    direction: str  # LONG or SHORT
    entry_low: float
    entry_high: float
    sl: float
    tp1: float
    rr1: float
    hit_rate_1: float
    tp2: float
    rr2: float
    hit_rate_2: float
    lot_size: float
    confidence_score: float
    regime_detected: str
    valid_max_minutes: int
    strategy_selected: str
    setup_summary: str
    invalidation_candles: int = 8


# ============================================================================
# Stream 1: Daily Dashboard Formatter
# ============================================================================


def format_daily_dashboard(data: DailyDashboardData) -> str:
    """Format Stream 1: Daily session report sent at close of ~12h session."""
    pnl_sign = "+" if data.session_pnl_usd >= 0 else ""
    win_rate_calc = (data.wins / data.total_trades * 100) if data.total_trades > 0 else 0.0

    message = (
        f"📊 DAILY DASHBOARD — XAUUSD SESSION ({data.date_str})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Net P&L: {pnl_sign}${data.session_pnl_usd:,.2f} ({pnl_sign}{data.session_pnl_pips:.1f} pips)\n"
        f"🎯 Trades: {data.total_trades} (Win: {data.wins} | Loss: {data.losses})\n"
        f"📈 Realized Session Win Ratio: {win_rate_calc:.1f}%\n"
        f"📉 Max Session Drawdown: {data.max_drawdown_pct:.2f}%\n"
        f"🛡 Engine PAUSED Events: {data.paused_events_count} (Spread/News protection active)\n"
        f"📏 Average Session Spread: {data.avg_spread_pips:.1f} pips\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 Verified Audit: {data.myfxbook_url}\n"
        "ℹ️ Data source: Deterministic SQLite Audit Ledger"
    )

    validate_text_purity(message)
    return message


# ============================================================================
# Stream 2: Signal Alert Formatter
# ============================================================================


def format_signal_alert(data: SignalAlertData) -> str:
    """Format Stream 2: Structured signal alert emitted per-trade event."""
    direction_upper = data.direction.upper()
    if direction_upper not in ("LONG", "SHORT"):
        raise ValueError(f"Direction must be LONG or SHORT, got: {data.direction}")

    # Validate individual components before building template
    validate_text_purity(data.setup_summary)
    validate_text_purity(data.strategy_selected)

    message = (
        f"⚡ SIGNAL — XAUUSD {data.strategy_timeframe}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Direction: {direction_upper}\n"
        f"🎯 Entry Zone: {data.entry_low:.2f} – {data.entry_high:.2f}\n"
        f"🛑 Stop Loss: {data.sl:.2f} (ATR-based)\n"
        f"🎯 TP1: {data.tp1:.2f} (1:{data.rr1:.1f} RR) — {data.hit_rate_1:.1f}% historical hit rate\n"
        f"⚡ TP2: {data.tp2:.2f} (1:{data.rr2:.1f} RR) — {data.hit_rate_2:.1f}% historical hit rate\n"
        f"📦 Lot Size: {data.lot_size:.2f}\n"
        f"🧠 Confidence: {data.confidence_score:.1f}%\n"
        f"🔍 Regime: {data.regime_detected} (H4)\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Valid max: {data.valid_max_minutes} menit (expired jika belum entry)\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 Strategi: {data.strategy_selected}\n"
        f"📊 Setup: {data.setup_summary}\n"
        f"⚠️ Invalidasi: Regime H4 berubah arah / time invalidation {data.invalidation_candles} candle M15\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 #{data.trade_id}"
    )

    validate_text_purity(message)
    return message
