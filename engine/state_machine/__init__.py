"""News and volatility state machine module.

Exports core state gating primitives, EWMA spread filters, and news calendar windows.
"""

from engine.state_machine.news_filter import NewsCalendarFilter, convert_eastern_to_utc
from engine.state_machine.spread_filter import SpreadFilter
from engine.state_machine.state_machine import NewsStateMachine, SpreadProvider

__all__ = [
    "NewsCalendarFilter",
    "NewsStateMachine",
    "SpreadFilter",
    "SpreadProvider",
    "convert_eastern_to_utc",
]
