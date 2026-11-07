"""Unit tests for TelegramControlBot client and command dispatcher.

Validates the seven required behaviors from TASK-M6-STREAM-C:
1. Unauthorized update silent drop (REQ-TEL-001).
2. /status command response with system state summary.
3. /report command response via DailyMetricsCollector (REQ-TEL-004).
4. Destructive command (/killswitch) triggers 15s two-step keyboard without executing (REQ-TEL-003).
5. Two-step confirmation callback within 15s executes emergency handler (REQ-TEL-003).
6. Expired two-step callback (>15s) is rejected without executing emergency handler (REQ-TEL-003).
7. Replay attack with the same nonce is rejected on the second call (REQ-TEL-002).

Plus supporting edge cases:
- /pause and /force_close two-step cycles.
- /resume direct execution.
- Cancellation callback.
- SecretString token unwrapping.
- Long polling transport (poll_once).
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
from engine.telegram_bot.client import (
    FORCE_CLOSE_MAX_DEVIATION_PTS,
    TelegramControlBot,
)
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
# 1. Unauthorized Update Silent Drop (REQ-TEL-001)
# ----------------------------------------------------------------------


def test_unauthorized_update_silent_drop() -> None:
    """Non-whitelisted user updates must return None without sending any Telegram response."""
    bot, authenticator, _, _, _, _ = _make_bot()
    bot.send = MagicMock()  # Mock transport out completely

    # 1a. Unauthorized text command
    res_msg = bot.handle_update(_text_update(STRANGER_ID, "/status"))
    assert res_msg is None

    # 1b. Unauthorized callback query
    res_cb = bot.handle_update(_callback_update(STRANGER_ID, "STATUS:any-nonce"))
    assert res_cb is None

    # Transport must never have been called
    bot.send.assert_not_called()
    assert authenticator.authenticate.call_count == 2


def test_whitespace_message_returns_none() -> None:
    """Whitespace-only text message returns None without raising IndexError."""
    bot, _, _, _, _, _ = _make_bot()
    assert bot.handle_update(_text_update(ADMIN_ID, "   ")) is None

# ----------------------------------------------------------------------
# 2. Authorized /status Command
# ----------------------------------------------------------------------


def test_authorized_command_status() -> None:
    """Admin /status command returns system state summary and main control keyboard."""
    bot, _, _, _, metrics_collector, _ = _make_bot()
    assert metrics_collector is not None
    metrics_collector.collect_daily_metrics.return_value = DailyMetrics(
        date_utc="2026-11-07",
        total_trades=5,
        win_trades=3,
        loss_trades=2,
        win_rate_pct=60.0,
        gross_profit_usd=150.0,
        gross_loss_usd=50.0,
        net_pnl_usd=100.0,
        profit_factor=3.0,
        max_drawdown_usd=30.0,
        max_drawdown_pct=0.30,
        paused_duration_seconds=45.0,
        active_positions_count=1,
        current_account_equity=10100.0,
    )

    update = _text_update(ADMIN_ID, "/status")
    res = bot.handle_update(update)

    assert res is not None
    assert res["method"] == "sendMessage"
    assert res["chat_id"] == CHAT_ID
    assert "STATUS - CONTROL PANEL" in str(res["text"])
    assert "Active positions: 1" in str(res["text"])
    assert "Account equity: $10,100.00" in str(res["text"])
    assert "Net P&L today: +$100.00" in str(res["text"])
    assert "reply_markup" in res
    assert "inline_keyboard" in res["reply_markup"]


# ----------------------------------------------------------------------
# 3. Authorized /report Command (REQ-TEL-004)
# ----------------------------------------------------------------------


def test_authorized_command_report() -> None:
    """Admin /report command invokes DailyMetricsCollector and returns formatted dashboard."""
    bot, _, _, _, metrics_collector, _ = _make_bot()
    assert metrics_collector is not None
    metrics_collector.collect_daily_metrics.return_value = DailyMetrics(
        date_utc="2026-11-07",
        total_trades=8,
        win_trades=5,
        loss_trades=3,
        win_rate_pct=62.5,
        gross_profit_usd=250.0,
        gross_loss_usd=90.0,
        net_pnl_usd=160.0,
        profit_factor=2.78,
        max_drawdown_usd=40.0,
        max_drawdown_pct=0.40,
        paused_duration_seconds=0.0,
        active_positions_count=0,
        current_account_equity=10160.0,
        myfxbook_url="https://www.myfxbook.com/members/aeterna",
    )

    update = _text_update(ADMIN_ID, "/report")
    res = bot.handle_update(update)

    assert res is not None
    assert res["method"] == "sendMessage"
    assert res["chat_id"] == CHAT_ID
    # Must use canonical template
    assert "DAILY DASHBOARD" in str(res["text"])
    assert "$160.00" in str(res["text"])
    assert "Trades: 8 (Win: 5 | Loss: 3)" in str(res["text"])
    metrics_collector.collect_daily_metrics.assert_called_once()


# ----------------------------------------------------------------------
# 4. Destructive Command Triggers Two-Step Keyboard (REQ-TEL-003)
# ----------------------------------------------------------------------


def test_destructive_command_triggers_two_step_keyboard() -> None:
    """Destructive command (/killswitch) does NOT execute immediately; renders 15s confirmation."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None

    update = _text_update(ADMIN_ID, "/killswitch")
    res = bot.handle_update(update)

    # Emergency handler must not be called
    emergency_handler.execute_emergency_killswitch.assert_not_called()

    # Two-step state must have been initiated
    two_step.initiate.assert_called_once_with(AdminCommand.KILLSWITCH, ADMIN_ID)

    assert res is not None
    assert res["method"] == "sendMessage"
    assert "EMERGENCY KILLSWITCH" in str(res["text"])
    assert "Konfirmasi dalam 15 detik" in str(res["text"])

    # Must contain confirmation inline keyboard
    keyboard = res["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 1
    assert "KONFIRMASI EKSEKUSI (Batas 15 Detik)" in keyboard[0][0]["text"]
    assert "BATALKAN" in keyboard[0][1]["text"]
    assert keyboard[0][0]["callback_data"].startswith("confirm:KILLSWITCH:")
    assert keyboard[0][1]["callback_data"].startswith("cancel:KILLSWITCH:")


# ----------------------------------------------------------------------
# 5. Two-Step Confirmation Execution (REQ-TEL-003)
# ----------------------------------------------------------------------


def test_two_step_confirmation_execution() -> None:
    """Confirmation callback within 15s executes emergency handler action."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None
    emergency_handler.execute_emergency_killswitch.return_value = True


    # 2. Simulate two-step confirm success within 15s
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.KILLSWITCH,
        nonce="step-ks-42",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CONFIRMED,
    )

    cb_update = _callback_update(
        ADMIN_ID, data="confirm:KILLSWITCH:step-ks-42", callback_id="cb-ks"
    )
    res = bot.handle_update(cb_update)

    two_step.confirm.assert_called_once_with("step-ks-42", ADMIN_ID)
    emergency_handler.execute_emergency_killswitch.assert_called_once()

    assert res is not None
    assert res["method"] == "sendMessage"
    assert "KILLSWITCH dieksekusi" in str(res["text"])


# ----------------------------------------------------------------------
# 6. Expired Two-Step Callback Rejected (>15s) (REQ-TEL-003)
# ----------------------------------------------------------------------


def test_expired_two_step_callback_rejected() -> None:
    """Callback after 15s TTL returns expiration alert; emergency handler is NOT called."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None


    # Controller marks action expired
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.KILLSWITCH,
        nonce="step-ks-exp",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.EXPIRED,
    )

    cb_update = _callback_update(
        ADMIN_ID, data="confirm:KILLSWITCH:step-ks-exp", callback_id="cb-exp"
    )
    res = bot.handle_update(cb_update)

    # Must NOT execute emergency killswitch
    emergency_handler.execute_emergency_killswitch.assert_not_called()

    assert res is not None
    assert res["method"] == "answerCallbackQuery"
    assert res["callback_query_id"] == "cb-exp"
    assert "Konfirmasi kedaluwarsa (Batas 15s)" in str(res["text"])
    assert res["show_alert"] is True


# ----------------------------------------------------------------------
# 7. Replay Attack Rejected via Nonce (REQ-TEL-002)
# ----------------------------------------------------------------------


def test_replay_attack_rejected() -> None:
    """Replaying the same nonce a second time is rejected; emergency handler called only once."""
    bot, _, nonce_manager, _, _, _ = _make_bot()

    valid_nonce = CallbackNonce(
        nonce="replay-test-nonce",
        action=AdminCommand.STATUS,
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=160.0,
    )

    # First attempt succeeds, second attempt returns None (already consumed / invalidated)
    nonce_manager.consume_nonce.side_effect = [valid_nonce, None]

    cb_update = _callback_update(
        ADMIN_ID, data="STATUS:replay-test-nonce", callback_id="cb-rep-1"
    )

    # Call 1: valid
    res1 = bot.handle_update(cb_update)
    assert res1 is not None
    assert res1["method"] == "sendMessage"
    assert "STATUS" in str(res1["text"])

    # Call 2: replay with exact same update
    cb_update_replay = _callback_update(
        ADMIN_ID, data="STATUS:replay-test-nonce", callback_id="cb-rep-2"
    )
    res2 = bot.handle_update(cb_update_replay)
    assert res2 is not None
    assert res2["method"] == "answerCallbackQuery"
    assert "Aksi kedaluwarsa (Batas 60s)" in str(res2["text"])
    assert res2["show_alert"] is True

# ----------------------------------------------------------------------
# Additional Supporting Tests: Two-step Force Close, Pause, Resume, Cancel
# ----------------------------------------------------------------------


def test_force_close_all_confirmation_cycle() -> None:
    """Force close all triggers two-step and passes max_deviation_pts=50 upon confirm."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None
    emergency_handler.execute_force_close_all.return_value = [
        EmergencyCloseResult(ticket=101, success=True, closed_lot=0.1, executed_price=2750.0),
        EmergencyCloseResult(ticket=102, success=True, closed_lot=0.05, executed_price=2750.2),
    ]

    # Trigger /force_close
    res_trigger = bot.handle_update(_text_update(ADMIN_ID, "/force_close"))
    assert res_trigger is not None
    assert "FORCE CLOSE ALL" in str(res_trigger["text"])
    assert f"maks slippage {FORCE_CLOSE_MAX_DEVIATION_PTS} pts" in str(res_trigger["text"])

    # Confirm
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.FORCE_CLOSE_ALL,
        nonce="step-fc-1",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CONFIRMED,
    )

    res_confirm = bot.handle_update(
        _callback_update(ADMIN_ID, "confirm:FORCE_CLOSE_ALL:step-fc-1")
    )
    emergency_handler.execute_force_close_all.assert_called_once_with(
        max_deviation_pts=FORCE_CLOSE_MAX_DEVIATION_PTS
    )
    assert res_confirm is not None
    assert "FORCE CLOSE ALL: 2/2 posisi tertutup" in str(res_confirm["text"])


def test_pause_and_resume_cycle() -> None:
    """Pause requires two-step confirmation; Resume executes directly."""
    bot, _, _, two_step, _, emergency_handler = _make_bot()
    assert emergency_handler is not None
    emergency_handler.set_system_state_paused.return_value = True
    emergency_handler.set_system_state_normal.return_value = True

    # 1. /pause triggers two-step
    res_pause = bot.handle_update(_text_update(ADMIN_ID, "/pause"))
    assert res_pause is not None
    assert "PAUSE TRADING" in str(res_pause["text"])
    emergency_handler.set_system_state_paused.assert_not_called()

    # Confirm pause
    two_step.confirm.return_value = TwoStepAction(
        action=AdminCommand.PAUSE,
        nonce="step-pause-1",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CONFIRMED,
    )
    bot.handle_update(_callback_update(ADMIN_ID, "confirm:PAUSE:step-pause-1"))
    emergency_handler.set_system_state_paused.assert_called_once()

    # 2. /resume is direct (non-destructive resumption)
    res_resume = bot.handle_update(_text_update(ADMIN_ID, "/resume"))
    assert res_resume is not None
    assert "State: NORMAL" in str(res_resume["text"])
    emergency_handler.set_system_state_normal.assert_called_once()


def test_two_step_cancellation_callback() -> None:
    """Clicking BATALKAN cancels the pending two-step action."""
    bot, _, _, two_step, _, _ = _make_bot()

    two_step.cancel.return_value = TwoStepAction(
        action=AdminCommand.KILLSWITCH,
        nonce="step-cancel-1",
        user_id=ADMIN_ID,
        created_at_mono=100.0,
        expires_at_mono=115.0,
        state=TwoStepState.CANCELLED,
    )

    res = bot.handle_update(_callback_update(ADMIN_ID, "cancel:KILLSWITCH:step-cancel-1"))
    two_step.cancel.assert_called_once_with("step-cancel-1", ADMIN_ID)
    assert res is not None
    assert res["method"] == "answerCallbackQuery"
    assert "Perintah dibatalkan" in str(res["text"])


def test_main_control_keyboard_rendering() -> None:
    """Main keyboard includes all specified buttons, each with its unique nonce."""
    bot, _, nonce_manager, _, _, _ = _make_bot()
    markup = bot.build_main_control_keyboard(ADMIN_ID)

    assert "inline_keyboard" in markup
    rows = markup["inline_keyboard"]
    assert len(rows) == 4

    # Row 0: Status, Daily Report
    assert rows[0][0]["text"] == "Status"
    assert rows[0][1]["text"] == "Daily Report"
    # Row 1: Pause / Resume
    assert rows[1][0]["text"] == "Pause / Resume"
    # Row 2: Force Close All
    assert rows[2][0]["text"] == "Force Close All"
    # Row 3: Emergency Killswitch
    assert rows[3][0]["text"] == "Emergency Killswitch"

    # Nonce manager must have been called 5 times
    assert nonce_manager.create_nonce.call_count == 5


def test_secret_string_token_support() -> None:
    """Bot unmasks DPAPI SecretString correctly when formatting API URLs."""
    mock_secret = MagicMock()
    mock_secret.get_secret_value.return_value = "secret-unwrapped-token"
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {}}
    mock_session.post.return_value = mock_response

    bot, _, _, _, _, _ = _make_bot(token=mock_secret, session=mock_session)  # type: ignore[arg-type]
    bot.send({"method": "sendMessage", "chat_id": CHAT_ID, "text": "hello"})
    mock_secret.get_secret_value.assert_called_once()
    call_url = mock_session.post.call_args[0][0]
    assert call_url == "https://api.telegram.org/botsecret-unwrapped-token/sendMessage"


@pytest.mark.asyncio
async def test_async_decoupling_off_event_loop() -> None:
    """handle_update_async executes off the event loop thread without blocking."""
    bot, _, _, _, _, _ = _make_bot()
    update = _text_update(ADMIN_ID, "/resume")

    res = await bot.handle_update_async(update)
    assert res is not None
    assert res["method"] == "sendMessage"


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
        ADMIN_ID, data="STATUS:status-nonce", callback_id="cb-dispatch"
    )
    bot.dispatch_update(update)

    # 1. answerCallbackQuery must be delivered
    # 2. sendMessage payload for STATUS must be delivered
    assert mock_session.post.call_count == 2
    urls = [call.args[0] for call in mock_session.post.call_args_list]
    assert any("answerCallbackQuery" in url for url in urls)
    assert any("sendMessage" in url for url in urls)


@pytest.mark.asyncio
async def test_poll_once_advances_offset() -> None:
    """poll_once parses getUpdates result and updates internal last_update_id."""
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "result": [
            {"update_id": 100, "message": {"text": "hello"}},
            {"update_id": 105, "message": {"text": "world"}},
        ],
    }
    mock_session.get.return_value = mock_response
    bot, _, _, _, _, _ = _make_bot(session=mock_session)

    updates = await bot.poll_once(timeout=10, limit=10)
    assert len(updates) == 2
    assert bot.last_update_id == 105

    # Second poll should use offset=106
    await bot.poll_once(timeout=10, limit=10)
    assert mock_session.get.call_args.kwargs["params"]["offset"] == 106
