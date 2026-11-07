"""Interactive Test Utility for Telegram Bot Control Panel & Channel Broadcast.

Module: scripts.test_telegram_dashboard
Responsibility:
1. Loads encrypted DPAPI secrets (Token, Admin ID, Channel ID).
2. Connects to Telegram Bot API.
3. Tests Bot Control Panel: Sends the conceptual Single-Entry /menu Dashboard to Admin.
4. Starts a real-time polling listener so the Operator can click inline buttons (Pause, Report, Killswitch).
5. Optionally tests Channel broadcast if telegram_channel_id is configured.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.monitoring.types import DailyMetrics
from engine.security.dpapi import DEFAULT_SECRETS_PATH, load_trading_secrets
from engine.telegram_bot.auth import (
    InMemoryEphemeralStore,
    TelegramAdminAuthenticator,
    TelegramNonceManager,
    TelegramTwoStepController,
)
from engine.telegram_bot.client import TelegramControlBot
from engine.telegram_bot.interfaces import ExecutionEmergencyHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aeterna.test_telegram")


class MockEmergencyHandler(ExecutionEmergencyHandler):
    """Safe mock emergency handler for testing Telegram interaction."""

    def __init__(self) -> None:
        self.state = "NORMAL"

    def execute_force_close_all(self, max_deviation_pts: int = 50) -> list[Any]:
        print(f"\n[ACTION TEST] FORCE CLOSE ALL triggered! (Max slippage: {max_deviation_pts} pts)")
        return []

    def execute_emergency_killswitch(self) -> bool:
        print("\n[ACTION TEST] EMERGENCY KILLSWITCH TRIGGERED! Engine shutdown simulation.")
        return True

    def set_system_state_paused(self) -> bool:
        print("\n[ACTION TEST] System state changed to: PAUSED")
        self.state = "PAUSED"
        return True

    def set_system_state_normal(self) -> bool:
        print("\n[ACTION TEST] System state changed to: NORMAL")
        self.state = "NORMAL"
        return True


class MockMetricsCollector:
    """Mock metrics for rendering live numbers on the /menu dashboard."""

    def collect_daily_metrics(self, target_date: str | None = None) -> DailyMetrics:
        return DailyMetrics(
            date_utc="2026-11-07",
            total_trades=2,
            win_trades=2,
            loss_trades=0,
            win_rate_pct=100.0,
            gross_profit_usd=145.50,
            gross_loss_usd=0.0,
            net_pnl_usd=145.50,
            profit_factor=2.45,
            max_drawdown_usd=50.0,
            max_drawdown_pct=0.50,
            paused_duration_seconds=0.0,
            current_account_equity=10145.50,
            active_positions_count=2,
            myfxbook_url="https://www.myfxbook.com",
        )


async def main_async() -> int:
    print("=" * 80)
    print("AETERNA QUANT — TELEGRAM CONTROL PANEL & DASHBOARD TESTER")
    print("=" * 80)

    try:
        secrets = load_trading_secrets(DEFAULT_SECRETS_PATH)
    except FileNotFoundError:
        print("[ERROR] Credentials not found.")
        print("Anda bisa:")
        print("1. Buat file .env (copy dari .env.example) lalu isi TELEGRAM_BOT_TOKEN dan TELEGRAM_ADMIN_USER_ID, ATAU")
        print("2. Jalankan: uv run python scripts/setup_secrets.py")
        return 1
    token = secrets.get("telegram_bot_token")
    raw_admin_id = secrets.get("telegram_admin_id")
    channel_id = secrets.get("telegram_channel_id")

    if not token or not raw_admin_id:
        print("[ERROR] Telegram Bot Token or Admin ID is missing in secrets.")
        return 1

    admin_id = int(raw_admin_id)
    print("[+] Loaded credentials successfully from secure storage")

    # Initialize Telegram Control Bot stack
    store = InMemoryEphemeralStore()
    auth = TelegramAdminAuthenticator(admin_id=admin_id)
    nonce_mgr = TelegramNonceManager(store=store)
    two_step = TelegramTwoStepController(store=store)
    metrics = MockMetricsCollector()
    handler = MockEmergencyHandler()

    bot = TelegramControlBot(
        token=token,
        authenticator=auth,
        nonce_manager=nonce_mgr,
        two_step=two_step,
        metrics_collector=metrics,
        emergency_handler=handler,
    )

    print("\n[*] Sending Single-Entry Dashboard (/menu) to your Telegram Chat...")
    # Send initial menu to Admin
    menu_payload = bot.handle_update({
        "message": {
            "chat": {"id": admin_id},
            "from": {"id": admin_id},
            "text": "/menu",
        }
    })

    if menu_payload:
        success = bot.send(menu_payload)
        if success:
            print("[SUCCESS] Dashboard sent to your Telegram private chat!")
            print("Silakan buka Telegram Anda. Pesan dashboard interaktif sudah masuk.")
        else:
            print("[FAIL] Failed to send message to Telegram API. Check your bot token / network.")
            return 1

    # Optional test for Channel
    if channel_id:
        print("\n[*] Testing Broadcast to Channel...")
        test_msg = (
            "⚡ [TEST SIGNAL BROADCAST — AETERNA QUANT]\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📈 Instrument : XAUUSDm\n"
            "🔍 Status     : Channel Broadcast Connection Verified (OK)\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        chan_success = bot.send({
            "method": "sendMessage",
            "chat_id": channel_id,
            "text": test_msg,
        })
        if chan_success:
            print("[SUCCESS] Test signal broadcasted to signal channel!")
        else:
            print("[!] Warning: Could not post to signal channel.")
            print("    Pastikan Bot sudah di-add sebagai ADMINISTRATOR di channel tersebut.")

    print("\n" + "=" * 80)
    print("LISTENING FOR INTERACTIVE BUTTON CLICKS (Press Ctrl+C to Stop)")
    print("Silakan klik tombol di Telegram Anda: [PAUSE], [REPORT], [FORCE CLOSE], [KILLSWITCH]")
    print("=" * 80)

    try:
        while True:
            updates = await bot.poll_once(timeout=5, limit=10)
            for update in updates:
                bot.dispatch_update(update)
            await asyncio.sleep(0.5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[*] Test stopped cleanly.")

    return 0


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[*] Exited.")
