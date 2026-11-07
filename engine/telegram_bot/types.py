"""Data types and immutable models for Telegram bot control and authorization.

Module: engine.telegram_bot.types
Responsibility: Defines immutable data structures for admin authentication,
ephemeral action nonces (60s TTL), two-step confirmation state machines (15s TTL),
and emergency closure results.
Owner: aeterna-execution
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AdminCommand(str, Enum):
    """Supported Telegram bot control commands and inline keyboard actions."""

    STATUS = "STATUS"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    FORCE_CLOSE_ALL = "FORCE_CLOSE_ALL"
    KILLSWITCH = "KILLSWITCH"
    DAILY_REPORT = "DAILY_REPORT"


class TwoStepState(str, Enum):
    """Lifecycle states of a two-step confirmation cycle for destructive commands."""

    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class AuthResult:
    """Outcome of an incoming Telegram user/admin authentication evaluation."""

    allowed: bool
    user_id: int
    reason: str  # e.g., "OK", "UNAUTHORIZED_USER_SILENT_DROP", "RATE_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class CallbackNonce:
    """Ephemeral single-use nonce protecting inline buttons against replay attacks.

    Enforces REQ-TEL-002:
    - Time-to-Live (TTL) is strictly 60.0 seconds from generation.
    - Consumed and invalidated immediately upon first execution attempt.
    """

    nonce: str
    action: AdminCommand
    user_id: int
    created_at_mono: float
    expires_at_mono: float  # monotonic timestamp deadline (now + 60.0s)
    payload: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, current_mono: float) -> bool:
        """Evaluate if the nonce has exceeded its 60-second validity window."""
        return current_mono >= self.expires_at_mono


@dataclass(frozen=True)
class TwoStepAction:
    """Two-step confirmation state record for destructive operations.

    Enforces REQ-TEL-003:
    - Destructive actions (Emergency Stop, Force Close All) require explicit secondary confirmation.
    - Confirmation window expires after exactly 15.0 seconds.
    """

    action: AdminCommand
    nonce: str
    user_id: int
    created_at_mono: float
    expires_at_mono: float  # monotonic timestamp deadline (now + 15.0s)
    state: TwoStepState

    def is_expired(self, current_mono: float) -> bool:
        """Evaluate if the confirmation window has expired."""
        return current_mono >= self.expires_at_mono


@dataclass(frozen=True)
class EmergencyCloseResult:
    """Outcome of an emergency position force-close operation."""

    ticket: int
    success: bool
    closed_lot: float
    executed_price: float | None = None
    slippage_points: float = 0.0
    error_message: str | None = None
