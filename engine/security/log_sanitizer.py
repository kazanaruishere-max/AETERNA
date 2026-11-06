"""Log Sanitization Filter with Fast-Path Heuristic and Safe Traceback Sanitization.

Module: engine.security.log_sanitizer
Responsibility: Automatic redaction of sensitive credentials in logs and tracebacks.
Enforces:
- REQ-EXE-004: Multi-layer regex redaction of passwords, tokens, API keys, and account IDs.
- Ultra-Fast Heuristic Path (<0.001 ms) to prevent I/O mutex bottleneck during MT5 execution.
- Safe traceback sanitization via record.exc_text (never overwriting record.exc_info).
Owner: aeterna-security
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportUnnecessaryIsInstance=false

from __future__ import annotations

import logging
import re
from typing import Any

TRIGGER_TOKENS: tuple[str, ...] = (
    "pass",
    "pwd",
    "token",
    "secret",
    "login",
    "%3a",
    "%3d",
    "api_",
    "key",
    "bearer",
    "authorization",
    "bot",
    "telegram",
)

# 1. Telegram Bot Token (Raw format & URL-encoded %3A, handling preceding '/bot' or word boundary)
RE_TELEGRAM_TOKEN = re.compile(
    r"(?i)(?:\b|(?<=bot))\d{8,10}(?::|%3A)[a-zA-Z0-9_-]{30,50}\b"
)

# 2. Key-Value Standard & URL-Encoded
RE_KEY_VALUE_SECRETS = re.compile(
    r"(?i)\b((?:mt5[_-]?)?password|passwd|pwd|token|secret|api[_-]?key|client[_-]?secret)"
    r"(\s*[:=]|\s*%3D|\s*:\s*)\s*"
    r"(['\"]?)([^\s,'\"&\\}{]+)\3"
)

# 3. JSON Escaped / Serialized Credentials
RE_JSON_SECRETS = re.compile(
    r'(?i)(\\?["\'](?:(?:mt5[_-]?)?password|passwd|pwd|token|secret|api[_-]?key)\\?["\']\s*:\s*\\?["\'])([^\\"\']+)(\\?["\'])'
)

# 4. MetaTrader 5 Login Call Extraction
RE_MT5_LOGIN_CALL = re.compile(
    r"(?i)(login\s*\(\s*\d+\s*,\s*['\"])([^'\"]+)(['\"])"
)


def _needs_sanitization(text: str) -> bool:
    """Ultra-fast heuristic check. Returns False for >98% of standard market logs."""
    text_lower = text.lower()
    return any(tok in text_lower for tok in TRIGGER_TOKENS)


def sanitize_text(text: str) -> str:
    """Sanitize sensitive credentials from a text string using multi-layer regex.

    Args:
        text: Input string to redact.

    Returns:
        Redacted string with credentials replaced by ***REDACTED***.
    """
    if not isinstance(text, str) or not text:
        return text

    if not _needs_sanitization(text):
        return text

    # Layer 1: Telegram Bot Token
    res = RE_TELEGRAM_TOKEN.sub("***REDACTED_TELEGRAM_TOKEN***", text)

    # Layer 2: Key-Value Credentials
    res = RE_KEY_VALUE_SECRETS.sub(r"\1\2\3***REDACTED***\3", res)

    # Layer 3: JSON Escaped Credentials
    res = RE_JSON_SECRETS.sub(r"\1***REDACTED***\3", res)

    # Layer 4: MT5 Login Parameter
    res = RE_MT5_LOGIN_CALL.sub(r"\1***REDACTED***\3", res)

    return res


def _sanitize_arg(arg: Any) -> Any:
    """Sanitize individual argument passed to logger interpolation."""
    if isinstance(arg, str):
        return sanitize_text(arg)
    if isinstance(arg, dict):
        clean_dict: dict[Any, Any] = {}
        for k, v in arg.items():
            clean_k = sanitize_text(str(k)) if isinstance(k, str) else k
            clean_v = sanitize_text(str(v)) if isinstance(v, str) else v
            clean_dict[clean_k] = clean_v
        return clean_dict
    if isinstance(arg, (list, tuple)):
        clean_list = [_sanitize_arg(item) for item in arg]
        return tuple(clean_list) if isinstance(arg, tuple) else clean_list
    return arg


class LogSanitizer(logging.Filter):
    """Logging filter providing zero I/O bottleneck log sanitization and leak prevention."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize message, interpolation arguments, and traceback text.

        Enforces:
        - Never overwrites record.exc_info with string (prevents internal TypeError).
        - Safe traceback redaction stored in record.exc_text.
        """
        # 1. Sanitize message and arguments safely
        if record.args:
            # Safely merge arguments before redaction to prevent placeholder corruption
            try:
                formatted = record.getMessage()
            except (TypeError, ValueError, KeyError):
                formatted = str(record.msg)
            record.msg = sanitize_text(formatted)
            record.args = ()
        elif isinstance(record.msg, str):
            record.msg = sanitize_text(record.msg)

        # 3. Safe Traceback Sanitization via record.exc_text
        if record.exc_info:
            # Format exception traceback safely using standard formatter
            raw_traceback = self._formatter.formatException(record.exc_info)
            # Store redacted string in exc_text without corrupting exc_info tuple
            record.exc_text = sanitize_text(raw_traceback)

        return True
