"""Deterministic OHLC Chart Snapshot Renderer.

Module: engine.runtime.chart_snapshot
Responsibility: Renders deterministic OHLC PNG charts using standard library only
                adhering strictly to financial boundary and publication rules (REQ-TEL-004, REQ-RUNTIME-005).
Owner: aeterna-architect
Tier: Tier A
"""

from __future__ import annotations

import io
import struct
import zlib
from typing import Final

from engine.analysis_engine.python.types import CandleDict

BG_COLOR: Final[tuple[int, int, int]] = (18, 22, 28)
BORDER_COLOR: Final[tuple[int, int, int]] = (45, 55, 72)
GRID_COLOR: Final[tuple[int, int, int]] = (28, 35, 45)
ZONE_COLOR: Final[tuple[int, int, int]] = (25, 42, 65)
ZONE_BORDER: Final[tuple[int, int, int]] = (45, 80, 125)
INV_COLOR: Final[tuple[int, int, int]] = (235, 160, 40)
BULL_COLOR: Final[tuple[int, int, int]] = (38, 166, 154)
BEAR_COLOR: Final[tuple[int, int, int]] = (239, 83, 80)
TITLE_COLOR: Final[tuple[int, int, int]] = (220, 225, 235)

# Minimal 3x5 font table for "XAUUSD OBSERVATION"
FONT_3X5: Final[dict[str, tuple[int, ...]]] = {
    " ": (0, 0, 0, 0, 0),
    "A": (2, 5, 7, 5, 5),
    "B": (6, 5, 6, 5, 6),
    "D": (6, 5, 5, 5, 6),
    "E": (7, 4, 6, 4, 7),
    "I": (7, 2, 2, 2, 7),
    "N": (5, 7, 7, 5, 5),
    "O": (7, 5, 5, 5, 7),
    "R": (6, 5, 6, 5, 5),
    "S": (7, 4, 7, 1, 7),
    "T": (7, 2, 2, 2, 2),
    "U": (5, 5, 5, 5, 7),
    "V": (5, 5, 5, 5, 2),
    "X": (5, 5, 2, 5, 5),
}


def _make_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Pack length, chunk type, payload, and CRC32 into a PNG chunk."""
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def _encode_png(width: int, height: int, pixels: bytearray, title: str) -> bytes:
    """Encode raw RGB pixels to a valid PNG byte stream with metadata."""
    out = io.BytesIO()
    out.write(b"\x89PNG\r\n\x1a\n")
    ihdr_payload = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    out.write(_make_chunk(b"IHDR", ihdr_payload))
    meta_payload = b"Title\x00" + title.encode("latin-1")
    out.write(_make_chunk(b"tEXt", meta_payload))

    raw_scanlines = bytearray()
    row_bytes = width * 3
    for y in range(height):
        raw_scanlines.append(0)
        start = y * row_bytes
        raw_scanlines.extend(pixels[start : start + row_bytes])

    compressed = zlib.compress(bytes(raw_scanlines), level=6)
    out.write(_make_chunk(b"IDAT", compressed))
    out.write(_make_chunk(b"IEND", b""))
    return out.getvalue()


def _fill_rect(
    buf: bytearray,
    w: int,
    h: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    """Fill axis-aligned rectangle with solid color (clamped to bounds)."""
    xa, xb = max(0, min(x0, x1)), min(w - 1, max(x0, x1))
    ya, yb = max(0, min(y0, y1)), min(h - 1, max(y0, y1))
    if xa > xb or ya > yb:
        return
    c = bytes(color)
    row_width = xb - xa + 1
    for y in range(ya, yb + 1):
        idx = (y * w + xa) * 3
        buf[idx : idx + row_width * 3] = c * row_width


def _draw_text(
    buf: bytearray,
    w: int,
    h: int,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    scale: int = 2,
) -> None:
    """Draw simple bitmap text using 3x5 font table."""
    for i, ch in enumerate(text.upper()):
        bitmap = FONT_3X5.get(ch, (0, 0, 0, 0, 0))
        cx = x + i * (4 * scale)
        for row_idx, row_val in enumerate(bitmap):
            for col_idx in range(3):
                if (row_val >> (2 - col_idx)) & 1:
                    px = cx + col_idx * scale
                    py = y + row_idx * scale
                    _fill_rect(buf, w, h, px, py, px + scale - 1, py + scale - 1, color)


def _draw_zone_and_levels(
    buf: bytearray,
    w: int,
    h: int,
    px0: int,
    px1: int,
    py0: int,
    py1: int,
    price_to_y: PriceScaler,
    zone_low: float | None,
    zone_high: float | None,
    inv_level: float | None,
) -> None:
    """Draw observation zone, grid lines, and invalidation level."""
    if zone_low is not None and zone_high is not None:
        zy0 = price_to_y(max(zone_low, zone_high))
        zy1 = price_to_y(min(zone_low, zone_high))
        _fill_rect(buf, w, h, px0, zy0, px1, zy1, ZONE_COLOR)
        _fill_rect(buf, w, h, px0, zy0, px1, zy0, ZONE_BORDER)
        _fill_rect(buf, w, h, px0, zy1, px1, zy1, ZONE_BORDER)

    for k in (1, 2, 3):
        gy = py0 + int((py1 - py0) * k / 4)
        _fill_rect(buf, w, h, px0, gy, px1, gy, GRID_COLOR)

    if inv_level is not None:
        iy = price_to_y(inv_level)
        for x in range(px0, px1, 8):
            _fill_rect(buf, w, h, x, iy, min(x + 4, px1), iy, INV_COLOR)

    _fill_rect(buf, w, h, px0, py0, px1, py0, BORDER_COLOR)
    _fill_rect(buf, w, h, px0, py1, px1, py1, BORDER_COLOR)
    _fill_rect(buf, w, h, px0, py0, px0, py1, BORDER_COLOR)
    _fill_rect(buf, w, h, px1, py0, px1, py1, BORDER_COLOR)


def _draw_candles(
    buf: bytearray,
    w: int,
    h: int,
    candles: list[CandleDict],
    px0: int,
    px1: int,
    price_to_y: PriceScaler,
) -> None:
    """Render OHLC wicks and bodies."""
    n = len(candles)
    bar_width = (px1 - px0) / n
    hw = max(1, int(bar_width * 0.35))
    for i, c in enumerate(candles):
        cx = int(px0 + (i + 0.5) * bar_width)
        color = BULL_COLOR if c["close"] >= c["open"] else BEAR_COLOR
        yh = price_to_y(float(c["high"]))
        yl = price_to_y(float(c["low"]))
        _fill_rect(buf, w, h, cx, yh, cx, yl, color)
        yo = price_to_y(float(c["open"]))
        yc = price_to_y(float(c["close"]))
        by0, by1 = min(yo, yc), max(yo, yc)
        if by0 == by1:
            by1 = by0 + 1
        _fill_rect(buf, w, h, cx - hw, by0, cx + hw, by1, color)


class PriceScaler:
    """Callable helper to map price to Y coordinate in plot area."""

    def __init__(self, min_p: float, max_p: float, py0: int, py1: int) -> None:
        self.min_p = min_p
        self.max_p = max_p
        self.py0 = py0
        self.py1 = py1
        self.span = max(1e-6, max_p - min_p)

    def __call__(self, price: float) -> int:
        ratio = max(0.0, min(1.0, (price - self.min_p) / self.span))
        return round(self.py1 - ratio * (self.py1 - self.py0))


def render_ohlc_png(
    candles: list[CandleDict],
    *,
    zone_low: float | None = None,
    zone_high: float | None = None,
    invalidation_level: float | None = None,
    width: int = 640,
    height: int = 360,
) -> bytes:
    """Render deterministic OHLC chart as PNG bytes (REQ-TEL-004, REQ-RUNTIME-005)."""
    if not candles:
        raise ValueError("Candles list cannot be empty")
    if width <= 0 or height <= 0:
        raise ValueError("Width and height must be positive")

    selected = candles[-120:]
    lows = [float(c["low"]) for c in selected]
    highs = [float(c["high"]) for c in selected]
    all_prices = lows + highs
    if zone_low is not None:
        all_prices.append(zone_low)
    if zone_high is not None:
        all_prices.append(zone_high)
    if invalidation_level is not None:
        all_prices.append(invalidation_level)

    min_p, max_p = min(all_prices), max(all_prices)
    pad = 1.0 if max_p == min_p else (max_p - min_p) * 0.05
    min_p -= pad
    max_p += pad

    buf = bytearray(bytes(BG_COLOR) * (width * height))
    px0, px1 = 15, width - 15
    py0, py1 = 35, height - 15
    scaler = PriceScaler(min_p, max_p, py0, py1)

    _draw_zone_and_levels(
        buf,
        width,
        height,
        px0,
        px1,
        py0,
        py1,
        scaler,
        zone_low,
        zone_high,
        invalidation_level,
    )
    _draw_candles(buf, width, height, selected, px0, px1, scaler)
    _draw_text(
        buf, width, height, px0 + 4, 12, "XAUUSD OBSERVATION", TITLE_COLOR, scale=2
    )

    return _encode_png(width, height, buf, title="XAUUSD OBSERVATION")
