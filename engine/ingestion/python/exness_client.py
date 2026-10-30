"""Exness MT5 Data Ingestion Client (Windows Native).

Ingests M1, M15, H1, and H4 OHLCV bars plus tick volume via the official MetaTrader5
Python package. Maps broker data into immutable CandleRecord objects.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from engine.models import CandleRecord, Timeframe

logger = logging.getLogger("aeterna.ingestion.exness")

# Mapping of engine timeframes to MetaTrader5 constants
TIMEFRAME_MAP: dict[Timeframe, str] = {
    "M1": "TIMEFRAME_M1",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
}


class ExnessIngestionError(Exception):
    """Raised when Exness MT5 ingestion fails or terminal is unresponsive."""


class ExnessClient:
    """Handles communication with local MetaTrader 5 terminal for Exness."""

    def __init__(
        self,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        symbol: str = "XAUUSD",
    ) -> None:
        self.login = login
        self.password = password
        self.server = server
        self.symbol = symbol
        self._connected = False
        self._mt5: Any = None

    def connect(self) -> bool:
        """Initialize connection to local MetaTrader 5 terminal."""
        try:
            import MetaTrader5 as mt5  # type: ignore

            self._mt5 = mt5
        except ImportError:
            logger.warning("MetaTrader5 package not available in current environment.")
            return False

        if not self._mt5.initialize():
            err = self._mt5.last_error()
            logger.error("MT5 initialize() failed with error: %s", err)
            return False

        if self.login and self.password and self.server:
            authorized = self._mt5.login(
                login=self.login,
                password=self.password,
                server=self.server,
            )
            if not authorized:
                err = self._mt5.last_error()
                logger.error("MT5 login failed: %s", err)
                return False

        self._connected = True
        logger.info("Successfully connected to Exness MT5 (Symbol: %s)", self.symbol)
        return True

    def disconnect(self) -> None:
        """Shutdown MT5 terminal connection."""
        if self._mt5 and self._connected:
            self._mt5.shutdown()
            self._connected = False

    def fetch_recent_candles(
        self,
        timeframe: Timeframe,
        count: int = 100,
    ) -> list[CandleRecord]:
        """Fetch latest closed/open bars from MT5 and transform into CandleRecord list."""
        if not self._connected or not self._mt5:
            raise ExnessIngestionError("MT5 terminal is not connected.")

        tf_attr = TIMEFRAME_MAP.get(timeframe)
        if not tf_attr or not hasattr(self._mt5, tf_attr):
            raise ExnessIngestionError(f"Unsupported timeframe: {timeframe}")

        mt5_tf = getattr(self._mt5, tf_attr)
        rates = self._mt5.copy_rates_from_pos(self.symbol, mt5_tf, 0, count)

        if rates is None or len(rates) == 0:
            err = self._mt5.last_error()
            raise ExnessIngestionError(f"Failed to copy rates for {self.symbol} ({timeframe}): {err}")

        return self.transform_rates_to_candles(rates, timeframe, self.symbol)

    @staticmethod
    def transform_rates_to_candles(
        rates: Any,
        timeframe: Timeframe,
        symbol: str = "XAUUSD",
    ) -> list[CandleRecord]:
        """Transform numpy structured array from MT5 to domain CandleRecord list."""
        candles: list[CandleRecord] = []
        for bar in rates:
            # MT5 time is epoch integer in UTC
            dt = datetime.fromtimestamp(bar["time"], tz=timezone.utc)
            timestamp_utc = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            candles.append(
                CandleRecord(
                    pair=symbol,
                    timeframe=timeframe,
                    timestamp_utc=timestamp_utc,
                    source="exness_mt5",
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    tick_volume=int(bar["tick_volume"]),
                )
            )
        return candles

    def get_current_spread_pips(self) -> float:
        """Retrieve real-time bid/ask and return spread in pips (0.10 USD = 1.0 pip for Gold)."""
        if not self._connected or not self._mt5:
            raise ExnessIngestionError("MT5 terminal is not connected.")

        tick = self._mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise ExnessIngestionError(f"Failed to fetch tick for {self.symbol}")

        spread_usd = float(tick.ask - tick.bid)
        # For XAUUSD, 1 standard pip = 0.10 USD (point = 0.01)
        return round(spread_usd * 10.0, 2)
