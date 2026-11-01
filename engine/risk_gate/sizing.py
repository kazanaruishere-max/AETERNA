"""Financial position sizing engine enforcing strict risk invariant.

Enforces financial invariants:
- REQ-RSK-003: Graduated liquidity sizing (scale before floor).
- REQ-RSK-006: Rollover buffer block ('pre_rollover_force').
- REQ-ING-002: Distinct audit rejection reasons ('pre_rollover_force' vs 'insufficient_equity_for_min_lot').
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from engine.risk_gate.liquidity import RolloverFilter


@dataclass(frozen=True)
class SizingResult:
    """Outcome of position sizing calculation with audit fields."""

    lot_size: float
    risk_usd: float = 0.0
    raw_lot: float = 0.0
    liquidity_scale: float = 1.0
    is_valid: bool = False
    rejection_reason: str | None = None


class PositionSizer:
    """Financial position sizer enforcing risk invariant and scale-before-floor ordering.

    Enforces REQ-RSK-003, REQ-RSK-006, REQ-ING-002:
    - Max risk 0.5% (0.005) of account equity.
    - Scale Base Raw Lot BEFORE rounding down to 0.01 step.
    - Reject sub-minimum lot without rounding up.
    - Explicit audit reason: 'pre_rollover_force' or 'insufficient_equity_for_min_lot'.
    """

    def __init__(
        self,
        risk_per_trade_pct: float = 0.005,
        contract_size: float = 100.0,
        min_lot: float = 0.01,
        max_lot: float = 50.0,
    ) -> None:
        if risk_per_trade_pct <= 0.0 or risk_per_trade_pct > 1.0:
            raise ValueError(f"risk_per_trade_pct must be between 0 and 1, got {risk_per_trade_pct}")
        if contract_size <= 0.0:
            raise ValueError(f"contract_size must be positive, got {contract_size}")
        if min_lot <= 0.0:
            raise ValueError(f"min_lot must be positive, got {min_lot}")
        if max_lot < min_lot:
            raise ValueError(f"max_lot ({max_lot}) must be >= min_lot ({min_lot})")

        self.risk_per_trade_pct = float(risk_per_trade_pct)
        self.contract_size = float(contract_size)
        self.min_lot = float(min_lot)
        self.max_lot = float(max_lot)

    def calculate_lot_size(
        self,
        equity_usd: float,
        entry_price: float,
        sl_price: float,
        liquidity_scale: float = 1.0,
        is_rollover: bool = False,
        current_utc: datetime | None = None,
    ) -> SizingResult:
        """Calculate compliant lot size with scale-before-floor invariant.

        Args:
            equity_usd: Current account equity in USD.
            entry_price: Planned entry price.
            sl_price: Stop loss price.
            liquidity_scale: Scale factor from tick volume filter (1.0 or 0.5).
            is_rollover: Direct boolean flag indicating active rollover window.
            current_utc: Optional timestamp evaluated against rollover buffer.

        Returns:
            SizingResult with lot_size, audit fields, validity flag, and rejection reason.
        """
        # Calculate risk budget and SL distance
        risk_usd = max(0.0, float(equity_usd) * self.risk_per_trade_pct)
        sl_dist_pts = abs(float(entry_price) - float(sl_price))
        sl_dist_usd = sl_dist_pts * self.contract_size

        base_raw_lot = (risk_usd / sl_dist_usd) if sl_dist_usd > 0.0 else 0.0

        # 1. Rollover Check
        in_rollover = is_rollover or (
            current_utc is not None and RolloverFilter.is_in_rollover_buffer(current_utc)
        )
        if in_rollover:
            return SizingResult(
                lot_size=0.0,
                risk_usd=risk_usd,
                raw_lot=base_raw_lot,
                liquidity_scale=liquidity_scale,
                is_valid=False,
                rejection_reason="pre_rollover_force",
            )

        # 2. Invalid Stop Loss
        if sl_dist_usd <= 0.0:
            return SizingResult(
                lot_size=0.0,
                risk_usd=risk_usd,
                raw_lot=0.0,
                liquidity_scale=liquidity_scale,
                is_valid=False,
                rejection_reason="invalid_stop_loss",
            )

        # 3. Urutan Operasi Sizing (Scale-Before-Floor)
        scaled_lot = base_raw_lot * float(liquidity_scale)
        # Floor to 0.01 lot step avoiding floating-point imprecision
        final_lot = round(math.floor(round(scaled_lot * 100.0, 8)) / 100.0, 2)

        # 4. Minimum Lot Enforcement (No rounding up)
        if final_lot < self.min_lot:
            return SizingResult(
                lot_size=0.0,
                risk_usd=risk_usd,
                raw_lot=base_raw_lot,
                liquidity_scale=liquidity_scale,
                is_valid=False,
                rejection_reason="insufficient_equity_for_min_lot",
            )

        # 5. Cap at Maximum Lot
        final_lot = min(final_lot, self.max_lot)

        return SizingResult(
            lot_size=final_lot,
            risk_usd=risk_usd,
            raw_lot=base_raw_lot,
            liquidity_scale=liquidity_scale,
            is_valid=True,
            rejection_reason=None,
        )
