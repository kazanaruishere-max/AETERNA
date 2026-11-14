"""Unit tests for TelegramControlBot client and single-entry command dispatcher.

Module: tests.test_telegram_client
Responsibility: Verifies deterministic authorization, single-entry /menu dashboard,
stateful editMessageText handling, replay prevention, two-step confirmation cycles,
and emergency execution handoffs.
Covers REQ: REQ-TEL-001, REQ-TEL-002, REQ-TEL-003, REQ-TEL-004
Owner: aeterna-execution
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportMissingImports=false
# pyright: reportUntypedFunctionDecorator=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engine.monitoring.types import DailyMetrics
from engine.telegram_bot.client import TelegramControlBot
from engine.telegram_bot.interfaces import (
    AdminAuthenticator,
    DailyMetricsCollector,
    ExecutionEmergencyHandler,
    NonceManager,
    TwoStepController,
)
from engine.telegram_bot.types import (
    AdminCommand,
    AuthResult,
    CallbackNonce,
    EmergencyCloseResult,
    TwoStepAction,
    TwoStepState,
)

ADMIN_ID: int = 123456789
STRANGER_ID: int = 987654321
CHAT_ID: int = 424242


# ----------------------------------------------------------------------
# Test Fixtures / Helpers
# ----------------------------------------------------------------------


def _make_bot(
    admin_id: int = ADMIN_ID,
    *,
    metrics_collector: DailyMetricsCollector | None = None,
    emergency_handler: ExecutionEmergencyHandler | None = None,
    token: str = "mock-bot-token-12345",
    session: MagicMock | None = None,
) -> tuple[
    TelegramControlBot,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock | None,
    MagicMock | None,
]:
    authenticator = MagicMock(spec=AdminAuthenticator)

    def _auth(user_id: int) -> AuthResult:
        if user_id == admin_id:
            return AuthResult(allowed=True, user_id=user_id, reason="OK")
        return AuthResult(
            allowed=False, user_id=user_id, reason="UNAUTHORIZED_USER_SILENT_DROP"
        )

    authenticator.authenticate.side_effect = _auth

    nonce_manager = MagicMock(spec=NonceManager)
    nonce_counter = 0

    def _create_nonce(
        action: AdminCommand, user_id: int, payload: dict[str, object] | None = None
    ) -> CallbackNonce:
        nonlocal nonce_counter
        nonce_counter += 1
        return CallbackNonce(
            nonce=f"nonce-{action.value}-{nonce_counter}",
            action=action,
            user_id=user_id,
            created_at_mono=100.0,
            expires_at_mono=160.0,
            payload=dict(payload or {}),
        )

    nonce_manager.create_nonce.side_effect = _create_nonce

    two_step = MagicMock(spec=TwoStepController)
    step_counter = 0

    def _initiate_two_step(action: AdminCommand, user_id: int) -> TwoStepAction:
        nonlocal step_counter
        step_counter += 1
        return TwoStepAction(
            action=action,
            nonce=f"step-{action.value}-{step_counter}",
            user_id=user_id,
            created_at_mono=100.0,
            expires_at_mono=115.0,
            state=TwoStepState.PENDING_CONFIRMATION,
        )

    two_step.initiate.side_effect = _initiate_two_step

    mock_metrics = (
        MagicMock(spec=DailyMetricsCollector)
        if metrics_collector is None
        else metrics_collector
    )
    mock_emergency = (
        MagicMock(spec=ExecutionEmergencyHandler)
        if emergency_handler is None
        else emergency_handler
    )

    bot = TelegramControlBot(
        token=token,
        authenticator=authenticator,
        nonce_manager=nonce_manager,
        two_step=two_step,
        metrics_collector=mock_metrics,
        emergency_handler=mock_emergency,
        session=session,  # type: ignore[arg-type]
    )
    return bot, authenticator, nonce_manager, two_step, mock_metrics, mock_emergency


def _text_update(user_id: int, text: str, chat_id: int = CHAT_ID) -> dict[str, object]:
    return {
        "update_id": 1001,
        "message": {
            "message_id": 1,
            "from": {"id": user_id, "is_bot": False, "first_name": "Admin"},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def _callback_update(
    user_id: int, data: str, callback_id: str = "cb-999", chat_id: int = CHAT_ID
) -> dict[str, object]:
    return {
        "update_id": 1002,
        "callback_query": {
            "id": callback_id,
            "from": {"id": user_id, "is_bot": False, "first_name": "Admin"},
            "message": {
                "message_id": 50,
                "chat": {"id": chat_id, "type": "private"},
            },
            "data": data,
        },
    }


# ----------------------------------------------------------------------
# 1. Single-Entry /menu Command Renders Dashboard (Mandat 1)
# ----------------------------------------------------------------------


def test_single_entry_menu_command_renders_dashboard() -> None:
    """Verify /menu renders conceptual dashboard layout and inline control panel."""
    metrics = DailyMetrics(
        date_utc="2026-11-07",
        total_trades=5,
        win_trades=3,
        loss_trades=2,
        win_rate_pct=60.0,
        gross_profit_usd=200.0,
        gross_loss_usd=54.50,
        net_pnl_usd=145.50,
        profit_factor=3.67,
        max_drawdown_usd=50.0,
        max_drawdown_pct=0.50,
        paused_duration_seconds=0.0,
        active_positions_count=2,
        current_account_equity=10034.48,
        myfxbook_url="https://myfxbook.com/aeterna",
    )
    mock_metrics = MagicMock(spec=DailyMetricsCollector)
    mock_metrics.collect_daily_metrics.return_value = metrics

    bot, _, _, _, _, _ = _make_bot(metrics_collector=mock_metrics)
    res = bot.handle_update(_text_update(ADMIN_ID, "/menu"))

    assert res is not None
    assert res["method"] == "sendMessage"
    assert res["chat_id"] == CHAT_ID

    text = str(res["text"])
    assert "=================================" in text
    assert "AETERNA QUANT ENGINE - CONTROL PANEL" in text
    assert "Status       : 🟢 ACTIVE (BREAKOUT_M15)" in text
    assert "Daily PnL    : +$145.50 (+1.45%)" in text
    assert "Max DD       : -0.50%" in text
    assert "Posisi Aktif : 2 (XAUUSD)" in text

    keyboard = res["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 3
    # Row 0: Pause / Resume, Daily Report
    assert keyboard[0][0]["text"] == "⏸ PAUSE ENGINE"
    assert keyboard[0][0]["callback_data"].startswith("action:PAUSE:")
    assert keyboard[0][1]["text"] == "📊 DAILY REPORT"
    assert keyboard[0][1]["callback_data"].startswith("action:DAILY_REPORT:")
    # Row 1: Force Close
    assert keyboard[1][0]["text"] == "⚠️ FORCE CLOSE ALL POSITIONS"
    assert keyboard[1][0]["callback_data"].startswith("action:FORCE_CLOSE_ALL:")
    # Row 2: Emergency Killswitch
    assert keyboard[2][0]["text"] == "🛑 EMERGENCY KILLSWITCH (SHUTDOWN)"
    assert keyboard[2][0]["callback_data"].startswith("action:KILLSWITCH:")


# ----------------------------------------------------------------------
# 2. Arbitrary Slash Commands Divert to Menu (Mandat 1)
# ----------------------------------------------------------------------


def test_arbitrary_slash_commands_divert_to_menu() -> None:
    """Non-/menu commands (e.g. /status, /pause, /help) divert directly to /menu without split execution."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None

    slash_commands = [
        "/status",
        "/report",
        "/pause",
        "/resume",
        "/force_close",
        "/killswitch",
        "/help",
        "/start",
        "/arbitrary_cmd",
    ]

    for cmd in slash_commands:
        res = bot.handle_update(_text_update(ADMIN_ID, cmd))
        assert res is not None
        assert res["method"] == "sendMessage"
        assert res["chat_id"] == CHAT_ID
        assert "AETERNA QUANT ENGINE - CONTROL PANEL" in str(res["text"])
        assert "reply_markup" in res

    # Verify no split execution occurred
    emergency_handler.set_system_state_paused.assert_not_called()
    emergency_handler.set_system_state_normal.assert_not_called()
    emergency_handler.execute_force_close_all.assert_not_called()
    emergency_handler.execute_emergency_killswitch.assert_not_called()
    two_step.initiate.assert_not_called()


# ----------------------------------------------------------------------
# 3. Callback Query Routes Action via Nonce (Mandat 2 & REQ-TEL-002)
# ----------------------------------------------------------------------


def test_callback_query_routes_action_via_nonce() -> None:
    """Callback queries are validated with single-use 60s nonces and routed accordingly."""
    bot, _, nonce_manager, _, _, _ = _make_bot()

    # 1. Valid single-use nonce
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="valid-nonce-1",
        action=AdminCommand.STATUS,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    res = bot.handle_update(_callback_update(ADMIN_ID, "action:STATUS:valid-nonce-1"))
    nonce_manager.consume_nonce.assert_called_once_with("valid-nonce-1", ADMIN_ID)
    assert res is not None
    assert res["method"] == "editMessageText"

    # 2. Expired / invalid nonce (>60s)
    nonce_manager.consume_nonce.return_value = None
    res_expired = bot.handle_update(
        _callback_update(ADMIN_ID, "action:STATUS:expired-nonce")
    )
    assert res_expired is not None
    assert res_expired["method"] == "answerCallbackQuery"
    assert res_expired["show_alert"] is True
    assert "Aksi kedaluwarsa" in str(res_expired["text"])


# ----------------------------------------------------------------------
# 4. Stateful Dashboard Editing on Callback (Mandat 3 Anti-Spam)
# ----------------------------------------------------------------------


def test_stateful_dashboard_editing_on_callback() -> None:
    """Pressing Report / Refresh emits editMessageText instead of sendMessage."""
    metrics = DailyMetrics(
        date_utc="2026-11-07",
        total_trades=10,
        win_trades=7,
        loss_trades=3,
        win_rate_pct=70.0,
        gross_profit_usd=300.0,
        gross_loss_usd=100.0,
        net_pnl_usd=200.0,
        profit_factor=3.0,
        max_drawdown_usd=50.0,
        max_drawdown_pct=0.50,
        paused_duration_seconds=0.0,
        active_positions_count=1,
        current_account_equity=10200.0,
        myfxbook_url="https://myfxbook.com/aeterna",
    )
    mock_metrics = MagicMock(spec=DailyMetricsCollector)
    mock_metrics.collect_daily_metrics.return_value = metrics
    bot, _, nonce_manager, _, _, _ = _make_bot(metrics_collector=mock_metrics)

    # Click Report
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="rep-nonce",
        action=AdminCommand.DAILY_REPORT,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    res_report = bot.handle_update(
        _callback_update(ADMIN_ID, "action:DAILY_REPORT:rep-nonce")
    )
    assert res_report is not None
    assert res_report["method"] == "editMessageText"
    assert res_report["chat_id"] == CHAT_ID
    assert res_report["message_id"] == 50
    assert "DAILY DASHBOARD" in str(res_report["text"])

    # Click Refresh / Status
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="stat-nonce",
        action=AdminCommand.STATUS,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    res_status = bot.handle_update(
        _callback_update(ADMIN_ID, "action:STATUS:stat-nonce")
    )
    assert res_status is not None
    assert res_status["method"] == "editMessageText"
    assert res_status["chat_id"] == CHAT_ID
    assert res_status["message_id"] == 50
    assert "AETERNA QUANT ENGINE - CONTROL PANEL" in str(res_status["text"])


# ----------------------------------------------------------------------
# 5. Destructive Callback Triggers Two-Step (REQ-TEL-003)
# ----------------------------------------------------------------------


def test_destructive_callback_triggers_two_step() -> None:
    """Clicking Killswitch or Force Close edits message to 15s confirmation prompt."""
    bot, _, nonce_manager, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None

    # 1. Killswitch callback
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="nonce-kill",
        action=AdminCommand.KILLSWITCH,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    two_step.initiate.return_value = TwoStepAction(
        action=AdminCommand.KILLSWITCH,
        nonce="step-kill-1",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.PENDING_CONFIRMATION,
    )

    res = bot.handle_update(_callback_update(ADMIN_ID, "action:KILLSWITCH:nonce-kill"))
    assert res is not None
    assert res["method"] == "editMessageText"
    assert res["chat_id"] == CHAT_ID
    assert res["message_id"] == 50
    assert "EMERGENCY KILLSWITCH" in str(res["text"])
    assert "15 detik" in str(res["text"])

    keyboard = res["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"].startswith("confirm:KILLSWITCH:")
    assert "KONFIRMASI EKSEKUSI" in keyboard[0][0]["text"]
    assert keyboard[0][1]["callback_data"].startswith("cancel:KILLSWITCH:")
    assert "BATALKAN" in keyboard[0][1]["text"]

    emergency_handler.execute_emergency_killswitch.assert_not_called()

    # 2. Force Close callback
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="nonce-fc",
        action=AdminCommand.FORCE_CLOSE_ALL,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    two_step.initiate.return_value = TwoStepAction(
        action=AdminCommand.FORCE_CLOSE_ALL,
        nonce="step-fc-1",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.PENDING_CONFIRMATION,
    )
    res_fc = bot.handle_update(
        _callback_update(ADMIN_ID, "action:FORCE_CLOSE_ALL:nonce-fc")
    )
    assert res_fc is not None
    assert res_fc["method"] == "editMessageText"
    assert "FORCE CLOSE ALL" in str(res_fc["text"])
    emergency_handler.execute_force_close_all.assert_not_called()


# ----------------------------------------------------------------------
# 6. Two-Step Confirmation and Dashboard Restoration (Mandat 3 & REQ-TEL-003)
# ----------------------------------------------------------------------


def test_two_step_confirmation_and_dashboard_restoration() -> None:
    """Confirming two-step executes handler and restores dashboard with updated state."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None
    emergency_handler.set_system_state_paused.return_value = True
    emergency_handler.execute_emergency_killswitch.return_value = True

    # 1. Confirm PAUSE
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.PAUSE,
        nonce="step-pause-1",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CONFIRMED,
    )
    res_pause = bot.handle_update(
        _callback_update(ADMIN_ID, "confirm:PAUSE:step-pause-1")
    )
    emergency_handler.set_system_state_paused.assert_called_once()
    assert res_pause is not None
    assert res_pause["method"] == "editMessageText"
    assert "Status       : ⏸ PAUSED" in str(res_pause["text"])
    # Button should dynamically switch to RESUME
    keyboard_pause = res_pause["reply_markup"]["inline_keyboard"]
    assert keyboard_pause[0][0]["text"] == "▶️ RESUME ENGINE"
    assert keyboard_pause[0][0]["callback_data"].startswith("action:RESUME:")

    # 2. Confirm KILLSWITCH
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.KILLSWITCH,
        nonce="step-kill-1",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CONFIRMED,
    )
    res_kill = bot.handle_update(
        _callback_update(ADMIN_ID, "confirm:KILLSWITCH:step-kill-1")
    )
    emergency_handler.execute_emergency_killswitch.assert_called_once()
    assert res_kill is not None
    assert res_kill["method"] == "editMessageText"
    assert "🛑 SHUTDOWN (KILLSWITCH)" in str(res_kill["text"])


# ----------------------------------------------------------------------
# 7. Two-Step Cancellation Restores Dashboard (Mandat 3)
# ----------------------------------------------------------------------


def test_two_step_cancellation_restores_dashboard() -> None:
    """Clicking cancel restores the active dashboard layout without executing action."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None

    res = bot.handle_update(_callback_update(ADMIN_ID, "cancel:KILLSWITCH:step-kill-1"))
    two_step.cancel.assert_called_once_with("step-kill-1", ADMIN_ID)
    assert res is not None
    assert res["method"] == "editMessageText"
    assert res["chat_id"] == CHAT_ID
    assert res["message_id"] == 50
    assert "AETERNA QUANT ENGINE - CONTROL PANEL" in str(res["text"])
    assert "🟢 ACTIVE" in str(res["text"])
    assert "reply_markup" in res
    emergency_handler.execute_emergency_killswitch.assert_not_called()


# ----------------------------------------------------------------------
# 8. Unauthorized User Silent Drop on Menu & Callback (REQ-TEL-001)
# ----------------------------------------------------------------------


def test_unauthorized_user_silent_drop_on_menu_and_callback() -> None:
    """Unauthorized user updates (/menu or callbacks) are silently dropped without response."""
    bot, authenticator, _, _, _, _ = _make_bot()

    # Unauthorized /menu
    res_msg = bot.handle_update(_text_update(STRANGER_ID, "/menu"))
    assert res_msg is None

    # Unauthorized callback
    res_cb = bot.handle_update(_callback_update(STRANGER_ID, "action:STATUS:nonce-xyz"))
    assert res_cb is None

    assert authenticator.authenticate.call_count == 2


# ----------------------------------------------------------------------
# Additional Supporting Tests: Whitespace, Replay, Expiry, Async, Transport
# ----------------------------------------------------------------------


def test_whitespace_message_returns_none() -> None:
    """Whitespace-only text message returns None without error."""
    bot, _, _, _, _, _ = _make_bot()
    assert bot.handle_update(_text_update(ADMIN_ID, "   ")) is None


def test_expired_two_step_callback_rejected() -> None:
    """Callback after 15s TTL returns expiration alert; emergency handler is NOT called."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None

    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.KILLSWITCH,
        nonce="step-kill-exp",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.EXPIRED,
    )

    res = bot.handle_update(
        _callback_update(ADMIN_ID, "confirm:KILLSWITCH:step-kill-exp")
    )
    assert res is not None
    assert res["method"] == "answerCallbackQuery"
    assert res["show_alert"] is True
    assert "Konfirmasi kedaluwarsa" in str(res["text"])
    emergency_handler.execute_emergency_killswitch.assert_not_called()


def test_replay_attack_rejected() -> None:
    """Replaying the same nonce a second time is rejected."""
    bot, _, nonce_manager, _, _, emergency_handler = _make_bot()
    assert emergency_handler is not None

    # First attempt: valid
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="replay-nonce",
        action=AdminCommand.PAUSE,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    res1 = bot.handle_update(_callback_update(ADMIN_ID, "action:PAUSE:replay-nonce"))
    assert res1 is not None
    assert res1["method"] == "editMessageText"

    # Second attempt: nonce already consumed -> None returned
    nonce_manager.consume_nonce.return_value = None
    res2 = bot.handle_update(_callback_update(ADMIN_ID, "action:PAUSE:replay-nonce"))
    assert res2 is not None
    assert res2["method"] == "answerCallbackQuery"
    assert res2["show_alert"] is True
    assert "Aksi kedaluwarsa" in str(res2["text"])


def test_force_close_all_confirmation_cycle() -> None:
    """Force close all triggers two-step and executes handler with max_deviation_pts=50."""
    bot, _, nonce_manager, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None
    emergency_handler.execute_force_close_all.return_value = [
        EmergencyCloseResult(ticket=101, success=True, closed_lot=0.01),
        EmergencyCloseResult(ticket=102, success=True, closed_lot=0.02),
    ]

    # Trigger force close
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="fc-nonce-1",
        action=AdminCommand.FORCE_CLOSE_ALL,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    two_step.initiate.return_value = TwoStepAction(
        action=AdminCommand.FORCE_CLOSE_ALL,
        nonce="step-fc-cycle",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.PENDING_CONFIRMATION,
    )
    res_fc = bot.handle_update(
        _callback_update(ADMIN_ID, "action:FORCE_CLOSE_ALL:fc-nonce-1")
    )
    assert res_fc is not None
    assert res_fc["method"] == "editMessageText"
    emergency_handler.execute_force_close_all.assert_not_called()

    # Confirm force close
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.FORCE_CLOSE_ALL,
        nonce="step-fc-cycle",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CONFIRMED,
    )
    res_confirm = bot.handle_update(
        _callback_update(ADMIN_ID, "confirm:FORCE_CLOSE_ALL:step-fc-cycle")
    )
    emergency_handler.execute_force_close_all.assert_called_once_with(
        max_deviation_pts=50
    )
    assert res_confirm is not None
    assert res_confirm["method"] == "editMessageText"


def test_pause_and_resume_cycle() -> None:
    """Pause requires two-step confirmation; Resume executes directly via callback."""
    bot, _, nonce_manager, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None
    emergency_handler.set_system_state_paused.return_value = True
    emergency_handler.set_system_state_normal.return_value = True

    # 1. Initiate pause callback
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="p-init-nonce",
        action=AdminCommand.PAUSE,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    two_step.initiate.return_value = TwoStepAction(
        action=AdminCommand.PAUSE,
        nonce="step-pause-99",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.PENDING_CONFIRMATION,
    )
    res_init = bot.handle_update(
        _callback_update(ADMIN_ID, "action:PAUSE:p-init-nonce")
    )
    assert res_init is not None
    assert res_init["method"] == "editMessageText"
    assert "PAUSE TRADING" in str(res_init["text"])
    emergency_handler.set_system_state_paused.assert_not_called()

    # 2. Confirm pause
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.PAUSE,
        nonce="step-pause-99",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CONFIRMED,
    )
    res_confirm = bot.handle_update(
        _callback_update(ADMIN_ID, "confirm:PAUSE:step-pause-99")
    )
    emergency_handler.set_system_state_paused.assert_called_once()
    assert res_confirm is not None
    assert bot.is_paused is True
    assert "Status       : ⏸ PAUSED" in str(res_confirm["text"])

    # 3. Resume via callback
    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="res-nonce",
        action=AdminCommand.RESUME,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )
    res_resume = bot.handle_update(
        _callback_update(ADMIN_ID, "action:RESUME:res-nonce")
    )
    emergency_handler.set_system_state_normal.assert_called_once()
    assert bot.is_paused is False
    assert res_resume is not None
    assert res_resume["method"] == "editMessageText"
    assert "Status       : 🟢 ACTIVE" in str(res_resume["text"])


def test_main_control_keyboard_rendering() -> None:
    """Main keyboard includes all specified buttons, each with its unique nonce."""
    bot, _, nonce_manager, _, _, _ = _make_bot()
    keyboard = bot.build_main_control_keyboard(ADMIN_ID)["inline_keyboard"]

    assert len(keyboard) == 3
    assert keyboard[0][0]["callback_data"].startswith("action:PAUSE:")
    assert keyboard[0][1]["callback_data"].startswith("action:DAILY_REPORT:")
    assert keyboard[1][0]["callback_data"].startswith("action:FORCE_CLOSE_ALL:")
    assert keyboard[2][0]["callback_data"].startswith("action:KILLSWITCH:")
    assert nonce_manager.create_nonce.call_count == 4


def test_secret_string_token_support() -> None:
    """Bot unmasks DPAPI SecretString correctly when formatting API URLs."""
    mock_cred = MagicMock()
    mock_cred.get_secret_value.return_value = "custom-auth-credential"
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {}}
    mock_session.post.return_value = mock_response

    bot, _, _, _, _, _ = _make_bot(token=mock_cred, session=mock_session)  # type: ignore[arg-type]
    bot.send({"method": "sendMessage", "chat_id": CHAT_ID, "text": "hello"})
    mock_cred.get_secret_value.assert_called_once()
    call_url = mock_session.post.call_args[0][0]
    assert call_url == "https://api.telegram.org/botcustom-auth-credential/sendMessage"


@pytest.mark.asyncio
async def test_async_decoupling_off_event_loop() -> None:
    """handle_update_async executes off the event loop thread without blocking."""
    bot, _, _, _, _, _ = _make_bot()
    res = await bot.handle_update_async(_text_update(ADMIN_ID, "/menu"))
    assert res is not None
    assert res["method"] == "sendMessage"


def test_push_dashboard_sends_menu_to_admin_chat() -> None:
    """Startup push: dashboard + inline keyboard go out without any incoming update."""
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {}}
    mock_session.post.return_value = mock_response
    bot, *_ = _make_bot(session=mock_session)

    assert bot.push_dashboard(ADMIN_ID) is True

    body = mock_session.post.call_args.kwargs["json"]
    assert "sendMessage" in mock_session.post.call_args.args[0]
    assert body["chat_id"] == ADMIN_ID
    assert "AETERNA" in body["text"].upper()
    assert body["reply_markup"]["inline_keyboard"]


def test_dispatch_update_delivers_payload_and_answers_callback() -> None:
    """dispatch_update handles, answers callback, and transmits outgoing payload."""
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {}}
    mock_session.post.return_value = mock_response
    bot, _, nonce_manager, _, _, _ = _make_bot(session=mock_session)

    nonce_manager.consume_nonce.return_value = CallbackNonce(
        nonce="status-nonce",
        action=AdminCommand.STATUS,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )

    update = _callback_update(
        ADMIN_ID, data="action:STATUS:status-nonce", callback_id="cb-dispatch"
    )
    bot.dispatch_update(update)

    # 1. answerCallbackQuery must be delivered
    # 2. editMessageText payload for STATUS must be delivered
    assert mock_session.post.call_count == 2
    urls = [call.args[0] for call in mock_session.post.call_args_list]
    assert any("answerCallbackQuery" in url for url in urls)
    assert any("editMessageText" in url for url in urls)


@pytest.mark.asyncio
async def test_poll_once_advances_offset() -> None:
    """poll_once parses getUpdates result and updates internal last_update_id."""
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "result": [
            {"update_id": 105, "message": {"text": "hello"}},
            {"update_id": 106, "message": {"text": "world"}},
        ],
    }
    mock_session.get.return_value = mock_response

    bot, _, _, _, _, _ = _make_bot(session=mock_session)
    updates = await bot.poll_once(timeout=10, limit=20)

    assert len(updates) == 2
    assert bot.last_update_id == 106

    # Verify offset advances on subsequent call
    await bot.poll_once(timeout=10, limit=20)
    assert mock_session.get.call_args.kwargs["params"]["offset"] == 107
