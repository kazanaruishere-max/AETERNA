"""OANDA v20 REST Data Ingestion Client (Scanning Only).

Pulls M1, M15, H1, and H4 candles and Order/Position Book positioning data
directly from OANDA v20 REST API.

STRICT INVARIANT:
OANDA is SCANNING ONLY. It never places, modifies, or executes orders.
"""

from __future__ import annotations

import logging
from typing import Any
import requests

from engine.models import CandleRecord, Timeframe

logger = logging.getLogger("aeterna.ingestion.oanda")

OANDA_TIMEFRAME_MAP: dict[Timeframe, str] = {
    "M1": "M1",
    "M15": "M15",
    "H1": "H1",
    "H4": "H4",
}


class OandaIngestionError(Exception):
    """Raised when OANDA v20 REST API call fails."""


class OandaClient:
    """REST Client for OANDA v20 market scanning and sentiment positioning."""

    PRACTICE_URL = "https://api-fxpractice.oanda.com"
    LIVE_URL = "https://api-fxtrade.oanda.com"

    def __init__(
        self,
        api_token: str,
        account_id: str | None = None,
        environment: str = "practice",
        instrument: str = "XAU_USD",
        timeout_sec: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.api_token = api_token
        self.account_id = account_id
        self.base_url = self.LIVE_URL if environment == "live" else self.PRACTICE_URL
        self.instrument = instrument
        self.timeout_sec = timeout_sec
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "User-Agent": "AeternaQuant/1.0",
            }
        )

    def fetch_recent_candles(
        self,
        timeframe: Timeframe,
        count: int = 100,
    ) -> list[CandleRecord]:
        """Fetch latest midpoint candles from OANDA v20 and transform to CandleRecord list."""
        granularity = OANDA_TIMEFRAME_MAP.get(timeframe)
        if not granularity:
            raise OandaIngestionError(f"Unsupported timeframe for OANDA: {timeframe}")

        endpoint = f"{self.base_url}/v3/instruments/{self.instrument}/candles"
        params = {
            "price": "M",  # Midpoint candles
            "granularity": granularity,
            "count": min(count, 500),
        }

        try:
            resp = self.session.get(endpoint, params=params, timeout=self.timeout_sec)
        except requests.RequestException as e:
            raise OandaIngestionError(f"Network error querying OANDA candles: {e}") from e

        if resp.status_code != 200:
            raise OandaIngestionError(
                f"OANDA API returned error {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        raw_candles = data.get("candles", [])
        return self.transform_oanda_candles(raw_candles, timeframe, "XAUUSD")

    @staticmethod
    def transform_oanda_candles(
        raw_candles: list[dict[str, Any]],
        timeframe: Timeframe,
        pair_symbol: str = "XAUUSD",
    ) -> list[CandleRecord]:
        """Convert raw OANDA v20 candle dicts into domain CandleRecord list."""
        candles: list[CandleRecord] = []
        for c in raw_candles:
            # OANDA time format: '2026-10-30T10:00:00.000000000Z'
            raw_time: str = c.get("time", "")
            # Normalize to standard ISO-8601 YYYY-MM-DDTHH:MM:SSZ
            timestamp_utc = raw_time[:19] + "Z" if len(raw_time) >= 19 else raw_time

            mid = c.get("mid", {})
            candles.append(
                CandleRecord(
                    pair=pair_symbol,
                    timeframe=timeframe,
                    timestamp_utc=timestamp_utc,
                    source="oanda_v20",
                    open=float(mid.get("o", 0.0)),
                    high=float(mid.get("h", 0.0)),
                    low=float(mid.get("l", 0.0)),
                    close=float(mid.get("c", 0.0)),
                    tick_volume=int(c.get("volume", 0)),
                )
            )
        return candles

    def fetch_order_book(self) -> dict[str, Any]:
        """Fetch OANDA Order Book snapshot for positioning analysis (Refreshes ~15-30m)."""
        endpoint = f"{self.base_url}/v3/instruments/{self.instrument}/orderBook"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout_sec)
        except requests.RequestException as e:
            raise OandaIngestionError(f"Network error querying OANDA orderBook: {e}") from e

        if resp.status_code != 200:
            raise OandaIngestionError(
                f"OANDA API returned error {resp.status_code}: {resp.text}"
            )
        return resp.json().get("orderBook", {})

    def fetch_position_book(self) -> dict[str, Any]:
        """Fetch OANDA Position Book snapshot for long/short positioning skew."""
        endpoint = f"{self.base_url}/v3/instruments/{self.instrument}/positionBook"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout_sec)
        except requests.RequestException as e:
            raise OandaIngestionError(f"Network error querying OANDA positionBook: {e}") from e

        if resp.status_code != 200:
            raise OandaIngestionError(
                f"OANDA API returned error {resp.status_code}: {resp.text}"
            )
        return resp.json().get("positionBook", {})
