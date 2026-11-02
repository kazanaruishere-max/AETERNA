"""Unit and mock tests for Exness broker execution bridge.

Validates:
1. REQ-EXE-001: Mandatory attached server-side SL and TP on all orders (0 naked orders).
2. Proper construction of MT5 order_send payload for BUY and SELL orders.
3. Fail-fast rejection of naked orders, inverted SL/TP brackets, and invalid lot size.
4. Graceful handling of broker rejections (retcode != 10009) and connection issues.
5. Dynamic filling mode detection (IOC favored over FOK).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engine.execution.broker_bridge import (
    ExnessBrokerBridge,
    ExnessExecutionError,
    OrderRequest,
)
from engine.ingestion.python.exness_client import ExnessClient


def _create_mock_client() -> tuple[ExnessClient, MagicMock]:
    """Helper to instantiate ExnessClient with mocked MT5 backend."""
    mock_mt5 = MagicMock()
    mock_mt5.TRADE_ACTION_DEAL = 1
    mock_mt5.ORDER_TYPE_BUY = 0
    mock_mt5.ORDER_TYPE_SELL = 1
    mock_mt5.ORDER_FILLING_FOK = 0
    mock_mt5.ORDER_FILLING_IOC = 1
    mock_mt5.SYMBOL_FILLING_FOK = 1
    mock_mt5.SYMBOL_FILLING_IOC = 2
    mock_mt5.TRADE_RETCODE_DONE = 10009

    client = ExnessClient(symbol="XAUUSD")
    client.connected = True
    client.mt5 = mock_mt5
    return client, mock_mt5


def test_order_send_with_attached_sl_tp_buy() -> None:
    """Verify BUY order attaches SL/TP to order_send payload and handles success."""
    client, mock_mt5 = _create_mock_client()

    tick = MagicMock()
    tick.ask = 2750.50
    tick.bid = 2750.20
    mock_mt5.symbol_info_tick.return_value = tick

    sym_info = MagicMock()
    sym_info.filling_mode = 2  # SYMBOL_FILLING_IOC
    mock_mt5.symbol_info.return_value = sym_info

    send_res = MagicMock()
    send_res.retcode = 10009
    send_res.order = 12345678
    send_res.price = 2750.50
    send_res.comment = "Request executed"
    mock_mt5.order_send.return_value = send_res

    bridge = ExnessBrokerBridge(client)
    req = OrderRequest(
        symbol="XAUUSD",
        direction="BUY",
        lot_size=0.10,
        entry_price=2750.50,
        sl_price=2740.00,
        tp_price=2770.00,
    )

    result = bridge.send_market_order(req)

    assert result.success is True
    assert result.order_ticket == 12345678
    assert result.executed_price == 2750.50
    assert result.sl_price == 2740.00
    assert result.tp_price == 2770.00
    assert result.error_code is None
    assert result.error_message is None

    mock_mt5.order_send.assert_called_once()
    payload = mock_mt5.order_send.call_args[0][0]
    assert payload["action"] == 1
    assert payload["symbol"] == "XAUUSD"
    assert payload["volume"] == 0.10
    assert payload["type"] == 0  # BUY
    assert payload["price"] == 2750.50
    assert payload["sl"] == 2740.00
    assert payload["tp"] == 2770.00
    assert payload["type_filling"] == 1  # ORDER_FILLING_IOC
    assert payload["deviation"] == 20
    assert payload["magic"] == 202611
    assert payload["comment"] == "AETERNA-M15-BREAKOUT"


def test_order_send_with_attached_sl_tp_sell() -> None:
    """Verify SELL order attaches SL/TP to order_send payload and handles success."""
    client, mock_mt5 = _create_mock_client()

    tick = MagicMock()
    tick.ask = 2750.50
    tick.bid = 2750.20
    mock_mt5.symbol_info_tick.return_value = tick

    sym_info = MagicMock()
    sym_info.filling_mode = 1  # Only FOK supported
    mock_mt5.symbol_info.return_value = sym_info

    send_res = MagicMock()
    send_res.retcode = 10009
    send_res.order = 87654321
    send_res.price = 2750.20
    send_res.comment = "Request executed"
    mock_mt5.order_send.return_value = send_res

    bridge = ExnessBrokerBridge(client)
    req = OrderRequest(
        symbol="XAUUSD",
        direction="SELL",
        lot_size=0.05,
        entry_price=2750.20,
        sl_price=2760.00,
        tp_price=2730.00,
    )

    result = bridge.send_market_order(req)

    assert result.success is True
    assert result.order_ticket == 87654321
    assert result.executed_price == 2750.20
    assert result.sl_price == 2760.00
    assert result.tp_price == 2730.00

    payload = mock_mt5.order_send.call_args[0][0]
    assert payload["type"] == 1  # SELL
    assert payload["price"] == 2750.20
    assert payload["sl"] == 2760.00
    assert payload["tp"] == 2730.00
    assert payload["type_filling"] == 0  # ORDER_FILLING_FOK


def test_naked_order_strictly_rejected() -> None:
    """Verify request with zero or negative SL/TP strictly raises ValueError."""
    with pytest.raises(
        ValueError,
        match="Server-side SL and TP are strictly mandatory. Naked orders are prohibited.",
    ):
        OrderRequest(
            symbol="XAUUSD",
            direction="BUY",
            lot_size=0.01,
            entry_price=2750.0,
            sl_price=0.0,
            tp_price=2770.0,
        )

    with pytest.raises(
        ValueError,
        match="Server-side SL and TP are strictly mandatory. Naked orders are prohibited.",
    ):
        OrderRequest(
            symbol="XAUUSD",
            direction="BUY",
            lot_size=0.01,
            entry_price=2750.0,
            sl_price=2740.0,
            tp_price=0.0,
        )

    with pytest.raises(
        ValueError,
        match="Server-side SL and TP are strictly mandatory. Naked orders are prohibited.",
    ):
        OrderRequest(
            symbol="XAUUSD",
            direction="SELL",
            lot_size=0.01,
            entry_price=2750.0,
            sl_price=-10.0,
            tp_price=2730.0,
        )


def test_inverted_sl_tp_bracket_rejected() -> None:
    """Verify inverted price brackets are fail-fast rejected."""
    # BUY: SL must be < Entry < TP
    with pytest.raises(ValueError, match="Invalid BUY price bracket: must satisfy SL < Entry < TP."):
        OrderRequest(
            symbol="XAUUSD",
            direction="BUY",
            lot_size=0.01,
            entry_price=2750.0,
            sl_price=2755.0,  # SL > Entry
            tp_price=2770.0,
        )

    with pytest.raises(ValueError, match="Invalid BUY price bracket: must satisfy SL < Entry < TP."):
        OrderRequest(
            symbol="XAUUSD",
            direction="BUY",
            lot_size=0.01,
            entry_price=2750.0,
            sl_price=2740.0,
            tp_price=2745.0,  # TP < Entry
        )

    # SELL: TP must be < Entry < SL
    with pytest.raises(ValueError, match="Invalid SELL price bracket: must satisfy TP < Entry < SL."):
        OrderRequest(
            symbol="XAUUSD",
            direction="SELL",
            lot_size=0.01,
            entry_price=2750.0,
            sl_price=2745.0,  # SL < Entry
            tp_price=2730.0,
        )

    with pytest.raises(ValueError, match="Invalid SELL price bracket: must satisfy TP < Entry < SL."):
        OrderRequest(
            symbol="XAUUSD",
            direction="SELL",
            lot_size=0.01,
            entry_price=2750.0,
            sl_price=2760.0,
            tp_price=2755.0,  # TP > Entry
        )


def test_broker_rejection_handled_gracefully() -> None:
    """Verify non-10009 retcode returns success=False without silent errors."""
    client, mock_mt5 = _create_mock_client()

    tick = MagicMock()
    tick.ask = 2750.50
    tick.bid = 2750.20
    mock_mt5.symbol_info_tick.return_value = tick

    send_res = MagicMock()
    send_res.retcode = 10013  # TRADE_RETCODE_INVALID_VOLUME
    send_res.comment = "Invalid volume"
    mock_mt5.order_send.return_value = send_res

    bridge = ExnessBrokerBridge(client)
    req = OrderRequest(
        symbol="XAUUSD",
        direction="BUY",
        lot_size=0.01,
        entry_price=2750.50,
        sl_price=2740.00,
        tp_price=2770.00,
    )

    result = bridge.send_market_order(req)

    assert result.success is False
    assert result.order_ticket is None
    assert result.executed_price is None
    assert result.sl_price is None
    assert result.tp_price is None
    assert result.error_code == 10013
    assert result.error_message == "Invalid volume"


def test_lot_size_minimum_rejection() -> None:
    """Verify lot size below 0.01 is strictly rejected."""
    with pytest.raises(ValueError, match="Lot size must be at least 0.01."):
        OrderRequest(
            symbol="XAUUSD",
            direction="BUY",
            lot_size=0.005,
            entry_price=2750.0,
            sl_price=2740.0,
            tp_price=2770.0,
        )


def test_unconnected_client_raises() -> None:
    """Verify sending order via unconnected client raises ExnessExecutionError."""
    client = ExnessClient(symbol="XAUUSD")
    bridge = ExnessBrokerBridge(client)
    req = OrderRequest(
        symbol="XAUUSD",
        direction="BUY",
        lot_size=0.01,
        entry_price=2750.0,
        sl_price=2740.0,
        tp_price=2770.0,
    )

    with pytest.raises(ExnessExecutionError, match="MT5 terminal is not connected."):
        bridge.send_market_order(req)


def test_order_send_returned_none_handled_gracefully() -> None:
    """Verify order_send returning None (connection failure) returns success=False."""
    client, mock_mt5 = _create_mock_client()

    tick = MagicMock()
    tick.ask = 2750.50
    tick.bid = 2750.20
    mock_mt5.symbol_info_tick.return_value = tick
    mock_mt5.order_send.return_value = None
    mock_mt5.last_error.return_value = (-10004, "Terminal closed")

    bridge = ExnessBrokerBridge(client)
    req = OrderRequest(
        symbol="XAUUSD",
        direction="BUY",
        lot_size=0.01,
        entry_price=2750.50,
        sl_price=2740.00,
        tp_price=2770.00,
    )

    result = bridge.send_market_order(req)

    assert result.success is False
    assert result.error_code == -1
    assert "MT5 order_send returned None" in (result.error_message or "")
