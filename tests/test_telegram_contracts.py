"""Unit tests and characterization tests for Milestone 6 Contract-First API Lock.

Validates:
1. Immutability of Admin types: CallbackNonce, TwoStepAction, AuthResult, EmergencyCloseResult.
2. Immutability of DailyMetrics.
3. Expiration logic on CallbackNonce (60s TTL) and TwoStepAction (15s TTL).
4. Interface compliance and Protocol structural subtyping for EphemeralStore, AdminAuthenticator,
   NonceManager, TwoStepController, DailyMetricsCollector, and ExecutionEmergencyHandler.
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from engine.monitoring.types import DailyMetrics
from engine.telegram_bot.interfaces import (
    AdminAuthenticator,
    DailyMetricsCollector,
    EphemeralStore,
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


def test_callback_nonce_immutability_and_expiration() -> None:
    """Verify CallbackNonce is frozen and correctly evaluates its 60-second TTL."""
    nonce = CallbackNonce(
        nonce="abc-123-nonce",
        action=AdminCommand.FORCE_CLOSE_ALL,
        user_id=123456789,
        created_at_mono=100.0,
        expires_at_mono=160.0,  # 60 seconds TTL
        payload={"reason": "emergency"},
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        nonce.nonce = "tampered"  # type: ignore[misc]

    # Expiration evaluation
    assert not nonce.is_expired(current_mono=100.0)
    assert not nonce.is_expired(current_mono=159.9)
    assert nonce.is_expired(current_mono=160.0)
    assert nonce.is_expired(current_mono=165.0)


def test_two_step_action_immutability_and_expiration() -> None:
    """Verify TwoStepAction is frozen and correctly evaluates its 15-second TTL."""
    action = TwoStepAction(
        action=AdminCommand.KILLSWITCH,
        nonce="kill-999-nonce",
        user_id=123456789,
        created_at_mono=200.0,
        expires_at_mono=215.0,  # 15 seconds TTL
        state=TwoStepState.PENDING_CONFIRMATION,
    )

    # Immutability
    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        action.state = TwoStepState.CONFIRMED  # type: ignore[misc]

    # Expiration evaluation
    assert not action.is_expired(current_mono=200.0)
    assert not action.is_expired(current_mono=214.9)
    assert action.is_expired(current_mono=215.0)
    assert action.is_expired(current_mono=220.0)


def test_auth_result_and_emergency_close_result() -> None:
    """Verify AuthResult and EmergencyCloseResult immutable field attributes."""
    auth = AuthResult(allowed=True, user_id=123456789, reason="OK")
    assert auth.allowed is True
    assert auth.user_id == 123456789
    assert auth.reason == "OK"

    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        auth.allowed = False  # type: ignore[misc]

    res = EmergencyCloseResult(
        ticket=1001,
        success=True,
        closed_lot=0.05,
        executed_price=2750.50,
        slippage_points=5.0,
    )
    assert res.ticket == 1001
    assert res.success is True
    assert res.closed_lot == 0.05
    assert res.executed_price == 2750.50

    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        res.success = False  # type: ignore[misc]


def test_daily_metrics_immutability() -> None:
    """Verify DailyMetrics data model attributes and immutability."""
    metrics = DailyMetrics(
        date_utc="2026-11-06",
        total_trades=10,
        win_trades=7,
        loss_trades=3,
        win_rate_pct=70.0,
        gross_profit_usd=350.0,
        gross_loss_usd=150.0,
        net_pnl_usd=200.0,
        profit_factor=2.33,
        max_drawdown_usd=50.0,
        max_drawdown_pct=0.5,
        paused_duration_seconds=1200.0,
        active_positions_count=0,
        current_account_equity=10200.0,
        myfxbook_url="https://myfxbook.com/members/aeterna/12345",
    )

    assert metrics.net_pnl_usd == 200.0
    assert metrics.win_rate_pct == 70.0
    assert metrics.myfxbook_url is not None

    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        metrics.total_trades = 11  # type: ignore[misc]


def test_protocol_structural_subtyping() -> None:
    """Verify custom classes satisfy the Protocol definitions via structural typing."""

    class MockEphemeralStore:
        def set(self, key: str, value: Any, ttl_seconds: float) -> None:
            pass

        def get(self, key: str) -> Any | None:
            return None

        def delete(self, key: str) -> bool:
            return True

        def sweep_expired(self) -> int:
            return 0

    class MockAdminAuthenticator:
        def authenticate(self, user_id: int) -> AuthResult:
            return AuthResult(allowed=True, user_id=user_id, reason="OK")

    class MockNonceManager:
        def create_nonce(
            self, action: AdminCommand, user_id: int, payload: dict[str, Any] | None = None
        ) -> CallbackNonce:
            return CallbackNonce(
                nonce="dummy",
                action=action,
                user_id=user_id,
                created_at_mono=0.0,
                expires_at_mono=60.0,
            )

        def consume_nonce(self, nonce: str, user_id: int) -> CallbackNonce | None:
            return None

    class MockTwoStepController:
        def initiate(self, action: AdminCommand, user_id: int) -> TwoStepAction:
            return TwoStepAction(
                action=action,
                nonce="n1",
                user_id=user_id,
                created_at_mono=0.0,
                expires_at_mono=15.0,
                state=TwoStepState.PENDING_CONFIRMATION,
            )

        def confirm(self, nonce: str, user_id: int) -> TwoStepAction:
            return TwoStepAction(
                action=AdminCommand.KILLSWITCH,
                nonce=nonce,
                user_id=user_id,
                created_at_mono=0.0,
                expires_at_mono=15.0,
                state=TwoStepState.CONFIRMED,
            )

        def cancel(self, nonce: str, user_id: int) -> TwoStepAction:
            return TwoStepAction(
                action=AdminCommand.KILLSWITCH,
                nonce=nonce,
                user_id=user_id,
                created_at_mono=0.0,
                expires_at_mono=15.0,
                state=TwoStepState.CANCELLED,
            )

    class MockDailyMetricsCollector:
        def collect_daily_metrics(self, target_date: str | None = None) -> DailyMetrics:
            return DailyMetrics(
                date_utc="2026-11-06",
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
                current_account_equity=10000.0,
            )

    class MockExecutionEmergencyHandler:
        def execute_force_close_all(
            self, max_deviation_pts: int = 50
        ) -> list[EmergencyCloseResult]:
            return []

        def execute_emergency_killswitch(self) -> bool:
            return True

        def set_system_state_paused(self) -> bool:
            return True

        def set_system_state_normal(self) -> bool:
            return True

    # Assert structural type conformance with runtime check
    assert isinstance(MockEphemeralStore(), EphemeralStore)
    assert isinstance(MockAdminAuthenticator(), AdminAuthenticator)
    assert isinstance(MockNonceManager(), NonceManager)
    assert isinstance(MockTwoStepController(), TwoStepController)
    assert isinstance(MockDailyMetricsCollector(), DailyMetricsCollector)
    assert isinstance(MockExecutionEmergencyHandler(), ExecutionEmergencyHandler)
