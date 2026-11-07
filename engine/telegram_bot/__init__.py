"""Telegram bot alerting and control module."""

from engine.telegram_bot.interfaces import (
    AdminAuthenticator,
    DailyMetricsCollector,
    EphemeralStore,
    ExecutionEmergencyHandler,
    NonceManager,
    TwoStepController,
)
from engine.telegram_bot.templates import (
    DailyDashboardData,
    SignalAlertData,
    TemplateValidationError,
    format_daily_dashboard,
    format_signal_alert,
    validate_text_purity,
)
from engine.telegram_bot.types import (
    AdminCommand,
    AuthResult,
    CallbackNonce,
    EmergencyCloseResult,
    TwoStepAction,
    TwoStepState,
)

__all__ = [
    "AdminAuthenticator",
    "AdminCommand",
    "AuthResult",
    "CallbackNonce",
    "DailyDashboardData",
    "DailyMetricsCollector",
    "EmergencyCloseResult",
    "EphemeralStore",
    "ExecutionEmergencyHandler",
    "NonceManager",
    "SignalAlertData",
    "TemplateValidationError",
    "TwoStepAction",
    "TwoStepController",
    "TwoStepState",
    "format_daily_dashboard",
    "format_signal_alert",
    "validate_text_purity",
]
