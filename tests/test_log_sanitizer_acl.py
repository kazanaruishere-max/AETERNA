"""Deterministic unit and security tests for Log Sanitizer and Windows ACL Lockdown.

Validates:
1. REQ-EXE-004: Multi-layer regex redaction and ultra-fast heuristic check.
2. Safe traceback sanitization via record.exc_text (never corrupting record.exc_info).
3. REQ-EXE-005: Native Win32 identity retrieval, whitelist regex guard, and shell-free icacls lockdown.
4. Non-Windows platform graceful no-op.
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

import io
import logging
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.security.acl import (
    RE_SAFE_USERNAME,
    ACLError,
    get_current_windows_user,
    lock_application_storage,
    lock_file_to_current_user,
)
from engine.security.log_sanitizer import (
    LogSanitizer,
    sanitize_text,
)


def test_sanitize_multi_layer_credentials() -> None:
    """Verify redaction across Telegram tokens, standard key-values, JSON, and URL-encoding."""
    # 1. Telegram Bot Token (Raw format - using non-token mock string to prevent git/gitleaks false alarm)
    mock_tg_token = "000000000:FAKEtokenFORtestingPURPOSESonly123"
    raw_tg = f"Connecting to Telegram bot {mock_tg_token} now."
    clean_tg = sanitize_text(raw_tg)
    assert mock_tg_token not in clean_tg
    assert "***REDACTED_TELEGRAM_TOKEN***" in clean_tg

    # 2. Telegram Bot Token (URL-encoded %3A)
    url_tg = "https://api.telegram.org/bot000000000%3AFAKEtokenFORtestingPURPOSESonly123/getMe"
    clean_url_tg = sanitize_text(url_tg)
    assert "000000000%3AFAKEtokenFORtestingPURPOSESonly123" not in clean_url_tg
    assert "***REDACTED_TELEGRAM_TOKEN***" in clean_url_tg

    # 3. Standard Key-Value Credentials
    kv_text = "Login failed with password=DummyMockPassword123 and token='DummyMockToken!'"
    clean_kv = sanitize_text(kv_text)
    assert "DummyMockPassword123" not in clean_kv
    assert "DummyMockToken!" not in clean_kv
    assert "***REDACTED***" in clean_kv

    # 4. JSON Escaped Credentials
    json_text = 'Payload: {"mt5_password": "MockMT5Password999", "api_key": "K3y-Abc-123"}'
    clean_json = sanitize_text(json_text)
    assert "MockMT5Password999" not in clean_json
    assert "K3y-Abc-123" not in clean_json
    assert "***REDACTED***" in clean_json

    # 5. MT5 login method call pattern
    mt5_call = "mt5.login(12345678, 'MockLoginPassword', 'Exness-MT5Real21')"
    clean_mt5 = sanitize_text(mt5_call)
    assert "MockLoginPassword" not in clean_mt5
    assert "***REDACTED***" in clean_mt5


def test_safe_traceback_sanitization() -> None:
    """Verify exception traceback is sanitized via record.exc_text without corrupting exc_info."""
    sanitizer = LogSanitizer()
    secret_pass = "mock_err_pass"

    record: logging.LogRecord | None = None
    try:
        raise ValueError(f"Authentication failed with pwd='{secret_pass}'")
    except ValueError:
        # Create standard log record with exc_info
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=75,
            msg="Exception encountered during login",
            args=(),
            exc_info=sys.exc_info(),
        )

    assert record is not None
    assert record.exc_info is not None

    # Apply filter
    sanitizer.filter(record)

    # 1. exc_info must REMAIN a 3-element tuple (never overwritten with string!)
    assert isinstance(record.exc_info, tuple)
    assert len(record.exc_info) == 3

    # 2. exc_text must be populated and sanitized
    assert record.exc_text is not None
    assert secret_pass not in record.exc_text
    assert "***REDACTED***" in record.exc_text


def test_fast_path_latency_performance() -> None:
    """Verify heuristic fast-path processes standard market logs in < 0.05 ms per log."""
    normal_log = "Tick quote: pair=XAUUSD bid=2650.50 ask=2650.80 volume=140 spread=3.0"

    t0 = time.perf_counter()
    iterations = 1000
    for _ in range(iterations):
        sanitize_text(normal_log)
    elapsed = time.perf_counter() - t0

    avg_ms = (elapsed / iterations) * 1000.0
    # Average time must be well under 0.05 ms
    assert avg_ms < 0.05, f"Fast-path latency too high: {avg_ms:.4f} ms per log"


def test_logging_handler_integration_with_sanitizer() -> None:
    """Verify LogSanitizer integrates into logging.Handler pipeline and masks credentials."""
    dummy_log_entry = (
        "Attempting login with token=000000000:FAKEtokenFORtestingPURPOSESonly123 and "
        "password=DummyTestPassword789!"
    )

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))

    logger = logging.getLogger("aeterna.test.integration_sanitizer")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.addFilter(LogSanitizer())

    logger.info("%s", dummy_log_entry)
    handler.flush()

    output = stream.getvalue()
    assert "000000000:FAKEtokenFORtestingPURPOSESonly123" not in output
    assert "DummyTestPassword789!" not in output
    assert "***REDACTED_TELEGRAM_TOKEN***" in output or "***REDACTED***" in output


def test_native_win32_username_retrieval() -> None:
    """Verify native Win32 username retrieval matches safe whitelist regex."""
    if sys.platform != "win32":
        with pytest.raises(ACLError, match="Windows ACL identity is only supported on Win32 OS"):
            get_current_windows_user()
    else:
        user = get_current_windows_user()
        assert isinstance(user, str)
        assert len(user) > 0
        assert RE_SAFE_USERNAME.match(user) is not None


def test_acl_rejects_insecure_username_characters() -> None:
    """Verify username containing command injection characters strictly raises ValueError."""
    with (
        patch("engine.security.acl.get_current_windows_user", return_value="user&calc.exe"),
        patch("sys.platform", "win32"),
        pytest.raises(ValueError, match="Suspicious or insecure Windows username"),
    ):
        lock_file_to_current_user("dummy_path")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL tests require Win32 OS")
def test_acl_lockdown_execution(tmp_path: Path) -> None:
    """Verify lock_file_to_current_user executes shell-free icacls successfully."""
    test_file = tmp_path / "test_acl_target.db"
    test_file.write_text("dummy database content", encoding="utf-8")

    locked = lock_file_to_current_user(test_file)
    assert locked is True


def test_acl_non_windows_graceful_noop(tmp_path: Path) -> None:
    """Verify lock_file_to_current_user gracefully no-ops on non-Windows platforms."""
    test_file = tmp_path / "test_linux.db"
    test_file.write_text("linux content", encoding="utf-8")

    with patch("sys.platform", "linux"):
        locked = lock_file_to_current_user(test_file)
        assert locked is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL tests require Win32 OS")
def test_lock_application_storage(tmp_path: Path) -> None:
    """Verify lock_application_storage targets data and log files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "trading.db"
    db_file.write_text("db content", encoding="utf-8")

    enc_file = data_dir / ".secrets.enc"
    enc_file.write_text("enc content", encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "engine_debug.log"
    log_file.write_text("log content", encoding="utf-8")

    locked_list = lock_application_storage(base_dir=tmp_path)
    assert len(locked_list) >= 3
    assert db_file in locked_list
    assert enc_file in locked_list
    assert log_file in locked_list
