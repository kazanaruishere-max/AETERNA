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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
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

    def send_photo(self, chat_id: int, photo: bytes, caption: str) -> bool:
        """Send photo with caption to Telegram Bot API."""
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
    reasoning: tuple[str, ...] = ()


def build_observation_reasoning(
    *,
    regime: str = "UNKNOWN",
    strategy_id: str = "volatility_breakout",
    rr: float | str = 2.0,
    state: str = "NORMAL",
    news: str = "CLEAR",
    spread_z: float | str | None = None,
) -> tuple[str, ...]:
    """Construct deterministic reasoning facts for ObservationCard.

    Only deterministic facts are permitted (REQ-RUNTIME-005):
    - REGIME=<label>
    - STRATEGY=<id>
    - RR=<nilai>
    - STATE=<state>
    - NEWS=<CLEAR|BLACKOUT|PRE_NEWS>
    - SPREAD_Z=<nilai>
    """
    valid_news = ("CLEAR", "BLACKOUT", "PRE_NEWS")
    news_clean = str(news).strip().upper()
    if news_clean not in valid_news:
        news_clean = "CLEAR"

    if isinstance(rr, (int, float)):
        rr_str = f"{float(rr):.2f}"
    else:
        rr_str = str(rr).strip()

    if spread_z is None:
        spread_z_str = "0.00"
    elif isinstance(spread_z, (int, float)):
        spread_z_str = f"{float(spread_z):.2f}"
    else:
        spread_z_str = str(spread_z).strip()

    return (
        f"REGIME={regime}",
        f"STRATEGY={strategy_id}",
        f"RR={rr_str}",
        f"STATE={state}",
        f"NEWS={news_clean}",
        f"SPREAD_Z={spread_z_str}",
    )


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
    reasoning_display = " | ".join(card.reasoning) if card.reasoning else "NONE"
    formatted = (
        f"📋 OBSERVATION — {card.symbol} ({card.timestamp_utc})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧭 BIAS: {card.regime_bias}\n"
        f"🎯 ZONA: {card.zone_low:.2f} – {card.zone_high:.2f}\n"
        f"🛑 INVALIDASI: {card.invalidation_level:.2f}\n"
        f"💧 LIQUIDITY: {card.liquidity_state}\n"
        f"⛔ BLACKOUT: {blackout_display}\n"
        f"🧠 REASONING: {reasoning_display}\n"
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

    def __init__(
        self,
        client: TelegramTransport | Any,
        admin_chat_id: int,
        reasoning_enabled: bool = True,
        state_machine: Any | None = None,
        db_manager: Any | None = None,
        regime_provider: Any | None = None,
    ) -> None:
        if admin_chat_id <= 0:
            raise ValueError(
                f"admin_chat_id must be a positive integer, got: {admin_chat_id}"
            )
        self.client: TelegramTransport = client
        self.admin_chat_id = admin_chat_id
        self.reasoning_enabled = reasoning_enabled
        self.state_machine = state_machine
        self.db_manager = db_manager
        self.regime_provider = regime_provider

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

        effective_card = card
        if self.reasoning_enabled and not effective_card.reasoning:
            effective_card = self._attach_reasoning(card)

        try:
            message_text = format_observation_card(effective_card)
        except (ValueError, TypeError, OSError):
            logger.exception("Failed formatting observation card: %s", effective_card)
            raise

        payload = {
            "method": "sendMessage",
            "chat_id": self.admin_chat_id,
            "text": message_text,
        }
        try:
            return bool(self.client.send(payload))
        except (ValueError, TypeError, OSError):
            logger.exception("Client send failed for observation card")
            return False

    def publish_with_chart(
        self,
        card: ObservationCard,
        photo: bytes,
        chat_id: int | None = None,
    ) -> bool:
        """Publish card with observation chart to admin_chat_id only (REQ-RUNTIME-005, REQ-TEL-001)."""
        target_chat_id = self.admin_chat_id if chat_id is None else chat_id
        if target_chat_id != self.admin_chat_id:
            logger.warning(
                "Rejected publish_with_chart attempt to non-admin chat_id=%s (admin=%s)",
                target_chat_id,
                self.admin_chat_id,
            )
            return False

        effective_card = card
        if self.reasoning_enabled and not effective_card.reasoning:
            effective_card = self._attach_reasoning(card)

        try:
            caption = format_observation_card(effective_card)
        except (ValueError, TypeError, OSError):
            logger.exception("Failed formatting observation card: %s", effective_card)
            raise

        try:
            if hasattr(self.client, "send_photo"):
                return bool(self.client.send_photo(self.admin_chat_id, photo, caption))
            payload = {
                "method": "sendPhoto",
                "chat_id": self.admin_chat_id,
                "photo": photo,
                "caption": caption,
            }
            return bool(self.client.send(payload))
        except (ValueError, TypeError, OSError, RuntimeError):
            logger.exception("Client send_photo failed for observation chart")
            return False

    def _attach_reasoning(self, card: ObservationCard) -> ObservationCard:
        """Derive deterministic reasoning facts for an unannotated ObservationCard."""
        regime = card.regime_bias or "UNKNOWN"
        if (regime == "UNKNOWN" or not regime) and self.regime_provider is not None:
            try:
                provided = self.regime_provider()
                if provided:
                    regime = str(provided)
            except (ValueError, TypeError, OSError):
                logger.exception("Failed to query regime provider for reasoning")

        strategy_id = "volatility_breakout"
        rr = 2.0
        state = "NORMAL"
        news = "CLEAR"
        spread_z: float | None = None

        if self.db_manager is not None:
            try:
                with self.db_manager.get_connection() as conn:
                    row = conn.execute(
                        "SELECT strategy_id, state, entry_px, sl_px, tp_px, order_type "
                        "FROM signal_observations WHERE symbol = ? "
                        "ORDER BY bar_ts DESC LIMIT 1",
                        (card.symbol,),
                    ).fetchone()
                    if row is not None:
                        strategy_id = str(row["strategy_id"])
                        entry_px = float(row["entry_px"])
                        sl_px = float(row["sl_px"])
                        tp_px = float(row["tp_px"])
                        risk = abs(entry_px - sl_px)
                        reward = abs(tp_px - entry_px)
                        if risk > 0.0:
                            rr = reward / risk
            except (ValueError, TypeError, OSError):
                logger.exception("Failed to query signal record for reasoning")

        if self.state_machine is not None:
            try:
                state = str(self.state_machine.state)
                spread_z = self.state_machine.z_score
                eval_time = self._parse_card_time(card.timestamp_utc)
                if self.state_machine.news_filter.is_in_news_blackout(eval_time):
                    news = "BLACKOUT"
                elif self.state_machine.news_filter.is_in_pre_news_window(eval_time):
                    news = "PRE_NEWS"
                else:
                    news = "CLEAR"
            except (ValueError, TypeError, OSError):
                logger.exception("Failed to query state machine for reasoning")

        reasoning = build_observation_reasoning(
            regime=regime,
            strategy_id=strategy_id,
            rr=rr,
            state=state,
            news=news,
            spread_z=spread_z,
        )
        new_bias = (
            regime
            if card.regime_bias == "UNKNOWN" and regime != "UNKNOWN"
            else card.regime_bias
        )
        return replace(card, regime_bias=new_bias, reasoning=reasoning)

    @staticmethod
    def _parse_card_time(timestamp_utc: str) -> datetime:
        """Parse card timestamp string into UTC datetime, fallback to current UTC."""
        try:
            val = timestamp_utc.strip()
            if val.endswith(" UTC"):
                val_dt = val[:-4].strip()
                return datetime.fromisoformat(val_dt).replace(tzinfo=UTC)
            if val.endswith("Z"):
                val = val[:-1] + "+00:00"
            dt = datetime.fromisoformat(val)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except (ValueError, TypeError, OSError):
            return datetime.now(tz=UTC)
