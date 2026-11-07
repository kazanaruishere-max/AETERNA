"""Admin authentication, ephemeral nonce store, and two-step confirmation state machine.

Module: engine.telegram_bot.auth
Responsibility: Implements thread-safe in-memory cache with monotonic TTL expiration
and zero memory leak sweep, admin whitelist authentication with rate limiting,
cryptographically random 60s single-use replay nonces, and 15s two-step confirmation
cycles for destructive bot actions.
Owner: aeterna-execution
Tier: Tier A
Covers REQ: REQ-TEL-001, REQ-TEL-002, REQ-TEL-003
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from engine.telegram_bot.interfaces import (
    AdminAuthenticator,
    EphemeralStore,
    NonceManager,
    TwoStepController,
)
from engine.telegram_bot.types import (
    AdminCommand,
    AuthResult,
    CallbackNonce,
    TwoStepAction,
    TwoStepState,
)


@dataclass
class _StoreEntry:
    value: Any
    expires_at_mono: float


class InMemoryEphemeralStore:
    """Thread-safe in-memory cache for ephemeral nonces and two-step actions.

    Satisfies EphemeralStore protocol with explicit monotonic TTL and
    memory leak prevention via sweep_expired().
    """

    def __init__(self, time_provider: Callable[[], float] | None = None) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, _StoreEntry] = {}
        self._time_provider: Callable[[], float] = (
            time_provider if time_provider is not None else time.monotonic
        )

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store an item with explicit time-to-live expiration."""
        with self._lock:
            expires_at = self._time_provider() + max(0.0, float(ttl_seconds))
            self._entries[key] = _StoreEntry(value=value, expires_at_mono=expires_at)

    def get(self, key: str) -> Any | None:
        """Retrieve an item if it exists and has not expired; returns None if expired/missing."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if self._time_provider() >= entry.expires_at_mono:
                del self._entries[key]
                return None
            return entry.value

    def delete(self, key: str) -> bool:
        """Remove an item immediately from the store."""
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                return True
            return False

    def sweep_expired(self) -> int:
        """Purge all expired entries from in-memory cache to guarantee zero memory leaks."""
        with self._lock:
            now = self._time_provider()
            expired_keys = [
                k for k, entry in self._entries.items() if now >= entry.expires_at_mono
            ]
            for k in expired_keys:
                del self._entries[k]
            return len(expired_keys)


class TelegramAdminAuthenticator:
    """Authenticates Telegram user_id against whitelisted admin with rate limiting (REQ-TEL-001)."""

    def __init__(
        self,
        admin_id: int,
        rate_limit_per_second: float = 1.0,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self.admin_id: int = int(admin_id)
        self.rate_limit_per_second: float = float(rate_limit_per_second)
        self._lock = threading.RLock()
        self._last_authenticated_mono: float | None = None
        self._time_provider: Callable[[], float] = (
            time_provider if time_provider is not None else time.monotonic
        )

    def authenticate(self, user_id: int) -> AuthResult:
        """Authenticate user_id against whitelisted TELEGRAM_ADMIN_ID with rate limiting."""
        if user_id != self.admin_id:
            return AuthResult(
                allowed=False,
                user_id=user_id,
                reason="UNAUTHORIZED_USER_SILENT_DROP",
            )

        with self._lock:
            now = self._time_provider()
            if self.rate_limit_per_second > 0:
                min_interval = 1.0 / self.rate_limit_per_second
                if self._last_authenticated_mono is not None:
                    elapsed = now - self._last_authenticated_mono
                    if elapsed < min_interval:
                        return AuthResult(
                            allowed=False,
                            user_id=user_id,
                            reason="RATE_LIMIT_EXCEEDED",
                        )
            self._last_authenticated_mono = now
            return AuthResult(
                allowed=True,
                user_id=user_id,
                reason="OK",
            )


class TelegramNonceManager:
    """Manages ephemeral single-use nonces with 60s TTL against replay attacks (REQ-TEL-002)."""

    def __init__(
        self,
        store: EphemeralStore,
        ttl_seconds: float = 60.0,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self._store: EphemeralStore = store
        self.ttl_seconds: float = float(ttl_seconds)
        self._time_provider: Callable[[], float] = (
            time_provider if time_provider is not None else time.monotonic
        )

    def create_nonce(
        self,
        action: AdminCommand,
        user_id: int,
        payload: dict[str, Any] | None = None,
    ) -> CallbackNonce:
        """Generate a single-use cryptographically random nonce with 60s TTL."""
        token = secrets.token_urlsafe(16)
        now = self._time_provider()
        expires_at = now + self.ttl_seconds
        callback_nonce = CallbackNonce(
            nonce=token,
            action=action,
            user_id=user_id,
            created_at_mono=now,
            expires_at_mono=expires_at,
            payload=payload if payload is not None else {},
        )
        self._store.set(f"nonce:{token}", callback_nonce, ttl_seconds=self.ttl_seconds)
        return callback_nonce

    def consume_nonce(self, nonce: str, user_id: int) -> CallbackNonce | None:
        """Validate and immediately consume a nonce. Returns None if invalid or expired."""
        key = f"nonce:{nonce}"
        stored = self._store.get(key)
        if stored is None or not isinstance(stored, CallbackNonce):
            return None

        # Single-use mandate: immediately purge from store (anti-replay)
        self._store.delete(key)

        now = self._time_provider()
        if stored.user_id != user_id:
            return None
        if stored.is_expired(now):
            return None

        return stored


class TelegramTwoStepController:
    """Manages 15s two-step confirmations for destructive bot commands (REQ-TEL-003)."""

    def __init__(
        self,
        store: EphemeralStore,
        ttl_seconds: float = 15.0,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self._store: EphemeralStore = store
        self.ttl_seconds: float = float(ttl_seconds)
        self._time_provider: Callable[[], float] = (
            time_provider if time_provider is not None else time.monotonic
        )

    def initiate(self, action: AdminCommand, user_id: int) -> TwoStepAction:
        """Initiate a confirmation cycle (TTL: 15s) for a destructive command."""
        token = secrets.token_urlsafe(16)
        now = self._time_provider()
        expires_at = now + self.ttl_seconds
        action_record = TwoStepAction(
            action=action,
            nonce=token,
            user_id=user_id,
            created_at_mono=now,
            expires_at_mono=expires_at,
            state=TwoStepState.PENDING_CONFIRMATION,
        )
        self._store.set(f"twostep:{token}", action_record, ttl_seconds=self.ttl_seconds)
        return action_record

    def confirm(self, nonce: str, user_id: int) -> TwoStepAction:
        """Confirm and transition a pending two-step action."""
        key = f"twostep:{nonce}"
        stored = self._store.get(key)
        now = self._time_provider()

        if stored is None or not isinstance(stored, TwoStepAction):
            return TwoStepAction(
                action=AdminCommand.KILLSWITCH,
                nonce=nonce,
                user_id=user_id,
                created_at_mono=now,
                expires_at_mono=now,
                state=TwoStepState.EXPIRED,
            )

        # Single-use: remove from store immediately upon transition
        self._store.delete(key)

        if stored.user_id != user_id or stored.is_expired(now):
            return TwoStepAction(
                action=stored.action,
                nonce=nonce,
                user_id=user_id,
                created_at_mono=stored.created_at_mono,
                expires_at_mono=stored.expires_at_mono,
                state=TwoStepState.EXPIRED,
            )

        return TwoStepAction(
            action=stored.action,
            nonce=nonce,
            user_id=user_id,
            created_at_mono=stored.created_at_mono,
            expires_at_mono=stored.expires_at_mono,
            state=TwoStepState.CONFIRMED,
        )

    def cancel(self, nonce: str, user_id: int) -> TwoStepAction:
        """Cancel a pending two-step confirmation."""
        key = f"twostep:{nonce}"
        stored = self._store.get(key)
        now = self._time_provider()

        if stored is None or not isinstance(stored, TwoStepAction):
            return TwoStepAction(
                action=AdminCommand.KILLSWITCH,
                nonce=nonce,
                user_id=user_id,
                created_at_mono=now,
                expires_at_mono=now,
                state=TwoStepState.CANCELLED,
            )

        self._store.delete(key)
        return TwoStepAction(
            action=stored.action,
            nonce=nonce,
            user_id=user_id,
            created_at_mono=stored.created_at_mono,
            expires_at_mono=stored.expires_at_mono,
            state=TwoStepState.CANCELLED,
        )


__all__ = [
    "AdminAuthenticator",
    "EphemeralStore",
    "InMemoryEphemeralStore",
    "NonceManager",
    "TelegramAdminAuthenticator",
    "TelegramNonceManager",
    "TelegramTwoStepController",
    "TwoStepController",
]
