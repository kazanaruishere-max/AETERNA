"""Unit tests for server-side trailing stop manager, serial queue, and ticket re-anchoring.

Covers:
1. Serial execution pipeline: SL modify to BE strictly precedes Partial Close.
2. Dynamic spread-aware stop level guard: max(trade_stops_level, current_spread) + 50 buffer points.
3. Absolute entry spread break-even offset: guarantees non-negative Net PnL.
4. Odd lot resolution: floor rounding to 0.01 lot resolution.
5. Minimum lot 0.01 handling: skip partial close safely.
6. Ticket re-anchoring post-partial close via POSITION_IDENTIFIER (match and no-match fallback).
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
    trade_stops_level: int = 50
    point: float = 0.01


DEFAULT_INFO = DummySymbolInfo()
DEFAULT_TICK = DummyTick(bid=2760.5, ask=2760.8)


def _create_mock_client() -> tuple[ExnessClient, MagicMock]:
    """Helper to instantiate ExnessClient with mocked MT5 backend."""
    mock_mt5 = MagicMock()
    mock_mt5.TRADE_ACTION_DEAL, mock_mt5.TRADE_ACTION_SLTP = 1, 6
    mock_mt5.ORDER_TYPE_BUY, mock_mt5.ORDER_TYPE_SELL = 0, 1
    mock_mt5.ORDER_FILLING_IOC, mock_mt5.ORDER_FILLING_FOK = 1, 0
    mock_mt5.SYMBOL_FILLING_IOC, mock_mt5.TRADE_RETCODE_DONE = 2, 10009
    client = ExnessClient(symbol="XAUUSD")
    client.connected, client.mt5 = True, mock_mt5
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
    """Trigger +1.0R: verify modify_position_sltp precedes close_partial_position."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04)

    # 1. Success path
    call_log: list[str] = []

    def _mock_mod(*_a: object, **_k: object) -> ModifyResult:
        call_log.append("modify")
        return ModifyResult(success=True, ticket=10001, new_sl=2750.55, new_tp=2770.0)

    def _mock_close(*_a: object, **_k: object) -> PartialCloseResult:
        call_log.append("close")
        return PartialCloseResult(True, 10001, 10002, 0.02, 0.02, 2760.5)

    mock_bridge.modify_position_sltp.side_effect = _mock_mod
    mock_bridge.close_partial_position.side_effect = _mock_close
    new_pos, mod_res, close_res = pm.evaluate_trailing_and_scaleout(
        pos, DEFAULT_TICK, DEFAULT_INFO, now_mono=10.0
    )
    assert call_log == ["modify", "close"]
    assert mod_res and mod_res.success and close_res and close_res.success
    assert new_pos.be_sl_modified and new_pos.partial_closed and new_pos.ticket == 10002

    # 2. Modify failure path: partial close must NOT be called
    mock_bridge.modify_position_sltp.side_effect = None
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        success=False, ticket=10001, new_sl=2750.55, new_tp=2770.0, error_code=10016
    )
    mock_bridge.close_partial_position.reset_mock()

    new_pos_f, mod_f, close_f = pm.evaluate_trailing_and_scaleout(
        pos, DEFAULT_TICK, DEFAULT_INFO, now_mono=10.0
    )
    assert mod_f is not None and not mod_f.success
    assert close_f is None
    mock_bridge.close_partial_position.assert_not_called()
    assert not new_pos_f.be_sl_modified and not new_pos_f.partial_closed
    assert new_pos_f.last_modify_time_mono == 10.0


def test_dynamic_spread_aware_stop_level_guard() -> None:
    """Verify stops_level=300 and spread=450 uses max(300, 450) + 50 = 500 pts."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)
    symbol_info = DummySymbolInfo(trade_stops_level=300, point=0.01)
    tick = DummyTick(bid=2760.0, ask=2764.5)  # spread 4.50 = 450 pts

    min_stop_usd = pm.calculate_min_stop_distance_usd(tick, symbol_info)
    assert math.isclose(min_stop_usd, 5.0, abs_tol=1e-6)

    # BE target SL = 2750.0 + 5.80 + 0.20 = 2756.00 (distance to bid = 4.0 USD < 5.0 USD) -> HOLD
    pos_tight = PositionState(
        10001, 9999, "XAUUSD", "BUY", 2750.0, 0.04, 2740.0, 2740.0, 2780.0, 10.0, 5.80
    )
    new_pos, mod_res, close_res = pm.evaluate_trailing_and_scaleout(
        pos_tight, tick, symbol_info, now_mono=10.0
    )
    assert mod_res is None and close_res is None
    mock_bridge.modify_position_sltp.assert_not_called()
    assert not new_pos.be_sl_modified

    # When market advances so distance >= 5.0 USD (bid 2762.0 -> distance 6.0 USD)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        True, 10001, 2756.0, 2780.0
    )
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        True, 10001, 10002, 0.02, 0.02, 2762.0
    )
    tick_wide = DummyTick(bid=2762.0, ask=2766.5)
    _, mod_ok, _ = pm.evaluate_trailing_and_scaleout(
        pos_tight, tick_wide, symbol_info, now_mono=10.0
    )
    assert (
        mod_ok and mod_ok.success and mock_bridge.modify_position_sltp.call_count == 1
    )


def test_break_even_offset_guarantees_non_negative_net_pnl() -> None:
    """Verify Entry 2750.00, entry spread 0.35, cushion 0.20 yields Net PnL >= 0.0."""
    pm = PositionManager(
        bridge=MagicMock(spec=ExnessBrokerBridge), slippage_cushion_usd=0.20
    )

    # BUY position
    pos_buy = _create_sample_buy_pos()
    sl_be_buy = pm.calculate_break_even_sl(pos_buy)
    assert sl_be_buy == 2750.55
    net_pnl_buy = (sl_be_buy - pos_buy.open_price) - pos_buy.spread_at_entry_usd
    assert math.isclose(net_pnl_buy, 0.20, abs_tol=1e-6) and net_pnl_buy >= 0.0

    # SELL position
    pos_sell = PositionState(
        20001, 8888, "XAUUSD", "SELL", 2750.0, 0.04, 2760.0, 2760.0, 2730.0, 10.0, 0.35
    )
    sl_be_sell = pm.calculate_break_even_sl(pos_sell)
    assert sl_be_sell == 2749.45
    net_pnl_sell = (pos_sell.open_price - sl_be_sell) - pos_sell.spread_at_entry_usd
    assert math.isclose(net_pnl_sell, 0.20, abs_tol=1e-6) and net_pnl_sell >= 0.0


def test_partial_close_lot_resolution_odd_numbers() -> None:
    """Verify odd lot resolution: 0.03 -> Close 0.01, Rem 0.02; 0.05 -> Close 0.02, Rem 0.03."""
    close_03, rem_03 = PositionManager.resolve_partial_close_lot(0.03)
    assert close_03 == 0.01 and rem_03 == 0.02 and round(close_03 + rem_03, 2) == 0.03

    close_05, rem_05 = PositionManager.resolve_partial_close_lot(0.05)
    assert close_05 == 0.02 and rem_05 == 0.03 and round(close_05 + rem_05, 2) == 0.05

    close_10, rem_10 = PositionManager.resolve_partial_close_lot(0.10)
    assert close_10 == 0.05 and rem_10 == 0.05

    close_02, rem_02 = PositionManager.resolve_partial_close_lot(0.02)
    assert close_02 == 0.01 and rem_02 == 0.01


def test_partial_close_skipped_for_minimum_lot_0_01() -> None:
    """Verify lot 0.01 at +1.0R skips partial close deal while safely advancing SL to Break-Even."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        True, 10001, 2750.55, 2770.0
    )

    pm = PositionManager(bridge=mock_bridge)
    pos_min = _create_sample_buy_pos(current_lot=0.01)

    new_pos, mod_res, close_res = pm.evaluate_trailing_and_scaleout(
        pos_min, DEFAULT_TICK, DEFAULT_INFO, now_mono=10.0
    )
    assert mod_res and mod_res.success and close_res is None
    mock_bridge.close_partial_position.assert_not_called()
    assert new_pos.be_sl_modified and new_pos.current_sl == 2750.55
    assert new_pos.current_lot == 0.01 and not new_pos.partial_closed


def test_ticket_re_anchoring_post_partial_close() -> None:
    """Verify ticket changes from #10001 to #10002 post-partial close via POSITION_IDENTIFIER 9999."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        True, 10001, 2750.55, 2770.0
    )
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        True, 10001, 10002, 0.02, 0.02, 2760.5
    )

    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04)

    new_pos, _, close_res = pm.evaluate_trailing_and_scaleout(
        pos, DEFAULT_TICK, DEFAULT_INFO, now_mono=10.0
    )
    assert new_pos.ticket == 10002 and new_pos.position_identifier == 9999
    assert new_pos.current_lot == 0.02 and new_pos.partial_closed
    assert close_res is not None and close_res.new_ticket == 10002


def test_cooldown_anti_spam() -> None:
    """Verify modify request within < 2.0s cooldown interval is skipped."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        True, 10001, 2755.0, 2770.0
    )

    pm = PositionManager(bridge=mock_bridge, cooldown_seconds=2.0)
    pos = _create_sample_buy_pos(
        be_sl_modified=True,
        partial_closed=True,
        current_sl=2750.55,
        last_modify_time_mono=100.0,
    )
    tick = DummyTick(bid=2765.0, ask=2765.3)

    # 1. At now_mono = 101.5 (1.5s < 2.0s): MUST SKIP
    new_pos_cool, mod_cool, _ = pm.evaluate_trailing_and_scaleout(
        pos, tick, DEFAULT_INFO, now_mono=101.5
    )
    assert mod_cool is None and new_pos_cool.current_sl == 2750.55
    mock_bridge.modify_position_sltp.assert_not_called()

    # 2. At now_mono = 102.5 (2.5s >= 2.0s): ALLOWED
    new_pos_ok, mod_ok, _ = pm.evaluate_trailing_and_scaleout(
        pos, tick, DEFAULT_INFO, now_mono=102.5
    )
    assert mod_ok and mod_ok.success and new_pos_ok.current_sl == 2755.0
    mock_bridge.modify_position_sltp.assert_called_once_with(
        ticket=10001, symbol="XAUUSD", new_sl=2755.0, new_tp=2770.0
    )


def test_trailing_stop_advances_only_in_profit_direction() -> None:
    """Verify trailing stop strictly advances only in profit direction (pantang mundur)."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)

    # BUY position: current_sl = 2755.00, retrace to bid 2763.0 (proposed 2753.0 < 2755.0) -> SKIP
    pos_buy = _create_sample_buy_pos(
        be_sl_modified=True,
        partial_closed=True,
        current_sl=2755.0,
        last_modify_time_mono=50.0,
    )
    tick_retrace = DummyTick(bid=2763.0, ask=2763.3)
    new_pos, mod_res, _ = pm.evaluate_trailing_and_scaleout(
        pos_buy, tick_retrace, DEFAULT_INFO, now_mono=100.0
    )
    assert mod_res is None and new_pos.current_sl == 2755.0
    mock_bridge.modify_position_sltp.assert_not_called()

    # SELL position: current_sl = 2745.00, retrace to ask 2738.0 (proposed 2748.0 > 2745.0) -> SKIP
    pos_sell = PositionState(
        20001,
        8888,
        "XAUUSD",
        "SELL",
        2750.0,
        0.02,
        2760.0,
        2745.0,
        2730.0,
        10.0,
        0.35,
        True,
        True,
        50.0,
    )
    tick_sell_retrace = DummyTick(bid=2737.7, ask=2738.0)
    new_pos_s, mod_s, _ = pm.evaluate_trailing_and_scaleout(
        pos_sell, tick_sell_retrace, DEFAULT_INFO, now_mono=100.0
    )
    assert mod_s is None and new_pos_s.current_sl == 2745.0
    mock_bridge.modify_position_sltp.assert_not_called()


def test_broker_bridge_modify_position_sltp_success() -> None:
    """Verify ExnessBrokerBridge.modify_position_sltp sends TRADE_ACTION_SLTP with lock."""
    client, mock_mt5 = _create_mock_client()
    mock_mt5.order_send.return_value = MagicMock(retcode=10009)

    bridge = ExnessBrokerBridge(client)
    res = bridge.modify_position_sltp(10001, "XAUUSD", 2750.55, 2770.0)
    assert (
        res.success
        and res.ticket == 10001
        and res.new_sl == 2750.55
        and res.new_tp == 2770.0
    )

    mock_mt5.order_send.assert_called_once()
    payload = mock_mt5.order_send.call_args[0][0]
    assert payload["action"] == 6 and payload["position"] == 10001  # TRADE_ACTION_SLTP
    assert payload["sl"] == 2750.55 and payload["tp"] == 2770.0


def test_broker_bridge_close_partial_position_and_reanchor() -> None:
    """Verify close_partial_position executes deal and refreshes ticket via POSITION_IDENTIFIER."""
    client, mock_mt5 = _create_mock_client()
    mock_mt5.symbol_info_tick.return_value = MagicMock(bid=2760.5, ask=2760.8)
    mock_mt5.order_send.return_value = MagicMock(retcode=10009, price=2760.5)

    pos_info = MagicMock()
    pos_info.identifier, pos_info.ticket, pos_info.volume = 9999, 10002, 0.02
    mock_mt5.positions_get.return_value = (pos_info,)

    bridge = ExnessBrokerBridge(client)
    res = bridge.close_partial_position(10001, 9999, "XAUUSD", "BUY", 0.02)
    assert res.success and res.closed_ticket == 10001 and res.new_ticket == 10002
    assert (
        res.closed_lot == 0.02
        and res.remaining_lot == 0.02
        and res.executed_price == 2760.5
    )

    mock_mt5.order_send.assert_called_once()
    payload = mock_mt5.order_send.call_args[0][0]
    assert (
        payload["action"] == 1 and payload["position"] == 10001 and payload["type"] == 1
    )  # SELL
    assert payload["deviation"] == 20
    mock_mt5.positions_get.assert_called_once_with(symbol="XAUUSD")

    # Cover custom deviation forwarding
    mock_mt5.order_send.reset_mock()
    bridge.close_partial_position(10001, 9999, "XAUUSD", "BUY", 0.02, deviation=45)
    assert mock_mt5.order_send.call_args[0][0]["deviation"] == 45

    # Cover no-match fallback branch
    mock_mt5.positions_get.return_value = []
    res_nomatch = bridge.close_partial_position(10001, 9999, "XAUUSD", "BUY", 0.02)
    assert res_nomatch.success and res_nomatch.new_ticket == 10001


def test_be_trigger_r_configurable() -> None:
    """ADR-017: Verify configurable be_trigger_r (e.g. 1.5R) suppresses premature trigger at 1.0R."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    # When be_trigger_r = 1.5, pos open=2750, r=10 -> target = 2765.0
    pm_15 = PositionManager(bridge=mock_bridge, be_trigger_r=1.5)
    pos = _create_sample_buy_pos(current_lot=0.04)

    # At bid=2760.5 (1.05R): should NOT trigger BE modify
    new_pos, mod_res, close_res = pm_15.evaluate_trailing_and_scaleout(
        pos, DEFAULT_TICK, DEFAULT_INFO, now_mono=10.0
    )
    assert not new_pos.be_sl_modified
    assert mod_res is None
    assert close_res is None
    mock_bridge.modify_position_sltp.assert_not_called()

    # At bid=2765.5 (1.55R): should trigger BE modify
    tick_15r = DummyTick(bid=2765.5, ask=2765.8)
    mock_bridge.modify_position_sltp.return_value = ModifyResult(
        success=True, ticket=10001, new_sl=2750.55, new_tp=2770.0
    )
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        True, 10001, 10002, 0.02, 0.02, 2765.5
    )
    new_pos2, mod_res2, _close_res2 = pm_15.evaluate_trailing_and_scaleout(
        pos, tick_15r, DEFAULT_INFO, now_mono=10.0
    )
    assert new_pos2.be_sl_modified
    assert mod_res2 and mod_res2.success


def test_lapis_4_and_5_invalidation_rules() -> None:
    """Verify static helper methods for Lapis 4 (time) and Lapis 5 (rollover & regime)."""
    # Lapis 4: Time invalidation requires >= 8 bars M15 (invariant-cheatsheet §4.4)
    assert not PositionManager.is_time_invalidated(7, 0.1)
    assert not PositionManager.is_time_invalidated(7, 0.2)
    assert PositionManager.is_time_invalidated(8, 0.2) is True
    assert PositionManager.is_time_invalidated(7, 0.2) is False
    assert PositionManager.is_time_invalidated(8, 0.5) is True
    assert PositionManager.is_time_invalidated(8, -0.5) is True
    assert PositionManager.is_time_invalidated(12, 0.0) is True

    # Lapis 5: Rollover window (20:44+ UTC and 21:44+ UTC)
    from datetime import UTC, datetime

    dt_normal = datetime(2024, 7, 15, 14, 0, tzinfo=UTC)
    dt_summer_rollover = datetime(2024, 7, 15, 20, 45, tzinfo=UTC)
    dt_winter_rollover = datetime(2024, 1, 15, 21, 50, tzinfo=UTC)
    assert not PositionManager.is_rollover_window(dt_normal)
    assert PositionManager.is_rollover_window(dt_summer_rollover)
    assert PositionManager.is_rollover_window(dt_winter_rollover)

    # Lapis 5: Regime invalidation
    assert PositionManager.is_regime_invalidated("BUY", "BEARISH_TRENDING")
    assert not PositionManager.is_regime_invalidated("BUY", "BULLISH_TRENDING")
    assert PositionManager.is_regime_invalidated("SELL", "BULLISH_TRENDING")
    assert not PositionManager.is_regime_invalidated("SELL", "BEARISH_TRENDING")


def test_position_state_with_elapsed_bar() -> None:
    """Verify PositionState.with_elapsed_bar immutably advances elapsed_bars_m15."""
    pos = _create_sample_buy_pos(current_lot=0.04)
    assert pos.elapsed_bars_m15 == 0

    pos_1 = pos.with_elapsed_bar(1)
    assert pos_1.elapsed_bars_m15 == 1
    assert pos.elapsed_bars_m15 == 0  # Immutability check

    pos_4 = pos_1.with_elapsed_bar(3)
    assert pos_4.elapsed_bars_m15 == 4


def test_position_manager_on_bar_closed() -> None:
    """Verify on_bar_closed advances bar counter and liquidates at 8 bars."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=True,
        closed_ticket=10001,
        new_ticket=None,
        closed_lot=0.04,
        remaining_lot=0.0,
        executed_price=2755.0,
    )
    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04)

    # 1 to 7 bars: counter increments, no liquidation
    for bar in range(1, 8):
        pos, close_res = pm.on_bar_closed(pos)
        assert pos.elapsed_bars_m15 == bar
        assert close_res is None
    mock_bridge.close_partial_position.assert_not_called()

    # 8th bar: liquidation triggers
    pos, close_res = pm.on_bar_closed(pos)
    assert pos.elapsed_bars_m15 == 8
    assert close_res is not None and close_res.success is True
    assert pos.current_lot == 0.0
    mock_bridge.close_partial_position.assert_called_once()


def test_evaluate_time_invalidation_active_evaluation_path() -> None:
    """Verify counter advances naturally in real evaluation path to 8 bars and triggers liquidation."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=True,
        closed_ticket=10001,
        new_ticket=None,
        closed_lot=0.04,
        remaining_lot=0.0,
        executed_price=2755.0,
    )
    pm = PositionManager(bridge=mock_bridge)

    pos = _create_sample_buy_pos(current_lot=0.04)
    assert pos.elapsed_bars_m15 == 0
    tick = DummyTick(bid=2751.0, ask=2751.3)  # Floating < 1.0R

    # 1. Real evaluation path over 7 M15 closed bars: counter increments naturally, must NOT liquidate
    for bar_idx in range(1, 8):
        pos, _mod_res, close_res = pm.evaluate_trailing_and_scaleout(
            pos, tick, DEFAULT_INFO, now_mono=10.0 + bar_idx, bar_closed=True
        )
        assert pos.elapsed_bars_m15 == bar_idx
        assert close_res is None
    mock_bridge.close_partial_position.assert_not_called()

    # 2. 8th M15 bar closes in the real evaluation path: MUST liquidate via bridge
    pos, _mod_res_8, close_res_8 = pm.evaluate_trailing_and_scaleout(
        pos, tick, DEFAULT_INFO, now_mono=18.0, bar_closed=True
    )
    assert pos.elapsed_bars_m15 == 8
    assert close_res_8 is not None
    assert close_res_8.success is True
    assert pos.current_lot == 0.0
    mock_bridge.close_partial_position.assert_called_once_with(
        ticket=10001,
        position_identifier=9999,
        symbol="XAUUSD",
        direction="BUY",
        close_lot=0.04,
    )


def test_bar_closed_increments_counter_and_bar_closed_false_does_not() -> None:
    """Verify bar_closed=True increments elapsed_bars_m15 while bar_closed=False does not."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04)
    tick = DummyTick(bid=2751.0, ask=2751.3)

    assert pos.elapsed_bars_m15 == 0

    # bar_closed=False (tick evaluation): counter must NOT increment
    pos_tick, _, _ = pm.evaluate_trailing_and_scaleout(
        pos, tick, DEFAULT_INFO, now_mono=1.0, bar_closed=False
    )
    assert pos_tick.elapsed_bars_m15 == 0

    # bar_closed=True (closed M15 bar): counter increments by 1
    pos_bar1, _, _ = pm.evaluate_trailing_and_scaleout(
        pos_tick, tick, DEFAULT_INFO, now_mono=2.0, bar_closed=True
    )
    assert pos_bar1.elapsed_bars_m15 == 1

    # Another tick: counter stays 1
    pos_tick2, _, _ = pm.evaluate_trailing_and_scaleout(
        pos_bar1, tick, DEFAULT_INFO, now_mono=3.0, bar_closed=False
    )
    assert pos_tick2.elapsed_bars_m15 == 1

    # Second closed bar: counter increments to 2
    pos_bar2, _, _ = pm.evaluate_trailing_and_scaleout(
        pos_tick2, tick, DEFAULT_INFO, now_mono=4.0, bar_closed=True
    )
    assert pos_bar2.elapsed_bars_m15 == 2
    mock_bridge.close_partial_position.assert_not_called()


def test_deterministic_time_invalidation_bar_7_false_bar_8_true() -> None:
    """Verify deterministic fact: bar 7 is False (no invalidation) and bar 8 is True (liquidation)."""
    # 1. Direct predicate assertion
    assert PositionManager.is_time_invalidated(7) is False
    assert PositionManager.is_time_invalidated(8) is True

    # 2. End-to-end evaluation assertion
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    mock_bridge.close_partial_position.return_value = PartialCloseResult(
        success=True,
        closed_ticket=10001,
        new_ticket=None,
        closed_lot=0.04,
        remaining_lot=0.0,
        executed_price=2751.0,
    )
    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04).with_elapsed_bar(6)
    assert pos.elapsed_bars_m15 == 6
    tick = DummyTick(bid=2751.0, ask=2751.3)

    # Bar 7: bar_closed=True -> 7 bars -> False (no liquidation)
    pos_7, _, close_7 = pm.evaluate_trailing_and_scaleout(
        pos, tick, DEFAULT_INFO, now_mono=10.0, bar_closed=True
    )
    assert pos_7.elapsed_bars_m15 == 7
    assert close_7 is None
    assert PositionManager.is_time_invalidated(pos_7.elapsed_bars_m15) is False
    mock_bridge.close_partial_position.assert_not_called()

    # Bar 8: bar_closed=True -> 8 bars -> True (liquidation triggered)
    pos_8, _, close_8 = pm.evaluate_trailing_and_scaleout(
        pos_7, tick, DEFAULT_INFO, now_mono=11.0, bar_closed=True
    )
    assert pos_8.elapsed_bars_m15 == 8
    assert PositionManager.is_time_invalidated(pos_8.elapsed_bars_m15) is True
    assert close_8 is not None and close_8.success is True
    assert pos_8.current_lot == 0.0
    mock_bridge.close_partial_position.assert_called_once_with(
        ticket=10001,
        position_identifier=9999,
        symbol="XAUUSD",
        direction="BUY",
        close_lot=0.04,
    )


def test_position_manager_tracking_and_no_double_increment() -> None:
    """Verify evaluate_bar_closed advances counter by exactly 1 without double increment."""
    mock_bridge = MagicMock(spec=ExnessBrokerBridge)
    pm = PositionManager(bridge=mock_bridge)
    pos = _create_sample_buy_pos(current_lot=0.04)
    tick = DummyTick(bid=2751.0, ask=2751.3)

    pm.track_position(pos)
    assert len(pm.get_active_positions()) == 1

    # First closed bar
    results1 = pm.evaluate_bar_closed(tick, DEFAULT_INFO)
    assert len(results1) == 1
    new_pos1, _, _ = results1[0]
    assert new_pos1.elapsed_bars_m15 == 1
    assert pm.get_active_positions()[0].elapsed_bars_m15 == 1

    # Second closed bar: exactly 1 increment (no double increment)
    results2 = pm.evaluate_bar_closed(tick, DEFAULT_INFO)
    assert len(results2) == 1
    new_pos2, _, _ = results2[0]
    assert new_pos2.elapsed_bars_m15 == 2
    assert pm.get_active_positions()[0].elapsed_bars_m15 == 2

    # Untrack position
    untracked = pm.untrack_position(pos.ticket)
    assert untracked is not None
    assert len(pm.get_active_positions()) == 0
