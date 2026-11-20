"""Unit tests for RuntimeService and SignalOnlyDashboard.

Module: tests.runtime.test_runtime_service
Responsibility: Validates admin-only boundary, purity filter, lifecycle orchestration,
                and observation deduplication (REQ-RUNTIME-005, REQ-TEL-001, REQ-TEL-004, REQ-EXE-004).
Owner: aeterna-verifier
Tier: Tier A
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from engine.models import SignalObservationRecord
from engine.runtime.dashboard import (
    ObservationCard,
    SignalOnlyDashboard,
    format_observation_card,
)
from engine.runtime.runtime_service import RuntimeService


def _create_sample_card(
    regime_bias: str = "BULLISH_TREND",
    symbol: str = "XAUUSDm",
    data_tag: str = "internal_virtual_journal",
) -> ObservationCard:
    """Helper to construct a valid ObservationCard."""
    return ObservationCard(
        timestamp_utc="2026-11-18 08:00:00 UTC",
        symbol=symbol,
        regime_bias=regime_bias,
        zone_low=2750.0,
        zone_high=2752.0,
        invalidation_level=2745.0,
        liquidity_state="NORMAL",
        blackout_window=None,
        sample_count=1,
        data_tag=data_tag,
    )


def test_dashboard_rejects_non_admin_chat_id() -> None:
    """Non-whitelisted or mismatching chat ID must be silently dropped without sending."""
    mock_client = MagicMock()
    mock_client.send.return_value = True

    admin_chat_id = 123456789
    dashboard = SignalOnlyDashboard(client=mock_client, admin_chat_id=admin_chat_id)

    card = _create_sample_card()

    # 1. Publish to an unauthorized chat ID
    unauthorized_chat_id = 987654321
    result = dashboard.publish(card, chat_id=unauthorized_chat_id)
    assert result is False
    mock_client.send.assert_not_called()

    # 2. Publish to the authorized admin chat ID
    result_admin = dashboard.publish(card, chat_id=admin_chat_id)
    assert result_admin is True
    assert mock_client.send.call_count == 1
    call_payload = mock_client.send.call_args[0][0]
    assert call_payload["chat_id"] == admin_chat_id
    assert call_payload["method"] == "sendMessage"


@pytest.mark.parametrize(
    "forbidden_token",
    [
        "BUY sekarang",
        "SELL sekarang",
        "buy now",
        "sell now",
        "0.01 lot",
        "lots",
        "equity",
        "balance",
        "ticket",
        "server",
        "profit",
        "win rate: 80%",
        "garansi",
        "pastikan untung",
    ],
)
def test_observation_card_rejects_trading_instruction_tokens(
    forbidden_token: str,
) -> None:
    """Formatter must strictly raise ValueError when trading/performance tokens appear."""
    card = _create_sample_card(regime_bias=f"INVALID_{forbidden_token}")
    with pytest.raises(ValueError):
        format_observation_card(card)


def test_observation_card_contains_all_required_labels() -> None:
    """Observation card text must contain all mandatory structural labels and no legacy header."""
    card = _create_sample_card()
    text = format_observation_card(card)

    required_labels = (
        "OBSERVATION",
        "BIAS",
        "ZONA",
        "INVALIDASI",
        "LIQUIDITY",
        "BLACKOUT",
        "SAMPLE",
        "DATA_TAG",
    )
    for label in required_labels:
        assert label in text, (
            f"Mandatory label '{label}' missing from observation text."
        )

    assert "SIGNAL — XAUUSD" not in text
    assert "Not financial advice" in text


@pytest.mark.asyncio
async def test_runtime_service_starts_and_stops_all_tasks() -> None:
    """RuntimeService must start all loops and cancel/stop gracefully on stop_event."""
    loop_a_mock = MagicMock()
    loop_b_mock = MagicMock()
    tracker_mock = MagicMock()
    dashboard_mock = MagicMock()
    db_mock = MagicMock()

    loop_a_started = asyncio.Event()
    loop_b_started = asyncio.Event()
    tracker_started = asyncio.Event()

    async def fake_loop_a(stop_event: asyncio.Event) -> None:
        loop_a_started.set()
        await stop_event.wait()

    async def fake_loop_b(m15_event: asyncio.Event, stop_event: asyncio.Event) -> None:
        loop_b_started.set()
        await stop_event.wait()

    async def fake_tracker(stop_event: asyncio.Event) -> None:
        tracker_started.set()
        await stop_event.wait()

    loop_a_mock.run_forever.side_effect = fake_loop_a
    loop_b_mock.run_forever.side_effect = fake_loop_b
    tracker_mock.run_forever.side_effect = fake_tracker
    db_mock.get_open_signal_observations.return_value = []

    service = RuntimeService(
        loop_a=loop_a_mock,
        loop_b=loop_b_mock,
        virtual_tracker=tracker_mock,
        dashboard=dashboard_mock,
        db_manager=db_mock,
        symbol="XAUUSDm",
        publish_interval_seconds=0.05,
    )

    stop_event = asyncio.Event()
    service_task = asyncio.create_task(service.run_forever(stop_event))

    # Wait until all sub-tasks signal that they started
    await asyncio.wait_for(
        asyncio.gather(
            loop_a_started.wait(),
            loop_b_started.wait(),
            tracker_started.wait(),
        ),
        timeout=1.0,
    )

    # Trigger stop event
    await asyncio.sleep(0.05)
    stop_event.set()

    # Task should finish cleanly without error
    await asyncio.wait_for(service_task, timeout=1.0)
    assert service_task.done()
    assert not service_task.cancelled()


@pytest.mark.asyncio
async def test_publish_once_per_signal_id() -> None:
    """Observations must be deduplicated in-memory so identical signal_id is published only once."""
    mock_client = MagicMock()
    mock_client.send.return_value = True

    dashboard = SignalOnlyDashboard(client=mock_client, admin_chat_id=123456789)
    db_mock = MagicMock()

    record = SignalObservationRecord(
        signal_id="sig_test_001",
        symbol="XAUUSDm",
        bar_ts=1700000000,
        strategy_id="strat_v1",
        order_type="BUY",
        state="OPEN",
        entry_px=2750.0,
        sl_px=2745.0,
        tp_px=2760.0,
        lot_virtual=0.01,
        partial_skipped_min_lot=0,
        r_realized_net=0.0,
        exit_reason=None,
    )
    db_mock.get_open_signal_observations.return_value = [record]

    service = RuntimeService(
        loop_a=MagicMock(),
        loop_b=MagicMock(),
        virtual_tracker=MagicMock(),
        dashboard=dashboard,
        db_manager=db_mock,
        symbol="XAUUSDm",
        publish_interval_seconds=0.1,
    )

    # First poll: should publish the record
    await service._poll_and_publish_once()
    assert mock_client.send.call_count == 1
    assert "sig_test_001" in service._published_signal_ids

    # Second poll: record is still in DB, but must be skipped due to deduplication
    await service._poll_and_publish_once()
    assert mock_client.send.call_count == 1


def test_publish_with_chart_rejects_non_admin_chat_id() -> None:
    """publish_with_chart must silently reject any non-whitelisted/mismatching chat ID."""
    mock_client = MagicMock()
    mock_client.send_photo.return_value = True

    admin_chat_id = 123456789
    dashboard = SignalOnlyDashboard(client=mock_client, admin_chat_id=admin_chat_id)
    card = _create_sample_card()
    dummy_photo = b"\x89PNG\r\n\x1a\nfake_image_bytes"

    # 1. Non-admin chat ID rejected
    unauthorized_chat_id = 987654321
    result = dashboard.publish_with_chart(
        card, photo=dummy_photo, chat_id=unauthorized_chat_id
    )
    assert result is False
    mock_client.send_photo.assert_not_called()

    # 2. Authorized admin chat ID accepted
    result_admin = dashboard.publish_with_chart(
        card, photo=dummy_photo, chat_id=admin_chat_id
    )
    assert result_admin is True
    mock_client.send_photo.assert_called_once()
    called_chat_id, called_photo, called_caption = mock_client.send_photo.call_args[0]
    assert called_chat_id == admin_chat_id
    assert called_photo == dummy_photo
    assert "OBSERVATION" in called_caption


def test_publish_with_chart_default_admin_chat_id() -> None:
    """publish_with_chart with chat_id=None must deliver to default admin_chat_id."""
    mock_client = MagicMock()
    mock_client.send_photo.return_value = True

    admin_chat_id = 123456789
    dashboard = SignalOnlyDashboard(client=mock_client, admin_chat_id=admin_chat_id)
    card = _create_sample_card()
    dummy_photo = b"png_data"

    result = dashboard.publish_with_chart(card, photo=dummy_photo)
    assert result is True
    mock_client.send_photo.assert_called_once()
    called_chat_id, called_photo, called_caption = mock_client.send_photo.call_args[0]
    assert called_chat_id == admin_chat_id
    assert called_photo == dummy_photo
    assert "OBSERVATION" in called_caption
    assert "REASONING" in called_caption


def test_publish_with_chart_caption_contains_reasoning_and_card_details() -> None:
    """publish_with_chart caption must format ObservationCard + deterministic reasoning."""
    mock_client = MagicMock()
    mock_client.send_photo.return_value = True

    admin_chat_id = 123456789
    dashboard = SignalOnlyDashboard(
        client=mock_client,
        admin_chat_id=admin_chat_id,
        reasoning_enabled=True,
    )
    card = _create_sample_card(regime_bias="BULLISH_TREND")
    dummy_photo = b"png_payload"

    result = dashboard.publish_with_chart(card, photo=dummy_photo)
    assert result is True
    assert mock_client.send_photo.call_count == 1
    _, _, caption = mock_client.send_photo.call_args[0]

    # Required card structural labels
    for label in (
        "OBSERVATION",
        "BIAS",
        "ZONA",
        "INVALIDASI",
        "LIQUIDITY",
        "REASONING",
    ):
        assert label in caption

    # Deterministic reasoning elements
    assert "REGIME=" in caption
    assert "STRATEGY=" in caption
    assert "RR=" in caption
    assert "STATE=" in caption
    assert "NEWS=" in caption
    assert "SPREAD_Z=" in caption


@pytest.mark.parametrize(
    "forbidden_token",
    [
        "BUY sekarang",
        "SELL sekarang",
        "buy now",
        "sell now",
        "0.01 lot",
        "lots",
        "equity",
        "balance",
        "ticket",
        "server",
        "profit",
        "win rate: 80%",
        "garansi",
        "pastikan untung",
    ],
)
def test_publish_with_chart_rejects_forbidden_tokens(forbidden_token: str) -> None:
    """publish_with_chart must raise ValueError and drop publish when card has forbidden tokens."""
    mock_client = MagicMock()
    dashboard = SignalOnlyDashboard(client=mock_client, admin_chat_id=123456789)
    card = _create_sample_card(regime_bias=f"BIAS_{forbidden_token}")
    dummy_photo = b"png_bytes"

    with pytest.raises(ValueError):
        dashboard.publish_with_chart(card, photo=dummy_photo)
    mock_client.send_photo.assert_not_called()


def test_publish_with_chart_transport_error_does_not_crash() -> None:
    """publish_with_chart must catch transport errors and return False gracefully."""
    mock_client = MagicMock()
    mock_client.send_photo.side_effect = ConnectionError("Telegram network timeout")

    dashboard = SignalOnlyDashboard(client=mock_client, admin_chat_id=123456789)
    card = _create_sample_card()
    dummy_photo = b"png_bytes"

    result = dashboard.publish_with_chart(card, photo=dummy_photo)
    assert result is False
    mock_client.send_photo.assert_called_once()


def test_telegram_control_bot_send_photo_admin_only() -> None:
    """TelegramControlBot.send_photo must reject non-admin and send multipart to admin."""
    from engine.telegram_bot.client import TelegramControlBot
    from engine.telegram_bot.interfaces import (
        AdminAuthenticator,
        NonceManager,
        TwoStepController,
    )
    from engine.telegram_bot.types import AuthResult

    admin_id = 123456789
    authenticator = MagicMock(spec=AdminAuthenticator)

    def _auth(user_id: int) -> AuthResult:
        if user_id == admin_id:
            return AuthResult(allowed=True, user_id=user_id, reason="OK")
        return AuthResult(
            allowed=False, user_id=user_id, reason="UNAUTHORIZED_USER_SILENT_DROP"
        )

    authenticator.authenticate.side_effect = _auth

    session_mock = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 999}}
    session_mock.post.return_value = mock_response

    bot = TelegramControlBot(
        token="test-bot-token",
        authenticator=authenticator,
        nonce_manager=MagicMock(spec=NonceManager),
        two_step=MagicMock(spec=TwoStepController),
        session=session_mock,
    )

    photo_bytes = b"\x89PNG\r\n\x1a\nfake_image"
    caption_text = "Test observation caption"

    # 1. Non-admin chat ID is rejected before any HTTP call
    assert (
        bot.send_photo(chat_id=987654321, photo=photo_bytes, caption=caption_text)
        is False
    )
    session_mock.post.assert_not_called()

    # 2. Admin chat ID sends multipart POST
    assert (
        bot.send_photo(chat_id=admin_id, photo=photo_bytes, caption=caption_text)
        is True
    )
    assert session_mock.post.call_count == 1
    call_args = session_mock.post.call_args
    assert "sendPhoto" in call_args[0][0]
    assert call_args[1]["data"]["chat_id"] == str(admin_id)
    assert call_args[1]["data"]["caption"] == caption_text
    assert "photo" in call_args[1]["files"]


def test_telegram_control_bot_send_photo_transport_error() -> None:
    """TelegramControlBot.send_photo must return False on HTTP / transport error without crashing."""
    import requests

    from engine.telegram_bot.client import TelegramControlBot
    from engine.telegram_bot.interfaces import (
        AdminAuthenticator,
        NonceManager,
        TwoStepController,
    )
    from engine.telegram_bot.types import AuthResult

    admin_id = 123456789
    authenticator = MagicMock(spec=AdminAuthenticator)
    authenticator.authenticate.return_value = AuthResult(
        allowed=True, user_id=admin_id, reason="OK"
    )

    session_mock = MagicMock()
    session_mock.post.side_effect = requests.RequestException("Network dropped")

    bot = TelegramControlBot(
        token="test-bot-token",
        authenticator=authenticator,
        nonce_manager=MagicMock(spec=NonceManager),
        two_step=MagicMock(spec=TwoStepController),
        session=session_mock,
    )

    result = bot.send_photo(chat_id=admin_id, photo=b"photo_data", caption="caption")
    assert result is False
