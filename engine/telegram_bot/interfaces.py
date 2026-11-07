"""Protocol interfaces for decoupled Telegram bot control, auth, and reporting.

Module: engine.telegram_bot.interfaces
Responsibility: Defines abstract contracts (Protocols) connecting Telegram client,
admin authorization, ephemeral replay nonces, two-step confirmation state machines,
daily metrics collectors, and emergency execution bridges.

Concurrency Architecture & Async Decoupling:
- Telegram long-polling / webhook updates MUST operate asynchronously (via asyncio or
  thread-safe dispatch queues) to prevent holding CPython GIL and adding latency to MT5.
- ExecutionEmergencyHandler methods must be callable from background threads or async
  contexts without deadlocking the MT5 execution lock.
Owner: aeterna-architect
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from engine.monitoring.types import DailyMetrics
from engine.telegram_bot.types import (
    AdminCommand,
    AuthResult,
    CallbackNonce,
    EmergencyCloseResult,
    TwoStepAction,
)


@runtime_checkable
class EphemeralStore(Protocol):
    """Thread-safe in-memory cache for ephemeral nonces and two-step actions.

    Enforces memory leak prevention via mandatory sweep_expired() calls.
    """

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store an item with explicit time-to-live expiration."""
        raise NotImplementedError

    def get(self, key: str) -> Any | None:
        """Retrieve an item if it exists and has not expired; returns None if expired/missing."""
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        """Remove an item immediately from the store."""
        raise NotImplementedError

    def sweep_expired(self) -> int:
        """Purge all expired entries from in-memory cache to guarantee zero memory leaks.

        Returns:
            Count of expired items purged in this sweep.
        """
        raise NotImplementedError


@runtime_checkable
class AdminAuthenticator(Protocol):
    """Protocol for Telegram admin authentication and rate limiting (REQ-TEL-001)."""

    def authenticate(self, user_id: int) -> AuthResult:
        """Authenticate user_id against whitelisted TELEGRAM_ADMIN_ID with rate limiting."""
        raise NotImplementedError


@runtime_checkable
class NonceManager(Protocol):
    """Protocol for creating, validating, and consuming 60s ephemeral nonces (REQ-TEL-002)."""

    def create_nonce(
        self,
        action: AdminCommand,
        user_id: int,
        payload: dict[str, Any] | None = None,
    ) -> CallbackNonce:
        """Generate a single-use cryptographically random nonce with 60s TTL."""
        raise NotImplementedError

    def consume_nonce(self, nonce: str, user_id: int) -> CallbackNonce | None:
        """Validate and immediately consume a nonce. Returns None if invalid or expired."""
        raise NotImplementedError


@runtime_checkable
class TwoStepController(Protocol):
    """Protocol for managing 15s two-step confirmations for destructive commands (REQ-TEL-003)."""

    def initiate(self, action: AdminCommand, user_id: int) -> TwoStepAction:
        """Initiate a confirmation cycle (TTL: 15s) for a destructive command."""
        raise NotImplementedError

    def confirm(self, nonce: str, user_id: int) -> TwoStepAction:
        """Confirm and transition a pending two-step action."""
        raise NotImplementedError

    def cancel(self, nonce: str, user_id: int) -> TwoStepAction:
        """Cancel a pending two-step confirmation."""
        raise NotImplementedError


@runtime_checkable
class DailyMetricsCollector(Protocol):
    """Protocol for gathering daily metrics from hot-tier SQLite WAL tables (REQ-TEL-004)."""

    def collect_daily_metrics(self, target_date: str | None = None) -> DailyMetrics:
        """Compile consolidated daily metrics for the given UTC date (default: today)."""
        raise NotImplementedError


@runtime_checkable
class ExecutionEmergencyHandler(Protocol):
    """Thread-safe bridge for invoking emergency execution actions from Telegram bot.

    Designed for non-blocking execution across async and worker thread boundaries.
    """

    def execute_force_close_all(self, max_deviation_pts: int = 50) -> list[EmergencyCloseResult]:
        """Liquidate all open positions immediately with specified maximum slippage tolerance.

        Args:
            max_deviation_pts: Maximum allowed slippage points during emergency closure.

        Returns:
            List of EmergencyCloseResult per attempted position closure.
        """
        raise NotImplementedError

    def execute_emergency_killswitch(self) -> bool:
        """Trigger emergency shutdown, writing physical killswitch lockfile and stopping loop."""
        raise NotImplementedError

    def set_system_state_paused(self) -> bool:
        """Request immediate transition of system state to PAUSED."""
        raise NotImplementedError

    def set_system_state_normal(self) -> bool:
        """Request resumption of system state to NORMAL."""
        raise NotImplementedError
