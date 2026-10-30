"""Unit tests for Telegram message templates and purity validation."""

import pytest

from engine.telegram_bot.templates import (
    DailyDashboardData,
    SignalAlertData,
    TemplateValidationError,
    format_daily_dashboard,
    format_signal_alert,
    validate_text_purity,
)


def test_format_daily_dashboard_valid() -> None:
    data = DailyDashboardData(
        date_str="2026-10-29",
        session_pnl_usd=420.50,
        session_pnl_pips=42.0,
        total_trades=4,
        wins=3,
        losses=1,
        max_drawdown_pct=0.85,
        paused_events_count=2,
        avg_spread_pips=1.8,
        myfxbook_url="https://www.myfxbook.com/members/example/123456",
    )
    msg = format_daily_dashboard(data)
    assert "DAILY DASHBOARD — XAUUSD SESSION" in msg
    assert "+$420.50" in msg
    assert "Engine PAUSED Events: 2" in msg
    assert "Average Session Spread: 1.8 pips" in msg
    assert "myfxbook.com" in msg


def test_format_signal_alert_valid() -> None:
    data = SignalAlertData(
        trade_id="TRD-20261029-001",
        strategy_timeframe="H1",
        direction="LONG",
        entry_low=2735.20,
        entry_high=2736.50,
        sl=2728.00,
        tp1=2748.00,
        rr1=1.8,
        hit_rate_1=68.5,
        tp2=2758.00,
        rr2=3.2,
        hit_rate_2=44.0,
        lot_size=0.03,
        confidence_score=78.5,
        regime_detected="TRENDING_BULLISH",
        valid_max_minutes=30,
        strategy_selected="volatility_breakout",
        setup_summary="ATR expansion 1.6x di atas MA20 dengan volume tick konformatif",
        invalidation_candles=8,
    )
    msg = format_signal_alert(data)
    assert "⚡ SIGNAL — XAUUSD H1" in msg
    assert "📈 Direction: LONG" in msg
    assert "🎯 Entry Zone: 2735.20 – 2736.50" in msg
    assert "🛑 Stop Loss: 2728.00 (ATR-based)" in msg
    assert "🎯 TP1: 2748.00 (1:1.8 RR) — 68.5% historical hit rate" in msg
    assert "⚡ TP2: 2758.00 (1:3.2 RR) — 44.0% historical hit rate" in msg
    assert "📦 Lot Size: 0.03" in msg
    assert "🧠 Confidence: 78.5%" in msg
    assert "🔍 Regime: TRENDING_BULLISH (H4)" in msg
    assert "⏰ Valid max: 30 menit" in msg
    assert "🧠 Strategi: volatility_breakout" in msg
    assert "⚠️ Invalidasi: Regime H4 berubah arah / time invalidation 8 candle M15" in msg
    assert "🏷 #TRD-20261029-001" in msg


@pytest.mark.parametrize(
    "prohibited_word",
    [
        "Hasil analisis ChatGPT menganalisis arah pasar",
        "Didukung oleh model OpenAI terbaru",
        "Claude menyarankan entry buy",
        "DeepSeek mengidentifikasi support",
    ],
)
def test_cloud_ai_wording_prohibited(prohibited_word: str) -> None:
    with pytest.raises(TemplateValidationError, match="Prohibited cloud AI wording"):
        validate_text_purity(prohibited_word)


@pytest.mark.parametrize(
    "winrate_claim",
    [
        "Strategi ini memiliki Win Rate 85%",
        "Sistem dengan win rate: 75% terbukti",
        "Winrate=90%",
    ],
)
def test_raw_win_rate_prohibited(winrate_claim: str) -> None:
    with pytest.raises(TemplateValidationError, match="Prohibited raw win rate claim"):
        validate_text_purity(winrate_claim)


@pytest.mark.parametrize(
    "smc_word",
    [
        "Terjadi CHOCH pada timeframe M15",
        "Break of structure (BOS) terkonfirmasi",
        "Entry pada Order Block demand",
        "Menunggu penutupan Fair Value Gap (FVG)",
        "Liquidity sweep di area swing low",
        "Terjadi Judas swing di awal sesi London",
    ],
)
def test_smc_ict_jargon_prohibited(smc_word: str) -> None:
    with pytest.raises(TemplateValidationError, match="Prohibited SMC/ICT terminology"):
        validate_text_purity(smc_word)
