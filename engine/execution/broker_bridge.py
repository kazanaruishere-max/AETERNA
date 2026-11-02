"""MetaTrader 5 Broker Execution Bridge.

Enforces mandatory server-side attached Stop Loss (SL) and Take Profit (TP)
on all orders sent to Exness terminal. Naked orders strictly prohibited.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from engine.ingestion.python.exness_client import ExnessClient

logger = logging.getLogger("aeterna.execution.broker_bridge")

OrderDirection = Literal["BUY", "SELL"]


class ExnessExecutionError(Exception):
    """Raised when Exness MT5 order execution cannot proceed."""


def validate_order_request(req: OrderRequest) -> None:
    """Validate order request parameters strictly against naked orders and invalid brackets."""
    if req.lot_size < 0.01:
        raise ValueError("Lot size must be at least 0.01.")
    if req.sl_price <= 0.0 or req.tp_price <= 0.0:
        raise ValueError("Server-side SL and TP are strictly mandatory. Naked orders are prohibited.")
    if req.direction == "BUY" and not (req.sl_price < req.entry_price < req.tp_price):
        raise ValueError("Invalid BUY price bracket: must satisfy SL < Entry < TP.")
    if req.direction == "SELL" and not (req.tp_price < req.entry_price < req.sl_price):
        raise ValueError("Invalid SELL price bracket: must satisfy TP < Entry < SL.")


@dataclass(frozen=True)
class OrderRequest:
    """Immutable order placement request."""

    symbol: str
    direction: OrderDirection
    lot_size: float
    entry_price: float
    sl_price: float
    tp_price: float
    deviation_points: int = 20
    magic_number: int = 202611
    comment: str = "AETERNA-M15-BREAKOUT"

    def __post_init__(self) -> None:
        validate_order_request(self)


@dataclass(frozen=True)
class OrderExecutionResult:
    """Immutable result of MT5 order placement attempt."""

    success: bool
    order_ticket: int | None
    executed_price: float | None
    sl_price: float | None
    tp_price: float | None
    error_code: int | None = None
    error_message: str | None = None


class ExnessBrokerBridge:
    """Bridge for executing orders on MetaTrader 5 with server-side attached SL/TP."""

    def __init__(self, client: ExnessClient) -> None:
        self.client = client

    @staticmethod
    def validate_order_request(request: OrderRequest) -> None:
        """Validate order request parameters."""
        validate_order_request(request)

    @staticmethod
    def resolve_filling_mode(mt5: Any, symbol_info: Any) -> int:
        """Determine dynamic filling mode favoring IOC with fallback to FOK.

        # ponytail: binary IOC/FOK selection; upgrade to RETURN flag if exchange execution is enabled.
        """
        order_ioc = getattr(mt5, "ORDER_FILLING_IOC", 1)
        order_fok = getattr(mt5, "ORDER_FILLING_FOK", 0)
        symbol_ioc = getattr(mt5, "SYMBOL_FILLING_IOC", 2)

        if symbol_info is not None:
            filling_mode = int(getattr(symbol_info, "filling_mode", 0))
            if bool(filling_mode & symbol_ioc):
                return int(order_ioc)
            return int(order_fok)
        return int(order_ioc)

    def send_market_order(self, request: OrderRequest) -> OrderExecutionResult:
        """Send a market order with mandatory server-side SL/TP attached."""
        self.validate_order_request(request)
        with self.client.lock:
            if not self.client.connected or self.client.mt5 is None:
                raise ExnessExecutionError("MT5 terminal is not connected.")

            mt5 = self.client.mt5
            tick = mt5.symbol_info_tick(request.symbol)
            if tick is None:
                raise ExnessExecutionError(f"Failed to fetch market tick for {request.symbol}")

            symbol_info = mt5.symbol_info(request.symbol) if hasattr(mt5, "symbol_info") else None
            filling_mode = self.resolve_filling_mode(mt5, symbol_info)

            if request.direction == "BUY":
                order_type = getattr(mt5, "ORDER_TYPE_BUY", 0)
                price = float(tick.ask)
            else:
                order_type = getattr(mt5, "ORDER_TYPE_SELL", 1)
                price = float(tick.bid)

            action_deal = getattr(mt5, "TRADE_ACTION_DEAL", 1)

            order_payload = {
                "action": action_deal,
                "symbol": request.symbol,
                "volume": request.lot_size,
                "type": order_type,
                "price": price,
                "sl": request.sl_price,
                "tp": request.tp_price,
                "deviation": request.deviation_points,
                "magic": request.magic_number,
                "comment": request.comment,
                "type_filling": filling_mode,
            }

            res = mt5.order_send(order_payload)

            if res is None:
                err = mt5.last_error() if hasattr(mt5, "last_error") else None
                logger.error("MT5 order_send returned None for %s: %s", request.symbol, err)
                return OrderExecutionResult(
                    success=False,
                    order_ticket=None,
                    executed_price=None,
                    sl_price=None,
                    tp_price=None,
                    error_code=-1,
                    error_message=f"MT5 order_send returned None: {err}",
                )

            retcode_done = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            if res.retcode == retcode_done:
                logger.info(
                    "Order executed successfully: ticket=%s, price=%s, sl=%s, tp=%s",
                    res.order,
                    res.price,
                    request.sl_price,
                    request.tp_price,
                )
                return OrderExecutionResult(
                    success=True,
                    order_ticket=int(res.order),
                    executed_price=float(res.price),
                    sl_price=request.sl_price,
                    tp_price=request.tp_price,
                )

            logger.warning(
                "Order rejected by broker: code=%s, comment=%s",
                res.retcode,
                getattr(res, "comment", ""),
            )
            return OrderExecutionResult(
                success=False,
                order_ticket=None,
                executed_price=None,
                sl_price=None,
                tp_price=None,
                error_code=int(res.retcode),
                error_message=str(getattr(res, "comment", "")),
            )
