"""Admin-only observation card formatter and publisher.

Module: engine.runtime.dashboard
Responsibility: Transforms internal market observations into an admin-only text format
                adhering strictly to financial boundary and publication rules (REQ-TEL-001, REQ-TEL-004).
Owner: aeterna-architect
Tier: Tier A
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final, Protocol

from engine.telegram_bot.templates import validate_text_purity

logger = logging.getLogger("aeterna.runtime.dashboard")

PROHIBITED_CARD_TOKENS: Final[tuple[str, ...]] = (
    "buy sekarang",
    "sell sekarang",
    "buy now",
    "sell now",
    "win rate",
    "pastikan untung",
    "garansi",
    "profit",
    "equity",
    "balance",
    "ticket",
    "server",
)

LOT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?:^|[^a-zA-Z])lots?(?:[^a-zA-Z]|$)"
)
OLD_TEMPLATE_HEADER: Final[str] = "SIGNAL — XAUUSD"


class TelegramTransport(Protocol):
    """Protocol for Telegram client transport."""

    def send(self, payload: dict[str, Any]) -> bool:
        """Send payload to Telegram Bot API."""
        ...


@dataclass(frozen=True)
class ObservationCard:
    """Immutable internal market structure observation card."""

    timestamp_utc: str
    symbol: str
    regime_bias: str
    zone_low: float
    zone_high: float
    invalidation_level: float
    liquidity_state: str
    blackout_window: str | None
    sample_count: int
    data_tag: str = "internal_virtual_journal"


def _check_forbidden_tokens(text: str) -> None:
    """Validate that text strictly contains no trading execution or performance claims."""
    lower_text = text.lower()
    for token in PROHIBITED_CARD_TOKENS:
        if token in lower_text:
            raise ValueError(f"Prohibited token detected: '{token}'")

    if LOT_PATTERN.search(text):
        raise ValueError("Prohibited token detected: 'lot'")

    if OLD_TEMPLATE_HEADER in text:
        raise ValueError("Prohibited legacy signal header detected.")


def format_observation_card(card: ObservationCard) -> str:
    """Format an ObservationCard into a validated admin-only text notification.

    Guarantees presence of required structural labels and strict exclusion of
    commercial signal vending or imperative transaction wording.
    """
    blackout_display = (
        card.blackout_window if card.blackout_window is not None else "NONE"
    )
    formatted = (
        f"📋 OBSERVATION — {card.symbol} ({card.timestamp_utc})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧭 BIAS: {card.regime_bias}\n"
        f"🎯 ZONA: {card.zone_low:.2f} – {card.zone_high:.2f}\n"
        f"🛑 INVALIDASI: {card.invalidation_level:.2f}\n"
        f"💧 LIQUIDITY: {card.liquidity_state}\n"
        f"⛔ BLACKOUT: {blackout_display}\n"
        f"🔢 SAMPLE: #{card.sample_count}\n"
        f"🏷 DATA_TAG: {card.data_tag}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ Internal market structure observation. Not financial advice."
    )

    validate_text_purity(formatted)
    _check_forbidden_tokens(formatted)
    return formatted


class SignalOnlyDashboard:
    """Admin-only observation card publisher enforcing strict audience boundaries."""

    def __init__(self, client: TelegramTransport | Any, admin_chat_id: int) -> None:
        if admin_chat_id <= 0:
            raise ValueError(
                f"admin_chat_id must be a positive integer, got: {admin_chat_id}"
            )
        self.client: TelegramTransport = client
        self.admin_chat_id = admin_chat_id

    def publish(self, card: ObservationCard, chat_id: int | None = None) -> bool:
        """Publish card to admin_chat_id only. Silent reject on destination mismatch."""
        target_chat_id = self.admin_chat_id if chat_id is None else chat_id
        if target_chat_id != self.admin_chat_id:
            logger.warning(
                "Rejected publish attempt to non-admin chat_id=%s (admin=%s)",
                target_chat_id,
                self.admin_chat_id,
            )
            return False

        try:
            message_text = format_observation_card(card)
        except Exception:
            logger.exception("Failed formatting observation card: %s", card)
            raise

        payload = {
            "method": "sendMessage",
            "chat_id": self.admin_chat_id,
            "text": message_text,
        }
        try:
            return bool(self.client.send(payload))
        except Exception:
            logger.exception("Client send failed for observation card")
            return False
