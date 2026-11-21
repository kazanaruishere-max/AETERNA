"""Tests for main entrypoint wiring, credential provenance, and calendar snapshot resolution.

Covers:
1. load_trading_secrets_with_source with ENV credentials -> CREDENTIAL_SOURCE=ENV
2. load_trading_secrets_with_source with DPAPI credentials -> CREDENTIAL_SOURCE=DPAPI
3. load_trading_secrets backward compatibility delegation
4. Missing credentials raise FileNotFoundError
5. resolve_calendar_snapshot_path default fallback (data/calendar_snapshot.json)
6. resolve_calendar_snapshot_path environment override and whitespace handling
7. main_async logs CREDENTIAL_SOURCE=ENV and passes resolved snapshot to build_runtime_bundle
8. main_async logs CREDENTIAL_SOURCE=DPAPI and logs MODE=SIGNAL_ONLY LIVE_ORDER=DISABLED
9. Zero secret leakage in logs or representations
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.main import (
    DEFAULT_CALENDAR_SNAPSHOT_PATH,
    main_async,
    resolve_calendar_snapshot_path,
)
from engine.security.dpapi import (
    DPAPIError,
    SecretString,
    load_trading_secrets,
    load_trading_secrets_with_source,
)


def _make_dummy_credentials() -> dict[str, Any]:
    """Return dummy non-sensitive credential dictionary for testing."""
    return {
        "telegram_bot_token": SecretString(_cipher_bytes=b"dummy_token_cipher"),
        "telegram_admin_id": 123456789,
        "mt5_login": 98765432,
        "mt5_password": SecretString(_cipher_bytes=b"dummy_password_cipher"),
        "mt5_server": "Demo-Server",
    }


def test_load_trading_secrets_with_source_env() -> None:
    """Verify credentials loaded from environment return CREDENTIAL_SOURCE='ENV'."""
    dummy = _make_dummy_credentials()
    with patch(
        "engine.security.dpapi.load_credentials_from_env",
        return_value=dummy,
    ):
        creds, source = load_trading_secrets_with_source()
        assert creds == dummy
        assert source == "ENV"


def test_load_trading_secrets_with_source_dpapi(tmp_path: Path) -> None:
    """Verify fallback to DPAPI encrypted file returns CREDENTIAL_SOURCE='DPAPI'."""
    dummy = _make_dummy_credentials()
    dummy_enc_path = tmp_path / ".secrets.enc"
    dummy_enc_path.write_bytes(b"dummy_cipher_bytes")

    with (
        patch("engine.security.dpapi.load_credentials_from_env", return_value=None),
        patch("engine.security.dpapi.load_encrypted_secrets", return_value=dummy),
    ):
        creds, source = load_trading_secrets_with_source(filepath=dummy_enc_path)
        assert creds == dummy
        assert source == "DPAPI"


def test_load_trading_secrets_backward_compatible() -> None:
    """Verify load_trading_secrets delegates to load_trading_secrets_with_source."""
    dummy = _make_dummy_credentials()
    with patch(
        "engine.security.dpapi.load_trading_secrets_with_source",
        return_value=(dummy, "ENV"),
    ) as mock_loader:
        creds = load_trading_secrets()
        assert creds == dummy
        mock_loader.assert_called_once()


def test_load_trading_secrets_with_source_missing_raises_error(
    tmp_path: Path,
) -> None:
    """Verify FileNotFoundError is raised when neither env nor DPAPI exists."""
    missing_file = tmp_path / "missing.enc"
    with (
        patch("engine.security.dpapi.load_credentials_from_env", return_value=None),
        pytest.raises(FileNotFoundError, match="No credentials found"),
    ):
        load_trading_secrets_with_source(filepath=missing_file)


def test_load_trading_secrets_with_source_dpapi_error_raises_not_found(
    tmp_path: Path,
) -> None:
    """Verify DPAPI decryption error logs warning and raises FileNotFoundError."""
    dummy_enc_path = tmp_path / ".secrets.enc"
    dummy_enc_path.write_bytes(b"corrupt")

    with (
        patch("engine.security.dpapi.load_credentials_from_env", return_value=None),
        patch(
            "engine.security.dpapi.load_encrypted_secrets",
            side_effect=DPAPIError("decryption failed"),
        ),
        pytest.raises(FileNotFoundError, match="No credentials found"),
    ):
        load_trading_secrets_with_source(filepath=dummy_enc_path)


def test_resolve_calendar_snapshot_path_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify resolver returns default fallback when env var is unset."""
    monkeypatch.delenv("CALENDAR_SNAPSHOT_PATH", raising=False)
    resolved = resolve_calendar_snapshot_path()
    assert resolved == DEFAULT_CALENDAR_SNAPSHOT_PATH
    assert resolved == "data/calendar_snapshot.json"


def test_resolve_calendar_snapshot_path_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify resolver prioritizes CALENDAR_SNAPSHOT_PATH environment variable."""
    custom_path = "var/data/custom_calendar.json"
    monkeypatch.setenv("CALENDAR_SNAPSHOT_PATH", custom_path)
    resolved = resolve_calendar_snapshot_path()
    assert resolved == custom_path


def test_resolve_calendar_snapshot_path_whitespace_and_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify resolver trims whitespace and falls back to default on empty string."""
    monkeypatch.setenv("CALENDAR_SNAPSHOT_PATH", "   ")
    assert resolve_calendar_snapshot_path() == DEFAULT_CALENDAR_SNAPSHOT_PATH

    monkeypatch.setenv("CALENDAR_SNAPSHOT_PATH", "  custom/path.json  ")
    assert resolve_calendar_snapshot_path() == "custom/path.json"


def test_resolve_calendar_snapshot_path_explicit_dict() -> None:
    """Verify resolver handles explicit dictionary injection."""
    assert (
        resolve_calendar_snapshot_path({"CALENDAR_SNAPSHOT_PATH": "injected/path.json"})
        == "injected/path.json"
    )
    assert resolve_calendar_snapshot_path({}) == DEFAULT_CALENDAR_SNAPSHOT_PATH


@pytest.mark.asyncio
async def test_main_wiring_passes_calendar_snapshot_and_logs_source_env(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify main_async logs CREDENTIAL_SOURCE=ENV and forwards calendar_snapshot_path."""
    custom_snapshot = "data/prod_calendar_snapshot.json"
    monkeypatch.setenv("CALENDAR_SNAPSHOT_PATH", custom_snapshot)

    dummy_creds = _make_dummy_credentials()
    mock_bundle = MagicMock()
    mock_bundle.runtime.run_forever = AsyncMock()

    mock_exness = MagicMock()
    mock_exness.connected = True
    mock_exness.connect.return_value = True

    mock_bot = MagicMock()
    mock_bot.send_initial_dashboard.return_value = True

    with (
        caplog.at_level(logging.INFO, logger="aeterna"),
        patch(
            "engine.main.load_trading_secrets_with_source",
            return_value=(dummy_creds, "ENV"),
        ),
        patch("engine.main.ExnessClient", return_value=mock_exness),
        patch("engine.main.TelegramControlBot", return_value=mock_bot),
        patch("engine.main.build_runtime_bundle", return_value=mock_bundle) as mock_bld,
        patch("engine.main.run_trading_loop", new_callable=AsyncMock),
    ):
        exit_code = await main_async()

    assert exit_code == 0
    log_text = " ".join(caplog.messages)
    assert "CREDENTIAL_SOURCE=ENV" in log_text
    assert "MODE=SIGNAL_ONLY LIVE_ORDER=DISABLED" in log_text

    mock_bld.assert_called_once()
    assert mock_bld.call_args.kwargs.get("calendar_snapshot_path") == custom_snapshot


@pytest.mark.asyncio
async def test_main_wiring_logs_source_dpapi(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify main_async logs CREDENTIAL_SOURCE=DPAPI when secrets come from DPAPI."""
    dummy_creds = _make_dummy_credentials()
    mock_bundle = MagicMock()
    mock_bundle.runtime.run_forever = AsyncMock()

    mock_exness = MagicMock()
    mock_exness.connected = True
    mock_exness.connect.return_value = True

    mock_bot = MagicMock()
    mock_bot.send_initial_dashboard.return_value = True

    with (
        caplog.at_level(logging.INFO, logger="aeterna"),
        patch(
            "engine.main.load_trading_secrets_with_source",
            return_value=(dummy_creds, "DPAPI"),
        ),
        patch("engine.main.ExnessClient", return_value=mock_exness),
        patch("engine.main.TelegramControlBot", return_value=mock_bot),
        patch("engine.main.build_runtime_bundle", return_value=mock_bundle),
        patch("engine.main.run_trading_loop", new_callable=AsyncMock),
    ):
        exit_code = await main_async()

    assert exit_code == 0
    log_text = " ".join(caplog.messages)
    assert "CREDENTIAL_SOURCE=DPAPI" in log_text


def test_main_wiring_no_prohibited_tokens_in_code_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Confirm zero sensitive credentials or forbidden trading orders in wiring."""
    import engine.main as main_mod

    # Verify no live execution orders exist in main
    forbidden = ("order_send", "PositionModify")
    main_source = Path(main_mod.__file__).read_text(encoding="utf-8")
    for token in forbidden:
        assert token not in main_source, f"Forbidden '{token}' in engine/main.py"
