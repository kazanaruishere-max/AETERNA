"""Position lifecycle evaluator and server-side trailing stop manager.

Enforces:
1. Serial execution pipeline: SL modify to Break-Even strictly precedes Partial Close.
2. Dynamic spread-aware stop level guard: max(trade_stops_level, current_spread) + 50 buffer points.
3. Absolute entry spread break-even offset guaranteeing non-negative Net PnL.
4. Ticket re-anchoring via POSITION_IDENTIFIER post-partial close.
5. Cooldown anti-spam and deadband protections against broker rate limiting (Error 10016).
"""

from __future__ import annotations

import dataclasses
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from engine.execution.broker_bridge import (
    ExnessBrokerBridge,
    ModifyResult,
    OrderDirection,
    PartialCloseResult,
)

logger = logging.getLogger("aeterna.execution.position_manager")


@dataclass(frozen=True)
class PositionState:
    """Immutable model representing an active trading position state in memory."""

    ticket: int  # Current active MT5 ticket (mutates post-partial close)
    position_identifier: (
        int  # Permanent unique MT5 position identifier (POSITION_IDENTIFIER)
    )
    symbol: str
    direction: OrderDirection
    open_price: float
    current_lot: float  # Active remaining volume
    initial_sl: float
    current_sl: float
    tp: float
    initial_r_pts: float  # |open_price - initial_sl|
    spread_at_entry_usd: float  # Entry spread cost in USD for absolute BE offset
    be_sl_modified: bool = False  # Layer 2 capital protection flag
    partial_closed: bool = False  # Layer 3 take-profit flag
    last_modify_time_mono: float = 0.0  # Monotonic timestamp of last modification
    elapsed_bars_m15: int = 0  # Number of closed M15 bars elapsed since entry

    def with_break_even_sl(self, new_sl: float, timestamp_mono: float) -> PositionState:
        """Return new state after successful SL break-even or trailing modification."""
        return PositionState(
            ticket=self.ticket,
            position_identifier=self.position_identifier,
            symbol=self.symbol,
            direction=self.direction,
            open_price=self.open_price,
            current_lot=self.current_lot,
            initial_sl=self.initial_sl,
            current_sl=new_sl,
            tp=self.tp,
            initial_r_pts=self.initial_r_pts,
            spread_at_entry_usd=self.spread_at_entry_usd,
            be_sl_modified=True,
            partial_closed=self.partial_closed,
            last_modify_time_mono=timestamp_mono,
            elapsed_bars_m15=self.elapsed_bars_m15,
        )

    def with_partial_close(
        self, new_ticket: int, remaining_lot: float
    ) -> PositionState:
        """Return new state after successful partial close and ticket re-anchoring."""
        return PositionState(
            ticket=new_ticket,
            position_identifier=self.position_identifier,
            symbol=self.symbol,
            direction=self.direction,
            open_price=self.open_price,
            current_lot=remaining_lot,
            initial_sl=self.initial_sl,
            current_sl=self.current_sl,
            tp=self.tp,
            initial_r_pts=self.initial_r_pts,
            spread_at_entry_usd=self.spread_at_entry_usd,
            be_sl_modified=self.be_sl_modified,
            partial_closed=True,
            last_modify_time_mono=self.last_modify_time_mono,
            elapsed_bars_m15=self.elapsed_bars_m15,
        )

    def with_elapsed_bar(self, count: int = 1) -> PositionState:
        """Return new state with incremented elapsed M15 bar count."""
        return PositionState(
            ticket=self.ticket,
            position_identifier=self.position_identifier,
            symbol=self.symbol,
            direction=self.direction,
            open_price=self.open_price,
            current_lot=self.current_lot,
            initial_sl=self.initial_sl,
            current_sl=self.current_sl,
            tp=self.tp,
            initial_r_pts=self.initial_r_pts,
            spread_at_entry_usd=self.spread_at_entry_usd,
            be_sl_modified=self.be_sl_modified,
            partial_closed=self.partial_closed,
            last_modify_time_mono=self.last_modify_time_mono,
            elapsed_bars_m15=self.elapsed_bars_m15 + count,
        )


class PositionManager:
    """Manages active position lifecycle, server-side trailing stop, and scale-out."""

    def __init__(
        self,
        bridge: ExnessBrokerBridge,
        stops_level_buffer_pts: float = 50.0,
        cooldown_seconds: float = 2.0,
        slippage_cushion_usd: float = 0.20,
        deadband_usd: float = 0.20,
        be_trigger_r: float = 1.0,
        trailing_ratchet_r: float = 2.0,
        active_position: PositionState | None = None,
    ) -> None:
        self.bridge = bridge
        self.stops_level_buffer_pts = stops_level_buffer_pts
        self.cooldown_seconds = cooldown_seconds
        self.slippage_cushion_usd = slippage_cushion_usd
        self.deadband_usd = deadband_usd
        self.be_trigger_r = float(be_trigger_r)
        self.trailing_ratchet_r = float(trailing_ratchet_r)
        self.active_position = active_position
        self.active_positions: dict[int, PositionState] = {}
        if active_position is not None:
            self.active_positions[active_position.ticket] = active_position

    def track_position(self, pos: PositionState) -> None:
        """Register or update an active position in memory."""
        self.active_position = pos
        self.active_positions[pos.ticket] = pos

    def untrack_position(self, ticket: int) -> PositionState | None:
        """Remove a position from active tracking."""
        if self.active_position is not None and self.active_position.ticket == ticket:
            self.active_position = None
        return self.active_positions.pop(ticket, None)

    def get_active_positions(self) -> list[PositionState]:
        """Return all tracked active positions."""
        if self.active_positions:
            return list(self.active_positions.values())
        if self.active_position is not None:
            return [self.active_position]
        return []

    def evaluate_bar_closed(
        self,
        current_tick: Any,
        symbol_info: Any,
        now_mono: float | None = None,
    ) -> list[tuple[PositionState, ModifyResult | None, PartialCloseResult | None]]:
        """Evaluate active positions on M15 close with bar_closed=True (exactly once per closed bar)."""
        results: list[
            tuple[PositionState, ModifyResult | None, PartialCloseResult | None]
        ] = []
        positions = self.get_active_positions()
        for pos in positions:
            res_pos, mod_res, close_res = self.evaluate_trailing_and_scaleout(
                pos=pos,
                current_tick=current_tick,
                symbol_info=symbol_info,
                now_mono=now_mono,
                bar_closed=True,
            )
            if res_pos.current_lot <= 0.0:
                self.untrack_position(pos.ticket)
            elif res_pos.ticket != pos.ticket:
                self.untrack_position(pos.ticket)
                self.track_position(res_pos)
            else:
                self.track_position(res_pos)
            results.append((res_pos, mod_res, close_res))
        return results

    def calculate_break_even_sl(self, pos: PositionState) -> float:
        """Calculate break-even SL using absolute entry spread and slippage cushion."""
        be_offset_usd = pos.spread_at_entry_usd + self.slippage_cushion_usd
        if pos.direction == "BUY":
            return round(pos.open_price + be_offset_usd, 2)
        return round(pos.open_price - be_offset_usd, 2)

    def calculate_min_stop_distance_usd(
        self, current_tick: Any, symbol_info: Any
    ) -> float:
        """Calculate spread-aware minimum stop distance in USD to prevent Error 10016 TOO_CLOSE."""
        stops_level_pts = float(getattr(symbol_info, "trade_stops_level", 0.0))
        point_size = float(getattr(symbol_info, "point", 0.01))
        current_spread_pts = (
            float(current_tick.ask) - float(current_tick.bid)
        ) / point_size
        min_stop_distance_pts = (
            max(stops_level_pts, current_spread_pts) + self.stops_level_buffer_pts
        )
        return min_stop_distance_pts * point_size

    @staticmethod
    def resolve_partial_close_lot(current_lot: float) -> tuple[float, float]:
        """Calculate 50% partial close volume and remaining volume with 0.01 lot resolution.

        # ponytail: static 50% scale-out; upgrade to dynamic tiered scale-out if multi-target exit is enabled.
        """
        if current_lot <= 0.01:
            return 0.0, round(current_lot, 2)
        raw_close = current_lot * 0.5
        close_lot = math.floor(round(raw_close * 100.0, 8)) / 100.0
        remaining_lot = round(current_lot - close_lot, 2)
        return close_lot, remaining_lot

    def _execute_partial_close(
        self, pos: PositionState
    ) -> tuple[PositionState, PartialCloseResult]:
        """Execute 50% partial close deal and re-anchor new ticket via POSITION_IDENTIFIER."""
        close_lot, expected_rem_lot = self.resolve_partial_close_lot(pos.current_lot)
        close_res = self.bridge.close_partial_position(
            ticket=pos.ticket,
            position_identifier=pos.position_identifier,
            symbol=pos.symbol,
            direction=pos.direction,
            close_lot=close_lot,
        )
        if close_res.success:
            new_ticket = (
                close_res.new_ticket if close_res.new_ticket is not None else pos.ticket
            )
            rem_lot = (
                close_res.remaining_lot
                if close_res.remaining_lot > 0.0
                else expected_rem_lot
            )
            pos = pos.with_partial_close(new_ticket=new_ticket, remaining_lot=rem_lot)
        else:
            logger.warning(
                "Partial close deal failed for ticket %s: %s",
                pos.ticket,
                close_res.error_message,
            )
        return pos, close_res

    def _evaluate_break_even_and_scaleout(
        self,
        pos: PositionState,
        current_tick: Any,
        symbol_info: Any,
        now: float,
    ) -> tuple[PositionState, ModifyResult | None, PartialCloseResult | None]:
        """Evaluate serial pipeline: move SL to BE first, then execute partial close."""
        bid = float(current_tick.bid)
        ask = float(current_tick.ask)
        trigger_dist = pos.initial_r_pts * self.be_trigger_r
        trigger_reached = (
            (bid >= (pos.open_price + trigger_dist))
            if pos.direction == "BUY"
            else (ask <= (pos.open_price - trigger_dist))
        )
        if not trigger_reached:
            return pos, None, None

        target_sl = self.calculate_break_even_sl(pos)
        min_stop_usd = self.calculate_min_stop_distance_usd(current_tick, symbol_info)
        market_dist = (bid - target_sl) if pos.direction == "BUY" else (target_sl - ask)
        if (
            market_dist < min_stop_usd
            or abs(target_sl - pos.current_sl) < self.deadband_usd
        ):
            return pos, None, None
        if (now - pos.last_modify_time_mono) < self.cooldown_seconds:
            return pos, None, None

        mod_res = self.bridge.modify_position_sltp(
            ticket=pos.ticket, symbol=pos.symbol, new_sl=target_sl, new_tp=pos.tp
        )
        if not mod_res.success:
            logger.warning(
                "BE SL modify failed for %s: withholding partial close", pos.ticket
            )
            return dataclasses.replace(pos, last_modify_time_mono=now), mod_res, None

        pos = pos.with_break_even_sl(target_sl, now)
        if pos.current_lot <= 0.01:
            logger.info(
                "Partial close skipped for %s: lot <= 0.01 (SKIPPED_MIN_LOT)",
                pos.ticket,
            )
            return pos, mod_res, None

        pos, close_res = self._execute_partial_close(pos)
        return pos, mod_res, close_res

    def _evaluate_trailing_stop(
        self,
        pos: PositionState,
        current_tick: Any,
        symbol_info: Any,
        now: float,
    ) -> tuple[PositionState, ModifyResult | None]:
        """Advance SL strictly in profit direction once break-even is active."""
        bid = float(current_tick.bid)
        ask = float(current_tick.ask)

        if pos.direction == "BUY":
            proposed_sl = round(bid - pos.initial_r_pts, 2)
            if (
                proposed_sl <= pos.current_sl
                or (proposed_sl - pos.current_sl) < self.deadband_usd
            ):
                return pos, None
            market_dist = bid - proposed_sl
        else:
            proposed_sl = round(ask + pos.initial_r_pts, 2)
            if (
                proposed_sl >= pos.current_sl
                or (pos.current_sl - proposed_sl) < self.deadband_usd
            ):
                return pos, None
            market_dist = proposed_sl - ask

        if (now - pos.last_modify_time_mono) < self.cooldown_seconds:
            return pos, None

        min_stop_usd = self.calculate_min_stop_distance_usd(current_tick, symbol_info)
        if market_dist < min_stop_usd:
            return pos, None

        mod_res = self.bridge.modify_position_sltp(
            ticket=pos.ticket, symbol=pos.symbol, new_sl=proposed_sl, new_tp=pos.tp
        )
        if mod_res.success:
            pos = pos.with_break_even_sl(proposed_sl, now)
        else:
            pos = dataclasses.replace(pos, last_modify_time_mono=now)
        return pos, mod_res

    def on_bar_closed(
        self,
        pos: PositionState,
    ) -> tuple[PositionState, PartialCloseResult | None]:
        """Advance position by one closed M15 bar and evaluate time invalidation."""
        pos = pos.with_elapsed_bar(1)
        return self.evaluate_time_invalidation(pos)

    def evaluate_time_invalidation(
        self,
        pos: PositionState,
        elapsed_bars_m15: int | None = None,
        bar_closed: bool = False,
    ) -> tuple[PositionState, PartialCloseResult | None]:
        """Evaluate Lapis 4 Time Invalidation (8 closed bars on M15) and liquidate if expired."""
        if bar_closed:
            pos = pos.with_elapsed_bar(1)
        bars = pos.elapsed_bars_m15 if elapsed_bars_m15 is None else elapsed_bars_m15
        if self.is_time_invalidated(bars):
            logger.info(
                "Lapis 4 Time Invalidation triggered for ticket %s (%d bars M15). Liquidating position.",
                pos.ticket,
                bars,
            )
            close_res = self.bridge.close_partial_position(
                ticket=pos.ticket,
                position_identifier=pos.position_identifier,
                symbol=pos.symbol,
                direction=pos.direction,
                close_lot=pos.current_lot,
            )
            if close_res.success:
                pos = dataclasses.replace(pos, current_lot=0.0)
            return pos, close_res
        return pos, None

    def evaluate_trailing_and_scaleout(
        self,
        pos: PositionState,
        current_tick: Any,
        symbol_info: Any,
        now_mono: float | None = None,
        elapsed_bars_m15: int | None = None,
        bar_closed: bool = False,
    ) -> tuple[PositionState, ModifyResult | None, PartialCloseResult | None]:
        """Evaluate active position against +1.0R threshold, dynamic stop guard, and trailing logic."""
        pos, time_inv_res = self.evaluate_time_invalidation(
            pos, elapsed_bars_m15=elapsed_bars_m15, bar_closed=bar_closed
        )
        if time_inv_res is not None:
            return pos, None, time_inv_res

        if current_tick is None or symbol_info is None:
            return pos, None, None

        now = time.monotonic() if now_mono is None else float(now_mono)

        if not pos.be_sl_modified:
            return self._evaluate_break_even_and_scaleout(
                pos, current_tick, symbol_info, now
            )

        if not pos.partial_closed and pos.current_lot > 0.01:
            pos, close_res = self._execute_partial_close(pos)
            return pos, None, close_res

        pos, mod_res = self._evaluate_trailing_stop(pos, current_tick, symbol_info, now)
        return pos, mod_res, None

    @staticmethod
    def is_time_invalidated(elapsed_bars_m15: int, current_r: float = 0.0) -> bool:
        """Lapis 4 Time Invalidation: force close if market is stagnant for 8 closed M15 bars (2 hours)."""
        return elapsed_bars_m15 >= 8

    @staticmethod
    def is_rollover_window(dt_utc: datetime) -> bool:
        """Lapis 5 Pre-Rollover Force Close: 15 mins before daily break (20:44 UTC summer, 21:44 UTC winter)."""
        return (dt_utc.hour == 20 and dt_utc.minute >= 44) or (
            dt_utc.hour == 21 and dt_utc.minute >= 44
        )

    @staticmethod
    def is_regime_invalidated(direction: OrderDirection, current_regime: str) -> bool:
        """Lapis 5 Regime Invalidation: emergency exit if H4 macro trend flips contrary."""
        if direction == "BUY" and current_regime == "BEARISH_TRENDING":
            return True
        return bool(direction == "SELL" and current_regime == "BULLISH_TRENDING")
