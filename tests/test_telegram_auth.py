"""Unit tests for Telegram admin authentication, nonce manager, and two-step confirmation.

Module: tests.test_telegram_auth
Covers: REQ-TEL-001, REQ-TEL-002, REQ-TEL-003
Verification: Tests determinism, rate limiting, single-use anti-replay, 60s/15s TTLs,
memory leak sweep, and protocol compliance.
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

import concurrent.futures

from engine.telegram_bot.auth import (
    InMemoryEphemeralStore,
    TelegramAdminAuthenticator,
    TelegramNonceManager,
    TelegramTwoStepController,
)
from engine.telegram_bot.interfaces import (
    AdminAuthenticator,
    EphemeralStore,
    NonceManager,
    TwoStepController,
)
from engine.telegram_bot.types import (
    AdminCommand,
    TwoStepState,
)


class MockMonotonicClock:
    """Deterministic monotonic clock provider for test environments."""

    def __init__(self, start_time: float = 1000.0) -> None:
        self.current_time = start_time

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += seconds


def test_protocol_compliance() -> None:
    """Verify classes satisfy runtime checkable Protocols via structural subtyping."""
    store = InMemoryEphemeralStore()
    auth = TelegramAdminAuthenticator(admin_id=123456789)
    nonce_mgr = TelegramNonceManager(store=store)
    controller = TelegramTwoStepController(store=store)

    assert isinstance(store, EphemeralStore)
    assert isinstance(auth, AdminAuthenticator)
    assert isinstance(nonce_mgr, NonceManager)
    assert isinstance(controller, TwoStepController)


def test_admin_whitelist_silent_drop() -> None:
    """REQ-TEL-001: Non-admin users are rejected with UNAUTHORIZED_USER_SILENT_DROP."""
    admin_id = 123456789
    auth = TelegramAdminAuthenticator(admin_id=admin_id)

    # Unauthorized attempts
    res_stranger = auth.authenticate(user_id=987654321)
    assert res_stranger.allowed is False
    assert res_stranger.user_id == 987654321
    assert res_stranger.reason == "UNAUTHORIZED_USER_SILENT_DROP"

    res_zero = auth.authenticate(user_id=0)
    assert res_zero.allowed is False
    assert res_zero.reason == "UNAUTHORIZED_USER_SILENT_DROP"

    # Authorized admin
    res_admin = auth.authenticate(user_id=admin_id)
    assert res_admin.allowed is True
    assert res_admin.user_id == admin_id
    assert res_admin.reason == "OK"


def test_admin_rate_limiting() -> None:
    """REQ-TEL-001: Two consecutive admin requests within < 1.0s trigger RATE_LIMIT_EXCEEDED."""
    clock = MockMonotonicClock(start_time=100.0)
    admin_id = 123456789
    auth = TelegramAdminAuthenticator(
        admin_id=admin_id,
        rate_limit_per_second=1.0,
        time_provider=clock,
    )

    # First request succeeds
    r1 = auth.authenticate(user_id=admin_id)
    assert r1.allowed is True
    assert r1.reason == "OK"

    # Second request immediately (elapsed = 0.0s < 1.0s) is blocked
    r2 = auth.authenticate(user_id=admin_id)
    assert r2.allowed is False
    assert r2.reason == "RATE_LIMIT_EXCEEDED"

    # Advance clock by 0.5s (elapsed = 0.5s < 1.0s) is still blocked
    clock.advance(0.5)
    r3 = auth.authenticate(user_id=admin_id)
    assert r3.allowed is False
    assert r3.reason == "RATE_LIMIT_EXCEEDED"

    # Advance clock by another 0.6s (total elapsed = 1.1s >= 1.0s) succeeds
    clock.advance(0.6)
    r4 = auth.authenticate(user_id=admin_id)
    assert r4.allowed is True
    assert r4.reason == "OK"


def test_nonce_lifecycle_and_single_use() -> None:
    """REQ-TEL-002: Nonce is valid on first consumption and returns None on subsequent attempt (anti-replay)."""
    clock = MockMonotonicClock(start_time=500.0)
    store = InMemoryEphemeralStore(time_provider=clock)
    manager = TelegramNonceManager(store=store, ttl_seconds=60.0, time_provider=clock)
    user_id = 123456789

    nonce_record = manager.create_nonce(
        action=AdminCommand.FORCE_CLOSE_ALL,
        user_id=user_id,
        payload={"ticket": 1001},
    )

    assert nonce_record.user_id == user_id
    assert nonce_record.action == AdminCommand.FORCE_CLOSE_ALL
    assert nonce_record.payload == {"ticket": 1001}
    assert nonce_record.created_at_mono == 500.0
    assert nonce_record.expires_at_mono == 560.0

    # First consumption: succeeds
    consumed = manager.consume_nonce(nonce=nonce_record.nonce, user_id=user_id)
    assert consumed is not None
    assert consumed.nonce == nonce_record.nonce
    assert consumed.action == AdminCommand.FORCE_CLOSE_ALL
    assert consumed.payload == {"ticket": 1001}

    # Second consumption: single-use mandate immediately returns None (replay prevented)
    replay = manager.consume_nonce(nonce=nonce_record.nonce, user_id=user_id)
    assert replay is None


def test_nonce_expired_after_60s() -> None:
    """REQ-TEL-002: Nonce consumed after exactly 60s TTL has passed returns None."""
    clock = MockMonotonicClock(start_time=100.0)
    store = InMemoryEphemeralStore(time_provider=clock)
    manager = TelegramNonceManager(store=store, ttl_seconds=60.0, time_provider=clock)
    user_id = 123456789

    nonce_record = manager.create_nonce(action=AdminCommand.KILLSWITCH, user_id=user_id)

    # Advance clock beyond 60s window (60.1 seconds)
    clock.advance(60.1)

    # Attempt to consume expired nonce
    consumed = manager.consume_nonce(nonce=nonce_record.nonce, user_id=user_id)
    assert consumed is None


def test_nonce_user_mismatch() -> None:
    """REQ-TEL-002: Consuming nonce with incorrect user_id returns None."""
    clock = MockMonotonicClock(start_time=100.0)
    store = InMemoryEphemeralStore(time_provider=clock)
    manager = TelegramNonceManager(store=store, ttl_seconds=60.0, time_provider=clock)

    nonce_record = manager.create_nonce(action=AdminCommand.PAUSE, user_id=123456789)

    # Attacker tries to consume nonce
    attacker_attempt = manager.consume_nonce(
        nonce=nonce_record.nonce, user_id=999999999
    )
    assert attacker_attempt is None

    # Original nonce was burned by single-use mandate upon consumption attempt
    admin_attempt = manager.consume_nonce(nonce=nonce_record.nonce, user_id=123456789)
    assert admin_attempt is None


def test_two_step_confirmation_success() -> None:
    """REQ-TEL-003: Initiation and confirmation within 15.0s window transitions to CONFIRMED."""
    clock = MockMonotonicClock(start_time=200.0)
    store = InMemoryEphemeralStore(time_provider=clock)
    controller = TelegramTwoStepController(
        store=store, ttl_seconds=15.0, time_provider=clock
    )
    user_id = 123456789

    action = controller.initiate(action=AdminCommand.KILLSWITCH, user_id=user_id)
    assert action.state == TwoStepState.PENDING_CONFIRMATION
    assert action.action == AdminCommand.KILLSWITCH
    assert action.user_id == user_id
    assert action.created_at_mono == 200.0
    assert action.expires_at_mono == 215.0

    # Advance clock by 5s (well within 15s window)
    clock.advance(5.0)

    confirmed = controller.confirm(nonce=action.nonce, user_id=user_id)
    assert confirmed.state == TwoStepState.CONFIRMED
    assert confirmed.action == AdminCommand.KILLSWITCH
    assert confirmed.user_id == user_id

    # Secondary confirmation attempt returns EXPIRED (already consumed)
    second_confirm = controller.confirm(nonce=action.nonce, user_id=user_id)
    assert second_confirm.state == TwoStepState.EXPIRED


def test_two_step_confirmation_timeout_15s() -> None:
    """REQ-TEL-003: Initiation and confirmation after > 15.0s transitions to EXPIRED."""
    clock = MockMonotonicClock(start_time=300.0)
    store = InMemoryEphemeralStore(time_provider=clock)
    controller = TelegramTwoStepController(
        store=store, ttl_seconds=15.0, time_provider=clock
    )
    user_id = 123456789

    action = controller.initiate(action=AdminCommand.FORCE_CLOSE_ALL, user_id=user_id)
    assert action.state == TwoStepState.PENDING_CONFIRMATION

    # Advance clock past 15s threshold (15.1 seconds)
    clock.advance(15.1)

    result = controller.confirm(nonce=action.nonce, user_id=user_id)
    assert result.state == TwoStepState.EXPIRED


def test_two_step_cancellation() -> None:
    """REQ-TEL-003: Initiation followed by explicit cancel transitions to CANCELLED."""
    clock = MockMonotonicClock(start_time=400.0)
    store = InMemoryEphemeralStore(time_provider=clock)
    controller = TelegramTwoStepController(
        store=store, ttl_seconds=15.0, time_provider=clock
    )
    user_id = 123456789

    action = controller.initiate(action=AdminCommand.PAUSE, user_id=user_id)
    assert action.state == TwoStepState.PENDING_CONFIRMATION

    cancelled = controller.cancel(nonce=action.nonce, user_id=user_id)
    assert cancelled.state == TwoStepState.CANCELLED
    assert cancelled.action == AdminCommand.PAUSE
    assert cancelled.user_id == user_id

    # Confirming a cancelled action fails with EXPIRED
    confirm_attempt = controller.confirm(nonce=action.nonce, user_id=user_id)
    assert confirm_attempt.state == TwoStepState.EXPIRED


def test_ephemeral_store_sweep_expired() -> None:
    """Zero Memory Leak: sweep_expired() purges all expired keys from in-memory cache."""
    clock = MockMonotonicClock(start_time=1000.0)
    store = InMemoryEphemeralStore(time_provider=clock)

    # Insert 50 entries that expire in 10 seconds
    for i in range(50):
        store.set(key=f"nonce_{i}", value=f"payload_{i}", ttl_seconds=10.0)

    # Insert 10 entries that expire in 100 seconds
    for i in range(10):
        store.set(key=f"active_{i}", value=f"active_payload_{i}", ttl_seconds=100.0)

    # Advance clock by 15 seconds -> 50 entries expire
    clock.advance(15.0)

    purged_count = store.sweep_expired()
    assert purged_count == 50

    # Verify active entries remain accessible
    for i in range(10):
        assert store.get(f"active_{i}") == f"active_payload_{i}"

    # Verify expired entries are gone
    for i in range(50):
        assert store.get(f"nonce_{i}") is None

    # Advance clock by another 100 seconds -> remaining 10 entries expire
    clock.advance(100.0)
    second_purge = store.sweep_expired()
    assert second_purge == 10

    # Third sweep on clean store returns 0
    assert store.sweep_expired() == 0


def test_ephemeral_store_crud_and_delete() -> None:
    """Validate CRUD operations on InMemoryEphemeralStore."""
    store = InMemoryEphemeralStore()

    assert store.get("non_existent") is None
    deleted_missing = store.delete("non_existent")
    assert deleted_missing is False

    store.set("test_key", {"data": 42}, ttl_seconds=30.0)
    assert store.get("test_key") == {"data": 42}

    deleted_existing = store.delete("test_key")
    assert deleted_existing is True
    assert store.get("test_key") is None
    deleted_again = store.delete("test_key")
    assert deleted_again is False


def test_ephemeral_store_concurrency() -> None:
    """Stress test InMemoryEphemeralStore thread-safety with concurrent readers and writers."""
    store = InMemoryEphemeralStore()
    num_threads = 10
    ops_per_thread = 50

    def worker(thread_idx: int) -> None:
        for i in range(ops_per_thread):
            key = f"key_{thread_idx}_{i}"
            store.set(key, {"idx": thread_idx, "i": i}, ttl_seconds=5.0)
            val = store.get(key)
            assert val is not None
            store.delete(key)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, t) for t in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert store.sweep_expired() == 0
