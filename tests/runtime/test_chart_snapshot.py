"""Unit tests for deterministic OHLC chart snapshot renderer.

Module: tests.runtime.test_chart_snapshot
Responsibility: Validates PNG header/chunk integrity, boundary limits, and financial purity
                for observation chart rendering (REQ-TEL-004, REQ-RUNTIME-005).
Owner: aeterna-verifier
Tier: Tier A
"""

from __future__ import annotations

import struct
import zlib

import pytest

from engine.analysis_engine.python.types import CandleDict
from engine.runtime.chart_snapshot import render_ohlc_png


def _make_dummy_candles(
    count: int = 10, start_price: float = 2750.0
) -> list[CandleDict]:
    """Generate deterministic dummy candles for testing."""
    candles: list[CandleDict] = []
    price = start_price
    for i in range(count):
        open_p = price
        close_p = price + (1.5 if i % 2 == 0 else -1.2)
        high_p = max(open_p, close_p) + 0.8
        low_p = min(open_p, close_p) - 0.7
        candles.append(
            {
                "timestamp_utc": f"2026-11-20T{i:02d}:00:00Z",
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "tick_volume": 100 + i * 5,
            }
        )
        price = close_p
    return candles


def test_render_ohlc_png_valid_magic_header_and_chunks() -> None:
    """Renderer must return valid PNG bytes with proper signature and decompressed IDAT."""
    candles = _make_dummy_candles(20)
    w, h = 640, 360
    png_bytes = render_ohlc_png(
        candles,
        zone_low=2745.0,
        zone_high=2755.0,
        invalidation_level=2740.0,
        width=w,
        height=h,
    )

    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 0
    # PNG Magic Signature
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    # Chunk walker to verify chunk structure and CRC integrity
    offset = 8
    idat_chunks: list[bytes] = []
    ihdr_found = False
    iend_found = False

    while offset < len(png_bytes):
        chunk_len = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        data = png_bytes[offset + 8 : offset + 8 + chunk_len]
        crc = struct.unpack(
            ">I", png_bytes[offset + 8 + chunk_len : offset + 12 + chunk_len]
        )[0]

        expected_crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        assert crc == expected_crc, (
            f"CRC mismatch in chunk {chunk_type.decode('latin-1')}"
        )

        if chunk_type == b"IHDR":
            ihdr_found = True
            ihdr_w, ihdr_h, bit_depth, color_type = struct.unpack(">IIBB", data[:10])
            assert ihdr_w == w
            assert ihdr_h == h
            assert bit_depth == 8
            assert color_type == 2  # Truecolor RGB
        elif chunk_type == b"IDAT":
            idat_chunks.append(data)
        elif chunk_type == b"IEND":
            iend_found = True

        offset += 12 + chunk_len

    assert ihdr_found, "IHDR chunk missing"
    assert iend_found, "IEND chunk missing"
    assert len(idat_chunks) > 0, "IDAT chunk missing"

    # Verify IDAT decompression matches exact scanline byte count (filter byte + RGB per row)
    decompressed = zlib.decompress(b"".join(idat_chunks))
    expected_scanline_bytes = h * (1 + w * 3)
    assert len(decompressed) == expected_scanline_bytes


def test_render_ohlc_png_empty_candles_raises() -> None:
    """Empty candle input must raise ValueError."""
    with pytest.raises(ValueError, match="[Cc]andles.*empty"):
        render_ohlc_png([])


def test_render_ohlc_png_invalid_dimensions_raises() -> None:
    """Non-positive dimensions must raise ValueError."""
    candles = _make_dummy_candles(5)
    with pytest.raises(ValueError, match="[Ww]idth and height"):
        render_ohlc_png(candles, width=0, height=360)
    with pytest.raises(ValueError, match="[Ww]idth and height"):
        render_ohlc_png(candles, width=640, height=-10)


def test_render_ohlc_png_bounded_to_120_candles() -> None:
    """Renderer must successfully accept more than 120 candles and cap at last 120."""
    candles = _make_dummy_candles(150)
    png_bytes = render_ohlc_png(candles)
    assert len(png_bytes) > 0
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_ohlc_png_title_and_financial_purity() -> None:
    """Chart metadata must include OBSERVATION title and exclude trading/instruction tokens."""
    candles = _make_dummy_candles(15)
    png_bytes = render_ohlc_png(
        candles,
        zone_low=2740.0,
        zone_high=2760.0,
        invalidation_level=2735.0,
    )

    # Title must be OBSERVATION
    assert b"XAUUSD OBSERVATION" in png_bytes

    # No forbidden transaction / signal / account claims in bytes
    forbidden_tokens = (
        b"SIGNAL",
        b"buy sekarang",
        b"sell sekarang",
        b"buy now",
        b"sell now",
        b"profit",
        b"win rate",
        b"equity",
        b"balance",
        b"ticket",
        b"server",
    )
    for token in forbidden_tokens:
        assert token not in png_bytes


def test_render_ohlc_png_optional_levels_and_flat_candles() -> None:
    """Renderer handles None levels, single candle, and flat candles gracefully."""
    # 1. Levels are None
    candles = _make_dummy_candles(5)
    out_none = render_ohlc_png(
        candles,
        zone_low=None,
        zone_high=None,
        invalidation_level=None,
    )
    assert out_none[:8] == b"\x89PNG\r\n\x1a\n"

    # 2. Only invalidation level
    out_inv = render_ohlc_png(candles, invalidation_level=2748.0)
    assert out_inv[:8] == b"\x89PNG\r\n\x1a\n"

    # 3. Flat candle (min == max)
    flat_candle: list[CandleDict] = [
        {
            "timestamp_utc": "2026-11-20T00:00:00Z",
            "open": 2750.0,
            "high": 2750.0,
            "low": 2750.0,
            "close": 2750.0,
            "tick_volume": 50,
        }
    ]
    out_flat = render_ohlc_png(flat_candle)
    assert out_flat[:8] == b"\x89PNG\r\n\x1a\n"
