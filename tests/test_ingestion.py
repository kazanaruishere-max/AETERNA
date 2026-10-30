"""Unit tests for Exness and OANDA ingestion clients.

Verifies:
1. Exness numpy rate records transformation to CandleRecord.
2. OANDA v20 JSON payload transformation to CandleRecord.
3. Invariant check: source labels are preserved ('exness_mt5' vs 'oanda_v20').
4. Timestamp conversion to standard UTC ISO-8601 string.
"""

from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from engine.ingestion.python.exness_client import ExnessClient, ExnessIngestionError
from engine.ingestion.python.oanda_client import OandaClient, OandaIngestionError


def test_exness_transform_rates_to_candles() -> None:
    """Verify conversion of MT5 rate structure to CandleRecord."""
    # Synthetic MT5 rate record (time, open, high, low, close, tick_volume, spread, real_volume)
    dt_dtype = np.dtype(
        [
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("tick_volume", "u8"),
            ("spread", "i4"),
            ("real_volume", "u8"),
        ]
    )

    mock_rates = np.array(
        [
            (1793347200, 2745.50, 2750.00, 2744.20, 2748.10, 1540, 18, 0),
            (1793348100, 2748.10, 2752.30, 2747.00, 2751.20, 1820, 17, 0),
        ],
        dtype=dt_dtype,
    )

    candles = ExnessClient.transform_rates_to_candles(mock_rates, "M15", "XAUUSD")
    assert len(candles) == 2

    c0 = candles[0]
    assert c0.pair == "XAUUSD"
    assert c0.timeframe == "M15"
    assert c0.source == "exness_mt5"
    assert c0.open == 2745.50
    assert c0.high == 2750.00
    assert c0.low == 2744.20
    assert c0.close == 2748.10
    assert c0.tick_volume == 1540
    assert c0.timestamp_utc.endswith("Z")


def test_oanda_transform_candles() -> None:
    """Verify conversion of OANDA v20 JSON structure to CandleRecord."""
    raw_oanda = [
        {
            "time": "2026-10-30T10:00:00.000000000Z",
            "volume": 940,
            "mid": {"o": "2746.00", "h": "2749.50", "l": "2745.20", "c": "2748.80"},
        },
        {
            "time": "2026-10-30T10:15:00.000000000Z",
            "volume": 1120,
            "mid": {"o": "2748.80", "h": "2753.00", "l": "2748.10", "c": "2752.40"},
        },
    ]

    candles = OandaClient.transform_oanda_candles(raw_oanda, "M15", "XAUUSD")
    assert len(candles) == 2

    c0 = candles[0]
    assert c0.pair == "XAUUSD"
    assert c0.timeframe == "M15"
    assert c0.source == "oanda_v20"
    assert c0.open == 2746.00
    assert c0.close == 2748.80
    assert c0.tick_volume == 940
    assert c0.timestamp_utc == "2026-10-30T10:00:00Z"


def test_oanda_network_error_handling() -> None:
    """Verify OandaClient raises OandaIngestionError when API returns non-200."""
    client = OandaClient(api_token="mock_token", environment="practice")

    with patch.object(client.session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized - Invalid token"
        mock_get.return_value = mock_resp

        with pytest.raises(OandaIngestionError, match="OANDA API returned error 401"):
            client.fetch_recent_candles("M15")


def test_exness_unconnected_raises() -> None:
    """Verify calling fetch_recent_candles on unconnected ExnessClient raises."""
    client = ExnessClient()
    with pytest.raises(ExnessIngestionError, match="MT5 terminal is not connected"):
        client.fetch_recent_candles("M15")
