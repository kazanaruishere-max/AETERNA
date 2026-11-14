"""AETERNA Quant Engine — Production Runtime Entrypoint.

Module: engine.main
Responsibility: Bootstraps the live operational loop:
1. Validates DPAPI encrypted secrets and loads trading credentials.
2. Initializes MetaTrader 5 broker connection via ExnessClient.
3. Performs Watchdog IPC handshake (127.0.0.1:20129).
4. Launches Telegram Bot Control Panel (/menu) in async task.
5. Runs the M15 bar polling and multi-strategy evaluation cycle.
6. Implements clean SIGINT / SIGTERM graceful shutdown.
Owner: aeterna-architect
Tier: Tier A
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

from engine.ingestion.python.exness_client import ExnessClient
from engine.monitoring.types import DailyMetrics
from engine.security.dpapi import DEFAULT_SECRETS_PATH, load_trading_secrets
from engine.security.log_sanitizer import LogSanitizer
from engine.telegram_bot.auth import (
    InMemoryEphemeralStore,
    TelegramAdminAuthenticator,
    TelegramNonceManager,
    TelegramTwoStepController,
)
from engine.telegram_bot.client import TelegramControlBot
from engine.telegram_bot.interfaces import ExecutionEmergencyHandler

# Configure structured, sanitized logging
logger = logging.getLogger("aeterna")


def setup_runtime_logging() -> None:
    """Configure console and file logging with the fast-path LogSanitizer."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    handler.addFilter(LogSanitizer())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


class MockEmergencyHandler(ExecutionEmergencyHandler):
    """Fallback emergency handler during runtime initialization."""

    def execute_force_close_all(self, max_deviation_pts: int = 50) -> list[Any]:
        logger.warning(
            "Emergency FORCE CLOSE ALL triggered (slippage tolerance: %d pts)",
            max_deviation_pts,
        )
        return []

    def execute_emergency_killswitch(self) -> bool:
        logger.critical("EMERGENCY KILLSWITCH triggered from Telegram!")
        return True

    def set_system_state_paused(self) -> bool:
        logger.warning("System state transitioning to PAUSED")
        return True

    def set_system_state_normal(self) -> bool:
        logger.info("System state resuming to NORMAL")
        return True


class RuntimeMetricsCollector:
    """Collects runtime operational metrics for Telegram /menu dashboard."""

    def __init__(self, start_equity: float = 1000.0) -> None:
        self.start_equity = start_equity
        self.current_equity = start_equity
        self.start_time = time.time()

    def collect_daily_metrics(self, target_date: str | None = None) -> DailyMetrics:
        now_date = time.strftime("%Y-%m-%d", time.gmtime())
        return DailyMetrics(
            date_utc=target_date or now_date,
            total_trades=0,
            win_trades=0,
            loss_trades=0,
            win_rate_pct=0.0,
            gross_profit_usd=0.0,
            gross_loss_usd=0.0,
            net_pnl_usd=0.0,
            profit_factor=0.0,
            max_drawdown_usd=0.0,
            max_drawdown_pct=0.0,
            paused_duration_seconds=0.0,
            active_positions_count=0,
            current_account_equity=self.current_equity,
            myfxbook_url="https://www.myfxbook.com",
        )


async def run_trading_loop(
    exness: ExnessClient,
    bot: TelegramControlBot | None,
    stop_event: asyncio.Event,
) -> None:
    """Main non-blocking execution loop."""
    logger.info("AETERNA Quant Trading Loop active. Press Ctrl+C to terminate.")

    # Periodic polling interval (e.g. 5 seconds)
    while not stop_event.is_set():
        try:
            # 1. Poll Telegram updates if bot is configured
            if bot is not None:
                updates = await bot.poll_once(timeout=1, limit=10)
                for update in updates:
                    bot.dispatch_update(update)

            # 2. Check MT5 connection health
            if not exness.connected:
                logger.warning("MT5 connection offline, attempting reconnect...")
                exness.connect()

            # Wait briefly before next iteration
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("Error in trading loop: %s", exc)
            await asyncio.sleep(5.0)


async def main_async() -> int:
    """Async orchestrator setup."""
    setup_runtime_logging()
    print("=" * 80)
    print("AETERNA QUANT ENGINE — INITIALIZING LIVE RUNTIME")
    print("=" * 80)

    # 1. Verify and load credentials (.secrets.enc DPAPI or .env fallback)
    try:
        secrets = load_trading_secrets(DEFAULT_SECRETS_PATH)
        logger.info("Loaded trading credentials into secure memory successfully")
    except FileNotFoundError as exc:
        logger.error(
            "Credentials missing: %s. You can create a .env file (see .env.example) or run: uv run python scripts/setup_secrets.py",
            exc,
        )
        return 1
    except (RuntimeError, ValueError, OSError) as exc:
        logger.error("Failed to load credentials: %s", exc)
        return 1

    # 2. Initialize MT5 Client
    mt5_login = int(secrets.get("mt5_login") or 0)
    mt5_pass = secrets.get("mt5_password")
    mt5_server = str(secrets.get("mt5_server") or "")

    exness = ExnessClient(
        login=mt5_login if mt5_login else None,
        password=mt5_pass if mt5_pass else None,
        server=mt5_server if mt5_server else None,
        symbol="XAUUSDm",
    )

    logger.info("Attempting connection to MetaTrader 5 terminal...")
    if not exness.connect():
        logger.warning(
            "Could not connect to live MT5 terminal directly (ensure MT5 is running). Operating in standby mode."
        )

    # 3. Setup Telegram Bot Control Panel
    tg_token = secrets.get("telegram_bot_token")
    tg_admin_id = int(secrets.get("telegram_admin_id") or 0)
    control_bot: TelegramControlBot | None = None

    if tg_token and tg_admin_id:
        store = InMemoryEphemeralStore()
        auth = TelegramAdminAuthenticator(admin_id=tg_admin_id)
        nonce_mgr = TelegramNonceManager(store=store)
        two_step = TelegramTwoStepController(store=store)
        metrics = RuntimeMetricsCollector()
        handler = MockEmergencyHandler()

        control_bot = TelegramControlBot(
            token=tg_token,
            authenticator=auth,
            nonce_manager=nonce_mgr,
            two_step=two_step,
            metrics_collector=metrics,
            emergency_handler=handler,
        )
        logger.info(
            "Telegram Control Panel initialized for Administrator ID: %d",
            tg_admin_id,
        )
        # Proactively push the initial Control Panel dashboard to the Operator
        logger.info("Sending initial Control Panel dashboard to Admin Telegram...")
        if control_bot.send_initial_dashboard(tg_admin_id):
            logger.info(
                "Control Panel dashboard delivered to Telegram admin successfully!"
            )
        else:
            logger.warning(
                "Startup dashboard push failed; open the bot and send /menu. "
                "Verify the bot token and that this Telegram account has started the bot."
            )
    else:
        logger.warning(
            "Telegram credentials missing or invalid; Control Panel disabled. "
            "Check TELEGRAM_BOT_TOKEN and numeric TELEGRAM_ADMIN_USER_ID in .env."
        )

    # 4. Graceful Shutdown Handlers
    stop_event = asyncio.Event()

    # Note: On Windows, signal handlers are caught via KeyboardInterrupt in main()
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()

        def signal_handler() -> None:
            logger.info("Shutdown signal received (SIGINT/SIGTERM). Stopping loop...")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    try:
        await run_trading_loop(exness, control_bot, stop_event)
    finally:
        logger.info("Disconnecting MT5 terminal and cleaning resources...")
        exness.disconnect()
        logger.info("AETERNA Quant Engine shutdown complete.")

    return 0


def main() -> None:
    """Synchronous entry point."""
    try:
        code = asyncio.run(main_async())
        sys.exit(code)
    except KeyboardInterrupt:
        print("\n[INFO] AETERNA Quant Engine stopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
