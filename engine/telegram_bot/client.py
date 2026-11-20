"""Telegram control bot client: command dispatcher, inline keyboards, HTTP transport.

Module: engine.telegram_bot.client
Responsibility: Translates Telegram Bot API updates into authorized control actions.
- Silent drop for any non-whitelisted / rate-limited sender (REQ-TEL-001).
- Single-entry point (/menu) renders conceptual dashboard and inline control panel.
- Inline buttons carry single-use 60s nonces in <verb>:<action>:<nonce> format (REQ-TEL-002).
- Destructive commands require the 15s two-step confirmation (REQ-TEL-003).
- Stateful dashboard editing via editMessageText prevents chat room spam (REQ-TEL-004).
- Emergency execution is delegated to ExecutionEmergencyHandler, never executed inline
  on the polling thread.

handle_update() is a pure dispatcher: it returns the outgoing Bot API payload and
performs no I/O, which keeps authorization and replay tests deterministic. dispatch_update()
and poll_once() own the HTTP boundary.
Owner: aeterna-execution
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Final

import requests

from engine.monitoring.types import DailyMetrics
from engine.telegram_bot.interfaces import (
    AdminAuthenticator,
    DailyMetricsCollector,
    ExecutionEmergencyHandler,
    NonceManager,
    TwoStepController,
)
from engine.telegram_bot.templates import DailyDashboardData, format_daily_dashboard
from engine.telegram_bot.types import AdminCommand, TwoStepAction, TwoStepState

if TYPE_CHECKING:
    from engine.security.dpapi import SecretString

logger = logging.getLogger(__name__)

API_BASE_URL: Final[str] = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
FORCE_CLOSE_MAX_DEVIATION_PTS: Final[int] = 50

_TWO_STEP_PROMPT: Final[dict[AdminCommand, str]] = {
    AdminCommand.PAUSE: "PAUSE TRADING - konfirmasi dalam 15 detik.",
    AdminCommand.FORCE_CLOSE_ALL: (
        "FORCE CLOSE ALL - seluruh posisi akan dilikuidasi "
        f"(maks slippage {FORCE_CLOSE_MAX_DEVIATION_PTS} pts). Konfirmasi dalam 15 detik."
    ),
    AdminCommand.KILLSWITCH: (
        "EMERGENCY KILLSWITCH - engine dihentikan dan lockfile darurat ditulis. "
        "Konfirmasi dalam 15 detik."
    ),
}


class TelegramControlBot:
    """Authorized admin control panel over the Telegram Bot API.

    Args:
        token: Bot token, plain string or DPAPI-backed SecretString.
        authenticator: Whitelist + rate limit gate (REQ-TEL-001).
        nonce_manager: Single-use 60s nonce issuer/consumer (REQ-TEL-002).
        two_step: 15s two-step confirmation controller (REQ-TEL-003).
        metrics_collector: Daily metrics source for dashboard and daily report.
        emergency_handler: Non-blocking execution bridge for destructive actions.
        session: Mockable HTTP transport; defaults to an isolated requests.Session.
        api_base_url: Bot API root, overridable for local mock servers.
        timeout: Per-request HTTP timeout in seconds.
        strategy_name: Name of active trading strategy displayed on dashboard.
    """

    _DESTRUCTIVE: Final[frozenset[AdminCommand]] = frozenset(
        {AdminCommand.PAUSE, AdminCommand.FORCE_CLOSE_ALL, AdminCommand.KILLSWITCH}
    )

    def __init__(
        self,
        token: str | SecretString,
        authenticator: AdminAuthenticator,
        nonce_manager: NonceManager,
        two_step: TwoStepController,
        metrics_collector: DailyMetricsCollector | None = None,
        emergency_handler: ExecutionEmergencyHandler | None = None,
        session: requests.Session | None = None,
        api_base_url: str = API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        strategy_name: str = "BREAKOUT_M15",
    ) -> None:
        self._token = token
        self._authenticator = authenticator
        self._nonce_manager = nonce_manager
        self._two_step = two_step
        self._metrics_collector = metrics_collector
        self._emergency_handler = emergency_handler
        self._session = session if session is not None else requests.Session()
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout = timeout
        self._strategy_name = strategy_name
        self._is_paused = False
        self._is_killed = False
        self._last_update_id = 0

    @property
    def last_update_id(self) -> int:
        """Most recent update_id processed from long-polling."""
        return self._last_update_id

    @property
    def is_paused(self) -> bool:
        """Whether the engine control state is currently PAUSED."""
        return self._is_paused

    # ------------------------------------------------------------------
    # Update dispatching
    # ------------------------------------------------------------------

    def handle_update(self, update: dict[str, Any]) -> dict[str, Any] | None:
        """Authorize and dispatch one Telegram update; return the Bot API payload to send."""
        message = update.get("message")
        callback = update.get("callback_query")
        envelope = callback if isinstance(callback, dict) else message
        if not isinstance(envelope, dict):
            return None

        user_id = self._extract_user_id(envelope)
        if user_id is None:
            return None

        auth = self._authenticator.authenticate(user_id)
        if not auth.allowed:
            # Silent drop: the sender must learn nothing about the panel.
            logger.warning(
                "Telegram update dropped: user_id=%s reason=%s", user_id, auth.reason
            )
            return None

        if callback is not None:
            return self._handle_callback(callback, user_id)
        if message is not None:
            return self._handle_message(message, user_id)
        return None

    async def handle_update_async(
        self, update: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Dispatch off the event loop so emergency execution never blocks MT5 polling."""
        return await asyncio.to_thread(self.handle_update, update)

    def dispatch_update(self, update: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch and deliver: answer the callback query, then send the payload."""
        payload = self.handle_update(update)
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            callback_id = callback.get("id")
            already_answered = (
                isinstance(payload, dict)
                and payload.get("method") == "answerCallbackQuery"
            )
            if isinstance(callback_id, str) and not already_answered:
                self.send(
                    {"method": "answerCallbackQuery", "callback_query_id": callback_id}
                )
        if payload is not None:
            self.send(payload)
        return payload

    async def poll_once(
        self, timeout: int = 30, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch one long-polling batch (outbound HTTPS only) and advance the offset."""
        url = self._api_url("getUpdates")
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if self._last_update_id:
            params["offset"] = self._last_update_id + 1

        def _fetch() -> requests.Response:
            return self._session.get(
                url, params=params, timeout=self._timeout + timeout
            )

        try:
            response = await asyncio.to_thread(_fetch)
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            # Never log the URL: it embeds the bot token.
            logger.warning("Telegram getUpdates failed: %s", type(exc).__name__)
            return []

        if response.status_code != 200 or not body.get("ok", False):
            logger.warning(
                "Telegram getUpdates rejected: status=%s", response.status_code
            )
            return []

        updates: list[dict[str, Any]] = body.get("result", [])
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int) and update_id > self._last_update_id:
                self._last_update_id = update_id
        return updates

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    def send(self, payload: dict[str, Any]) -> bool:
        """POST one Bot API method. Returns False on any transport/API failure."""
        method = payload.get("method")
        if not isinstance(method, str):
            return False
        body = {key: value for key, value in payload.items() if key != "method"}
        try:
            response = self._session.post(
                self._api_url(method), json=body, timeout=self._timeout
            )
            return response.status_code == 200 and bool(
                response.json().get("ok", False)
            )
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Telegram %s failed: %s", method, type(exc).__name__)
            return False

    def send_photo(self, chat_id: int, photo: bytes, caption: str) -> bool:
        """Send photo via Telegram Bot API sendPhoto multipart/form-data.

        Enforces admin-only authentication guard (REQ-TEL-001) and returns False
        on non-admin recipient or transport error without leaking secrets.
        """
        auth = self._authenticator.authenticate(chat_id)
        if not auth.allowed:
            logger.warning(
                "Telegram sendPhoto dropped: chat_id=%s reason=%s",
                chat_id,
                auth.reason,
            )
            return False

        url = self._api_url("sendPhoto")
        data = {"chat_id": str(chat_id), "caption": caption}
        files = {"photo": ("observation_chart.png", photo, "image/png")}
        try:
            response = self._session.post(
                url, data=data, files=files, timeout=self._timeout
            )
            return response.status_code == 200 and bool(
                response.json().get("ok", False)
            )
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Telegram sendPhoto failed: %s", type(exc).__name__)
            return False

    def push_dashboard(self, chat_id: int) -> bool:
        """Proactively send the /menu dashboard (startup notice, no prior user message)."""
        return self.send_initial_dashboard(chat_id)

    def _api_url(self, method: str) -> str:
        return f"{self._api_base_url}/bot{self._bot_token()}/{method}"

    def _bot_token(self) -> str:
        token = self._token
        if isinstance(token, str):
            return token
        return token.get_secret_value()

    # ------------------------------------------------------------------
    # Inline keyboards
    # ------------------------------------------------------------------

    def build_main_control_keyboard(self, user_id: int) -> dict[str, Any]:
        """Render the main control panel; every button carries its own 60s nonce."""

        def button(label: str, action: AdminCommand) -> dict[str, str]:
            nonce = self._nonce_manager.create_nonce(action, user_id).nonce
            return {"text": label, "callback_data": f"action:{action.value}:{nonce}"}

        pause_or_resume = (
            button("▶️ RESUME ENGINE", AdminCommand.RESUME)
            if self._is_paused
            else button("⏸ PAUSE ENGINE", AdminCommand.PAUSE)
        )

        return {
            "inline_keyboard": [
                [
                    pause_or_resume,
                    button("📊 DAILY REPORT", AdminCommand.DAILY_REPORT),
                ],
                [button("⚠️ FORCE CLOSE ALL POSITIONS", AdminCommand.FORCE_CLOSE_ALL)],
                [button("🛑 EMERGENCY KILLSWITCH (SHUTDOWN)", AdminCommand.KILLSWITCH)],
            ]
        }

    def build_report_keyboard(self, user_id: int) -> dict[str, Any]:
        """Render keyboard for daily report view with refresh and return to menu."""
        nonce_refresh = self._nonce_manager.create_nonce(
            AdminCommand.DAILY_REPORT, user_id
        ).nonce
        nonce_menu = self._nonce_manager.create_nonce(
            AdminCommand.STATUS, user_id
        ).nonce
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "🔄 REFRESH REPORT",
                        "callback_data": f"action:{AdminCommand.DAILY_REPORT.value}:{nonce_refresh}",
                    },
                    {
                        "text": "🔙 DASHBOARD MENU",
                        "callback_data": f"action:{AdminCommand.STATUS.value}:{nonce_menu}",
                    },
                ]
            ]
        }

    def build_two_step_confirmation_keyboard(
        self, action: AdminCommand, nonce: str
    ) -> dict[str, Any]:
        """Render the 15s confirmation row bound to a single-use callback nonce."""
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "⚠️ KONFIRMASI EKSEKUSI (Batas 15 Detik)",
                        "callback_data": f"confirm:{action.value}:{nonce}",
                    },
                    {
                        "text": "❌ BATALKAN",
                        "callback_data": f"cancel:{action.value}:{nonce}",
                    },
                ]
            ]
        }

    # ------------------------------------------------------------------
    # Message / callback handlers
    # ------------------------------------------------------------------

    def _handle_message(
        self, message: dict[str, Any], user_id: int
    ) -> dict[str, Any] | None:
        chat_id = self._chat_id(message)
        text = message.get("text")
        if chat_id is None or not isinstance(text, str):
            return None

        tokens = text.strip().split()
        if not tokens:
            return None

        # Mandat 1: Single-Entry Point (/menu).
        # All incoming slash commands (/menu, /status, /report, /pause, /resume, /force_close, /killswitch, etc.)
        # and arbitrary text divert directly to the /menu dashboard without triggering split execution.
        dashboard_text = self._render_dashboard(user_id)
        keyboard = self.build_main_control_keyboard(user_id)
        return self._message(chat_id, dashboard_text, keyboard)

    def _handle_callback(
        self, callback: dict[str, Any], user_id: int
    ) -> dict[str, Any] | None:
        callback_id = callback.get("id")
        data = callback.get("data")
        nested_message = callback.get("message")
        chat_id = (
            self._chat_id(nested_message) if isinstance(nested_message, dict) else None
        )
        message_id = (
            self._message_id(nested_message)
            if isinstance(nested_message, dict)
            else None
        )
        if not isinstance(callback_id, str) or not isinstance(data, str):
            return None

        parts = data.split(":")
        verb = parts[0]
        nonce = parts[-1]

        if verb == "cancel":
            return self._cancel_two_step(
                callback_id, chat_id, message_id, nonce, user_id
            )
        if verb == "confirm":
            return self._confirm_two_step(
                callback_id, chat_id, message_id, nonce, user_id
            )

        consumed = self._nonce_manager.consume_nonce(nonce, user_id)
        if consumed is None:
            return self._alert(callback_id, "Aksi kedaluwarsa (Batas 60s).")
        if chat_id is None:
            return self._alert(callback_id, "Chat tidak dikenali.")
        return self._run_action(consumed.action, chat_id, message_id, user_id)

    def _run_action(
        self,
        action: AdminCommand,
        chat_id: int,
        message_id: int | None,
        user_id: int,
    ) -> dict[str, Any]:
        if action in self._DESTRUCTIVE:
            return self._initiate_two_step(action, chat_id, message_id, user_id)

        if action is AdminCommand.STATUS:
            dashboard_text = self._render_dashboard(user_id)
            keyboard = self.build_main_control_keyboard(user_id)
            if message_id is not None:
                return self._edit_message(chat_id, message_id, dashboard_text, keyboard)
            return self._message(chat_id, dashboard_text, keyboard)

        if action is AdminCommand.DAILY_REPORT:
            report_text = self._render_daily_report()
            keyboard = self.build_report_keyboard(user_id)
            if message_id is not None:
                return self._edit_message(chat_id, message_id, report_text, keyboard)
            return self._message(chat_id, report_text, keyboard)

        if action is AdminCommand.RESUME:
            self._resume(user_id)
            dashboard_text = self._render_dashboard(user_id)
            keyboard = self.build_main_control_keyboard(user_id)
            if message_id is not None:
                return self._edit_message(chat_id, message_id, dashboard_text, keyboard)
            return self._message(chat_id, dashboard_text, keyboard)

        dashboard_text = self._render_dashboard(user_id)
        keyboard = self.build_main_control_keyboard(user_id)
        if message_id is not None:
            return self._edit_message(chat_id, message_id, dashboard_text, keyboard)
        return self._message(chat_id, dashboard_text, keyboard)

    def _initiate_two_step(
        self,
        action: AdminCommand,
        chat_id: int,
        message_id: int | None,
        user_id: int,
    ) -> dict[str, Any]:
        pending = self._two_step.initiate(action, user_id)
        keyboard = self.build_two_step_confirmation_keyboard(action, pending.nonce)
        prompt_text = _TWO_STEP_PROMPT[action]
        if message_id is not None:
            return self._edit_message(chat_id, message_id, prompt_text, keyboard)
        return self._message(chat_id, prompt_text, keyboard)

    def _confirm_two_step(
        self,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        nonce: str,
        user_id: int,
    ) -> dict[str, Any] | None:
        confirmed = self._two_step.confirm(nonce, user_id)
        if confirmed.state is TwoStepState.EXPIRED:
            return self._alert(callback_id, "Konfirmasi kedaluwarsa (Batas 15s).")
        if confirmed.state is not TwoStepState.CONFIRMED:
            return self._alert(callback_id, "Konfirmasi dibatalkan.")
        if chat_id is None:
            return self._alert(callback_id, "Chat tidak dikenali.")

        self._execute(confirmed, user_id)

        # Mandat 3: Stateful Dashboard Editing (Anti-Spam Mandate)
        # Message is re-rendered to updated dashboard with latest state.
        dashboard_text = self._render_dashboard(user_id)
        keyboard = self.build_main_control_keyboard(user_id)
        if message_id is not None:
            return self._edit_message(chat_id, message_id, dashboard_text, keyboard)
        return self._message(chat_id, dashboard_text, keyboard)

    def _cancel_two_step(
        self,
        callback_id: str,
        chat_id: int | None,
        message_id: int | None,
        nonce: str,
        user_id: int,
    ) -> dict[str, Any] | None:
        self._two_step.cancel(nonce, user_id)
        if chat_id is not None and message_id is not None:
            # Mandat 3: Cancellation restores active dashboard state
            return self._edit_message(
                chat_id,
                message_id,
                self._render_dashboard(user_id),
                self.build_main_control_keyboard(user_id),
            )
        return self._alert(callback_id, "Perintah dibatalkan.")

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    def _execute(self, confirmed: TwoStepAction, user_id: int) -> str:
        handler = self._emergency_handler
        if handler is None:
            logger.error(
                "Emergency handler missing for %s by user_id=%s",
                confirmed.action.value,
                user_id,
            )
            return "Emergency handler belum dikonfigurasi; aksi TIDAK dieksekusi."

        logger.warning(
            "Executing %s via Telegram admin user_id=%s",
            confirmed.action.value,
            user_id,
        )
        if confirmed.action is AdminCommand.KILLSWITCH:
            ok = handler.execute_emergency_killswitch()
            if ok:
                self._is_killed = True
            return (
                "KILLSWITCH dieksekusi."
                if ok
                else "KILLSWITCH gagal (lihat log engine)."
            )
        if confirmed.action is AdminCommand.FORCE_CLOSE_ALL:
            results = handler.execute_force_close_all(
                max_deviation_pts=FORCE_CLOSE_MAX_DEVIATION_PTS
            )
            closed = sum(1 for result in results if result.success)
            return f"FORCE CLOSE ALL: {closed}/{len(results)} posisi tertutup."
        if confirmed.action is AdminCommand.PAUSE:
            ok = handler.set_system_state_paused()
            if ok:
                self._is_paused = True
            return "State: PAUSED." if ok else "Gagal mengubah state ke PAUSED."
        return "Aksi tidak didukung."

    def _resume(self, user_id: int) -> str:
        handler = self._emergency_handler
        if handler is None:
            logger.error("Emergency handler missing for RESUME by user_id=%s", user_id)
            return "Emergency handler belum dikonfigurasi; state TIDAK diubah."
        logger.warning("Resuming system state via Telegram admin user_id=%s", user_id)
        ok = handler.set_system_state_normal()
        if ok:
            self._is_paused = False
        return "State: NORMAL." if ok else "Gagal mengubah state ke NORMAL."

    def send_initial_dashboard(self, admin_id: int) -> bool:
        """Proactively push the /menu Single-Entry Dashboard to the admin upon startup."""
        text = self._render_dashboard(admin_id)
        keyboard = self.build_main_control_keyboard(admin_id)
        payload = self._message(admin_id, text, keyboard)
        return self.send(payload)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_dashboard(self, _user_id: int = 0) -> str:
        """Render conceptual single-entry dashboard layout."""
        status_str = f"🟢 ACTIVE ({self._strategy_name})"
        if self._is_killed:
            status_str = "🛑 SHUTDOWN (KILLSWITCH)"
        elif self._is_paused:
            status_str = "⏸ PAUSED"

        pnl_usd = 0.0
        pnl_pct = 0.0
        max_dd_pct = 0.0
        active_positions = 0

        collector = self._metrics_collector
        if collector is not None:
            try:
                metrics = collector.collect_daily_metrics()
                pnl_usd = float(metrics.net_pnl_usd)
                explicit_pct = getattr(metrics, "daily_pnl_pct", None)
                if explicit_pct is not None:
                    pnl_pct = float(explicit_pct)
                else:
                    equity = float(metrics.current_account_equity)
                    if equity > 0:
                        pnl_pct = (pnl_usd / equity) * 100.0
                max_dd_pct = float(metrics.max_drawdown_pct)
                active_positions = int(metrics.active_positions_count)
            except (RuntimeError, ValueError, OSError, TypeError) as exc:
                logger.warning("Metrics collection failed for dashboard: %s", exc)

        pnl_sign = "+" if pnl_usd >= 0 else "-"
        pct_sign = "+" if pnl_pct >= 0 else ""
        pnl_formatted = f"{pnl_sign}${abs(pnl_usd):,.2f} ({pct_sign}{pnl_pct:.2f}%)"

        dd_formatted = f"-{abs(max_dd_pct):.2f}%" if max_dd_pct != 0 else "0.00%"

        return (
            "=================================\n"
            "AETERNA QUANT ENGINE - CONTROL PANEL\n"
            f"Status       : {status_str}\n"
            f"Daily PnL    : {pnl_formatted}\n"
            f"Max DD       : {dd_formatted}\n"
            f"Posisi Aktif : {active_positions} (XAUUSD)\n"
            "================================="
        )

    def _render_status(self, _user_id: int = 0) -> str:
        """Alias for _render_dashboard for backward compatibility."""
        return self._render_dashboard(_user_id)

    def _render_daily_report(self) -> str:
        collector = self._metrics_collector
        if collector is None:
            return "Metrics collector belum dikonfigurasi; dashboard tidak tersedia."

        dashboard = getattr(collector, "generate_dashboard_report", None)
        try:
            if callable(dashboard):
                # DailyMetricsReporter owns the canonical template mapping.
                return str(dashboard())
            metrics = collector.collect_daily_metrics()
            return format_daily_dashboard(self._to_dashboard_data(metrics))
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("Daily report generation failed: %s", exc)
            return f"Gagal menyusun dashboard harian: {exc}"

    @staticmethod
    def _to_dashboard_data(metrics: DailyMetrics) -> DailyDashboardData:
        # ponytail: DailyMetrics carries no pips/spread/paused-event counters, so those
        # three render as zero until a reporter exposes generate_dashboard_report().
        return DailyDashboardData(
            date_str=metrics.date_utc,
            session_pnl_usd=metrics.net_pnl_usd,
            session_pnl_pips=0.0,
            total_trades=metrics.total_trades,
            wins=metrics.win_trades,
            losses=metrics.loss_trades,
            max_drawdown_pct=metrics.max_drawdown_pct,
            paused_events_count=0,
            avg_spread_pips=0.0,
            myfxbook_url=metrics.myfxbook_url or "-",
        )

    # ------------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _message(
        chat_id: int, text: str, keyboard: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": text,
        }
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        return payload

    @staticmethod
    def _edit_message(
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "method": "editMessageText",
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        return payload

    @staticmethod
    def _alert(callback_id: str, text: str) -> dict[str, Any]:
        return {
            "method": "answerCallbackQuery",
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": True,
        }

    @staticmethod
    def _extract_user_id(envelope: dict[str, Any]) -> int | None:
        sender = envelope.get("from")
        if not isinstance(sender, dict):
            return None
        user_id = sender.get("id")
        return user_id if isinstance(user_id, int) else None

    @staticmethod
    def _chat_id(message: dict[str, Any]) -> int | None:
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return None
        chat_id = chat.get("id")
        return chat_id if isinstance(chat_id, int) else None

    @staticmethod
    def _message_id(message: dict[str, Any]) -> int | None:
        mid = message.get("message_id")
        return mid if isinstance(mid, int) else None
