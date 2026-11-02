"""Unit tests for server-side trailing stop manager, serial queue, and ticket re-anchoring.

Covers:
1. Serial execution pipeline: SL modify to BE strictly precedes Partial Close.
2. Dynamic spread-aware stop level guard: max(trade_stops_level, current_spread) + 50 buffer points.
3. Absolute entry spread break-even offset: guarantees non-negative Net PnL.
4. Odd lot resolution: floor rounding to 0.01 lot resolution.
5. Minimum lot 0.01 handling: skip partial close safely.
6. Ticket re-anchoring post-partial close via POSITION_IDENTIFIER.
7. Cooldown anti-spam protection (< 2.0s interval).
8. Trailing stop advances strictly in profit direction (pantang bergeser mundur).
9. ExnessBrokerBridge modify_position_sltp and close_partial_position direct behavior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from unittest.mock import MagicMock

from engine.execution.broker_bridge import (
    ExnessBrokerBridge,
    ModifyResult,
    PartialCloseResult,
)
from engine.execution.position_manager import (
    PositionManager,
    PositionState,
)
from engine.ingestion.python.exness_client import ExnessClient


@dataclass(frozen=True)
class DummyTick:
    bid: float
    ask: float


@dataclass(frozen=True)
class DummySymbolInfo:
    trade_stops_level: int = 0
    point: float = 0.01


def _create_mock_client() -> tuple[ExnessClient, MagicMock]:
    """Helper to instantiate ExnessClient with mocked MT5 backend."""
    mock_mt5 = MagicMock()
    mock_mt5.TRADE_ACTION_DEAL = 1
    mock_mt5.TRADE_ACTION_SLTP = 6
    mock_mt5.ORDER_TYPE_BUY = 0
    mock_mt5.ORDER_TYPE_SELL = 1
    mock_mt5.TRADE_RETCODE_DONE = 10009
    mock_mt5.ORDER_FILLING_IOC = 1
    mock_mt5.ORDER_FILLING_FOK = 0
    mock_mt5.SYMBOL_FILLING_IOC = 2
    client = ExnessClient(symbol="XAUUSD")
    client.connected = True
    client.mt5 = mock_mt5
    return client, mock_mt5


def _create_sample_buy_pos(
    current_lot: float = 0.04,
    current_sl: float = 2740.0,
    be_sl_modified: bool = False,
    partial_closed: bool = False,
    last_modify_time_mono: float = 0.0,
) -> PositionState:
    """Helper to create standard BUY PositionState."""
    return PositionState(
        ticket=10001,
        position_identifier=9999,
        symbol="XAUUSD",
        direction="BUY",
        open_price=2750.0,
        current_lot=current_lot,
        initial_sl=2740.0,
        current_sl=current_sl,
        tp=2770.0,
        initial_r_pts=10.0,
        spread_at_entry_usd=0.35,
        be_sl_modified=be_sl_modified,
        partial_closed=partial_closed,
        last_modify_time_mono=last_modify_time_mono,
    )


def test_sequential_execution_pipeline_sl_before_partial_close() -> None:
    """Trigger +1.0R: verify modify_position_sltp precedes close_partial_position.

    If modify fails, partial close must be strictly withheld.
    """
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04)

    # 1. Successful modify path: both modify and close are called in strict order
    call_log: list[str] = []

    def handle_modify(*_args: object, **_kwargs: object) -> ModifyResult:
        call_log.append("modify_position_sltp")
        return ModifyResult(success=True, ticket=10001, new_sl=2750.55, new_tp=2770.0)

    def handle_close(*_args: object, **_kwargs: object) -> PartialCloseResult:
        call_log.append("close_partial_position")
        return PartialCloseResult(
            success=True,
            closed_ticket=10001,
            new_ticket=10002,
            closed_lot=0.02,
            remaining_lot=0.02,
            executed_price=2760.5,
        )

    mock_bridge.modify_position_sltp.side_effect = handle_modify
    mock_bridge.close_partial_position.side_effect = handle_close

    tick = DummyTick(bid=2760.5, ask=2760.8)  # +1.0R reached (bid >= 2760.0)
    symbol_info = DummySymbolInfo(trade_stops_level=50, point=0.01)

    new_pos, mod_res, close_res = pm.evaluate_trailing_and_scaleout(
        pos, tick, symbol_info, now_mono=10.0
    )

    assert call_log == ["modify_position_sltp", "close_partial_position"]
    assert mod_res is not None and mod_res.success
    assert close_res is not None and close_res.success
    assert new_pos.be_sl_modified is True
    assert new_pos.partial_closed is True
    assert new_pos.ticket == 10002
    assert new_pos.current_lot == 0.02

    # 2. Modify failure path: partial close must NOT be called
    call_log.clear()
    mock_bridge.modify_position_sltp.side_effect = None
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        success=False,
        ticket=10001,
        new_sl=2750.55,
        new_tp=2770.0,
        error_code=10016,
        error_message="Too close to market",
    )
    mock_bridge.close_partial_position.reset_mock()

    new_pos_fail, mod_res_fail, close_res_fail = pm.evaluate_trailing_and_scaleout(
        pos, tick, symbol_info, now_mono=10.0
    )

    assert mod_res_fail is not None and not mod_res_fail.success
    assert close_res_fail is None
    mock_bridge.close_partial_position.assert_not_called()
    assert new_pos_fail.be_sl_modified is False
    assert new_pos_fail.partial_closed is False


def test_dynamic_spread_aware_stop_level_guard() -> None:
    """Verify stops_level=300 and spread=450 uses max(300, 450) + 50 = 500 pts.

    Request with 400 pts distance must be held/skipped.
    """
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)

    # stops_level = 300 pts, point = 0.01
    symbol_info = DummySymbolInfo(trade_stops_level=300, point=0.01)

    # Tick with spread = 4.50 USD = 450 pts (ask - bid)
    # bid = 2760.00, ask = 2764.50
    tick = DummyTick(bid=2760.0, ask=2764.5)

    # Min stop distance = max(300, 450) + 50 = 500 pts = 5.00 USD
    min_stop_usd = pm.calculate_min_stop_distance_usd(tick, symbol_info)
    assert math.isclose(min_stop_usd, 5.0, abs_tol=1e-6)

    # Position configured so BE target SL is 2756.00 (distance to bid = 2760.00 - 2756.00 = 4.00 USD = 400 pts)
    # open_price = 2750.00, spread_at_entry_usd = 5.80 -> be_sl = 2750.00 + 5.80 + 0.20 = 2756.00
    pos_tight = PositionState(
        ticket=10001,
        position_identifier=9999,
        symbol="XAUUSD",
        direction="BUY",
        open_price=2750.0,
        current_lot=0.04,
        initial_sl=2740.0,
        current_sl=2740.0,
        tp=2780.0,
        initial_r_pts=10.0,
        spread_at_entry_usd=5.80,
    )

    # Market distance = 2760.0 - 2756.0 = 4.0 USD (< 5.0 USD min distance) -> MUST HOLD
    new_pos, mod_res, close_res = pm.evaluate_trailing_and_scaleout(
        pos_tight, tick, symbol_info, now_mono=10.0
    )

    assert mod_res is None
    assert close_res is None
    mock_bridge.modify_position_sltp.assert_not_called()
    assert new_pos.be_sl_modified is False

    # When market advances so distance >= 5.0 USD (e.g. bid = 2762.0 -> distance 6.0 USD >= 5.0 USD)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        success=True, ticket=10001, new_sl=2756.0, new_tp=2780.0
    )
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=True,
        closed_ticket=10001,
        new_ticket=10002,
        closed_lot=0.02,
        remaining_lot=0.02,
        executed_price=2762.0,
    )

    tick_wide = DummyTick(bid=2762.0, ask=2766.5)
    _new_pos_ok, mod_res_ok, _close_res_ok = pm.evaluate_trailing_and_scaleout(
        pos_tight, tick_wide, symbol_info, now_mono=10.0
    )

    assert mod_res_ok is not None and mod_res_ok.success
    assert mock_bridge.modify_position_sltp.call_count == 1


def test_break_even_offset_guarantees_non_negative_net_pnl() -> None:
    """Verify Entry 2750.00, entry spread 0.35, cushion 0.20 yields SL_be 2750.55 with Net PnL >= 0.0."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge, slippage_cushion_usd=0.20)

    # BUY position
    pos_buy = _create_sample_buy_pos()
    sl_be_buy = pm.calculate_break_even_sl(pos_buy)
    assert sl_be_buy == 2750.55

    # Net PnL at SL = (Exit Bid - Entry Price) - Entry Spread
    gross_pnl_buy = sl_be_buy - pos_buy.open_price
    net_pnl_buy = gross_pnl_buy - pos_buy.spread_at_entry_usd
    assert math.isclose(net_pnl_buy, 0.20, abs_tol=1e-6)
    assert net_pnl_buy >= 0.0

    # SELL position
    pos_sell = PositionState(
        ticket=20001,
        position_identifier=8888,
        symbol="XAUUSD",
        direction="SELL",
        open_price=2750.0,
        current_lot=0.04,
        initial_sl=2760.0,
        current_sl=2760.0,
        tp=2730.0,
        initial_r_pts=10.0,
        spread_at_entry_usd=0.35,
    )
    sl_be_sell = pm.calculate_break_even_sl(pos_sell)
    assert sl_be_sell == 2749.45

    # Net PnL at SL = (Entry Price - Exit Ask) - Entry Spread
    gross_pnl_sell = pos_sell.open_price - sl_be_sell
    net_pnl_sell = gross_pnl_sell - pos_sell.spread_at_entry_usd
    assert math.isclose(net_pnl_sell, 0.20, abs_tol=1e-6)
    assert net_pnl_sell >= 0.0


def test_partial_close_lot_resolution_odd_numbers() -> None:
    """Verify odd lot resolution: 0.03 -> Close 0.01, Rem 0.02; 0.05 -> Close 0.02, Rem 0.03."""
    # Lot 0.03
    close_03, rem_03 = PositionManager.resolve_partial_close_lot(0.03)
    assert close_03 == 0.01
    assert rem_03 == 0.02
    assert round(close_03 + rem_03, 2) == 0.03

    # Lot 0.05
    close_05, rem_05 = PositionManager.resolve_partial_close_lot(0.05)
    assert close_05 == 0.02
    assert rem_05 == 0.03
    assert round(close_05 + rem_05, 2) == 0.05

    # Lot 0.10 (even)
    close_10, rem_10 = PositionManager.resolve_partial_close_lot(0.10)
    assert close_10 == 0.05
    assert rem_10 == 0.05

    # Lot 0.02 (minimum even)
    close_02, rem_02 = PositionManager.resolve_partial_close_lot(0.02)
    assert close_02 == 0.01
    assert rem_02 == 0.01


def test_partial_close_skipped_for_minimum_lot_0_01() -> None:
    """Verify lot 0.01 at +1.0R skips partial close deal while safely advancing SL to Break-Even."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        success=True, ticket=10001, new_sl=2750.55, new_tp=2770.0
    )

    pm = PositionManager(bridge=mock_bridge)
    pos_min = _create_sample_buy_pos(current_lot=0.01)

    tick = DummyTick(bid=2760.5, ask=2760.8)
    symbol_info = DummySymbolInfo(trade_stops_level=50, point=0.01)

    new_pos, mod_res, close_res = pm.evaluate_trailing_and_scaleout(
        pos_min, tick, symbol_info, now_mono=10.0
    )

    assert mod_res is not None and mod_res.success
    assert close_res is None
    mock_bridge.close_partial_position.assert_not_called()
    assert new_pos.be_sl_modified is True
    assert new_pos.current_sl == 2750.55
    assert new_pos.current_lot == 0.01
    assert new_pos.partial_closed is False


def test_ticket_re_anchoring_post_partial_close() -> None:
    """Verify ticket changes from #10001 to #10002 post-partial close via POSITION_IDENTIFIER 9999."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        success=True, ticket=10001, new_sl=2750.55, new_tp=2770.0
    )
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=True,
        closed_ticket=10001,
        new_ticket=10002,
        closed_lot=0.02,
        remaining_lot=0.02,
        executed_price=2760.5,
    )

    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04)

    tick = DummyTick(bid=2760.5, ask=2760.8)
    symbol_info = DummySymbolInfo(trade_stops_level=50, point=0.01)

    new_pos, _mod_res, close_res = pm.evaluate_trailing_and_scaleout(
        pos, tick, symbol_info, now_mono=10.0
    )

    assert new_pos.ticket == 10002
    assert new_pos.position_identifier == 9999
    assert new_pos.current_lot == 0.02
    assert new_pos.partial_closed is True
    assert close_res is not None and close_res.new_ticket == 10002


def test_cooldown_anti_spam() -> None:
    """Verify modify request within < 2.0s cooldown interval is skipped."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        success=True, ticket=10001, new_sl=2755.0, new_tp=2770.0
    )

    pm = PositionManager(bridge=mock_bridge, cooldown_seconds=2.0)
    pos = _create_sample_buy_pos(
        be_sl_modified=True,
        partial_closed=True,
        current_sl=2750.55,
        last_modify_time_mono=100.0,
    )

    # Advance price: bid = 2765.0 -> proposed trailing SL = 2765.0 - 10.0 = 2755.0 (> 2750.55)
    tick = DummyTick(bid=2765.0, ask=2765.3)
    symbol_info = DummySymbolInfo(trade_stops_level=50, point=0.01)

    # 1. At now_mono = 101.5 (1.5s since last modify, < 2.0s): MUST SKIP
    new_pos_cool, mod_res_cool, _ = pm.evaluate_trailing_and_scaleout(
        pos, tick, symbol_info, now_mono=101.5
    )
    assert mod_res_cool is None
    mock_bridge.modify_position_sltp.assert_not_called()
    assert new_pos_cool.current_sl == 2750.55

    # 2. At now_mono = 102.5 (2.5s since last modify, >= 2.0s): ALLOWED
    new_pos_ok, mod_res_ok, _ = pm.evaluate_trailing_and_scaleout(
        pos, tick, symbol_info, now_mono=102.5
    )
    assert mod_res_ok is not None and mod_res_ok.success
    mock_bridge.modify_position_sltp.assert_called_once_with(
        ticket=10001, symbol="XAUUSD", new_sl=2755.0, new_tp=2770.0
    )
    assert new_pos_ok.current_sl == 2755.0
    assert new_pos_ok.last_modify_time_mono == 102.5


def test_trailing_stop_advances_only_in_profit_direction() -> None:
    """Verify trailing stop strictly advances only in profit direction (pantang mundur)."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)
    symbol_info = DummySymbolInfo(trade_stops_level=50, point=0.01)

    # BUY position: current_sl = 2755.00
    pos_buy = _create_sample_buy_pos(
        be_sl_modified=True,
        partial_closed=True,
        current_sl=2755.0,
        last_modify_time_mono=50.0,
    )

    # Market retraces: bid = 2763.0 -> proposed trailing SL = 2763.0 - 10.0 = 2753.0 (< 2755.00)
    # Must NOT move backwards!
    tick_retrace = DummyTick(bid=2763.0, ask=2763.3)
    new_pos, mod_res, _ = pm.evaluate_trailing_and_scaleout(
        pos_buy, tick_retrace, symbol_info, now_mono=100.0
    )
    assert mod_res is None
    assert new_pos.current_sl == 2755.0
    mock_bridge.modify_position_sltp.assert_not_called()

    # SELL position: current_sl = 2745.00, open_price = 2750.00
    pos_sell = PositionState(
        ticket=20001,
        position_identifier=8888,
        symbol="XAUUSD",
        direction="SELL",
        open_price=2750.0,
        current_lot=0.02,
        initial_sl=2760.0,
        current_sl=2745.0,
        tp=2730.0,
        initial_r_pts=10.0,
        spread_at_entry_usd=0.35,
        be_sl_modified=True,
        partial_closed=True,
        last_modify_time_mono=50.0,
    )

    # Market retraces upward: ask = 2738.0 -> proposed trailing SL = 2738.0 + 10.0 = 2748.0 (> 2745.00)
    # Must NOT move backwards for SELL!
    tick_sell_retrace = DummyTick(bid=2737.7, ask=2738.0)
    new_pos_s, mod_res_s, _ = pm.evaluate_trailing_and_scaleout(
        pos_sell, tick_sell_retrace, symbol_info, now_mono=100.0
    )
    assert mod_res_s is None
    assert new_pos_s.current_sl == 2745.0
    mock_bridge.modify_position_sltp.assert_not_called()


def test_broker_bridge_modify_position_sltp_success() -> None:
    """Verify ExnessBrokerBridge.modify_position_sltp sends TRADE_ACTION_SLTP with lock."""
    client, mock_mt5 = _create_mock_client()
    mock_mt5.order_send.return_value = MagicMock(retcode=10009)

    bridge = ExnessBrokerBridge(client)
    res = bridge.modify_position_sltp(
        ticket=10001,
        symbol="XAUUSD",
        new_sl=2750.55,
        new_tp=2770.0,
    )

    assert res.success is True
    assert res.ticket == 10001
    assert res.new_sl == 2750.55
    assert res.new_tp == 2770.0

    mock_mt5.order_send.assert_called_once()
    payload = mock_mt5.order_send.call_args[0][0]
    assert payload["action"] == 6  # TRADE_ACTION_SLTP
    assert payload["position"] == 10001
    assert payload["symbol"] == "XAUUSD"
    assert payload["sl"] == 2750.55
    assert payload["tp"] == 2770.0


def test_broker_bridge_close_partial_position_and_reanchor() -> None:
    """Verify close_partial_position executes deal and refreshes ticket via POSITION_IDENTIFIER."""
    client, mock_mt5 = _create_mock_client()
    mock_mt5.symbol_info_tick.return_value = MagicMock(bid=2760.5, ask=2760.8)
    mock_mt5.order_send.return_value = MagicMock(retcode=10009, price=2760.5)

    pos_info = MagicMock()
    pos_info.identifier = 9999
    pos_info.ticket = 10002
    pos_info.volume = 0.02
    mock_mt5.positions_get.return_value = (pos_info,)

    bridge = ExnessBrokerBridge(client)
    res = bridge.close_partial_position(
        ticket=10001,
        position_identifier=9999,
        symbol="XAUUSD",
        direction="BUY",
        close_lot=0.02,
    )

    assert res.success is True
    assert res.closed_ticket == 10001
    assert res.new_ticket == 10002
    assert res.closed_lot == 0.02
    assert res.remaining_lot == 0.02
    assert res.executed_price == 2760.5

    mock_mt5.order_send.assert_called_once()
    payload = mock_mt5.order_send.call_args[0][0]
    assert payload["action"] == 1  # TRADE_ACTION_DEAL
    assert payload["position"] == 10001
    assert payload["volume"] == 0.02
    assert payload["type"] == 1  # ORDER_TYPE_SELL (opposite of BUY)
    mock_mt5.positions_get.assert_called_once_with(symbol="XAUUSD")
