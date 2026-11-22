"""Deterministic unit and security tests for Windows DPAPI, Application Entropy, and JIT SecretString.

Validates:
1. REQ-EXE-003: Native CryptProtectData/CryptUnprotectData isolation with Application Entropy.
2. JIT Decryption: SecretString stores ONLY ciphertext in RAM (no plaintext _value attribute).
3. Absolute SecretString memory masking (zero plain-text leak in repr, str, f-strings, logging).
4. Master key / entropy desynchronization handling (DPAPIDesyncError on wrong salt / corrupt key).
5. Encryption/decryption persistence roundtrip and atomic file operations.
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
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.security.dpapi import (
    DEFAULT_APP_ENTROPY,
    DPAPIDesyncError,
    DPAPIError,
    SecretString,
    decrypt_dpapi,
    encrypt_dpapi,
    load_credentials_from_env,
    load_encrypted_secrets,
    save_encrypted_secrets,
)
from scripts.setup_secrets import run_setup


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_secret_string_jit_decryption_no_plaintext_in_memory() -> None:
    """Verify SecretString stores ONLY ciphertext in RAM with zero plaintext attributes."""
    raw_secret = "UltraSecretProductionPassword2026!"
    sec = SecretString.from_plaintext(raw_secret)

    # 1. Plaintext _value attribute MUST NOT EXIST
    assert not hasattr(sec, "_value")
    assert hasattr(sec, "_cipher_bytes")
    assert isinstance(sec._cipher_bytes, bytes)
    assert len(sec._cipher_bytes) > 0

    # 2. Plaintext must NOT appear anywhere in the object dictionary or attribute values
    for val in vars(sec).values():
        if isinstance(val, (str, bytes)):
            assert raw_secret.encode("utf-8") not in (
                val if isinstance(val, bytes) else val.encode("utf-8")
            )

    # 3. get_secret_value() must decrypt Just-In-Time (JIT) to return the original plaintext
    assert sec.get_secret_value() == raw_secret


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_secret_string_masking() -> None:
    """Verify SecretString strictly masks sensitive content in all string representations."""
    raw_secret = "P@ssw0rd_Exness_XAUUSD_2026!"
    sec = SecretString.from_plaintext(raw_secret)

    # 1. str() and repr() must return masked string
    assert str(sec) == "***MASKED***"
    assert repr(sec) == "***MASKED***"

    # 2. String formatting / f-strings must return masked string
    assert f"Secret: {sec}" == "Secret: ***MASKED***"
    assert f"{sec}" == "***MASKED***"

    # 3. Logging output must never contain raw plaintext
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    test_logger = logging.getLogger("test_masking_logger")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    test_logger.info("Attempting login with credentials: %s", sec)
    handler.flush()
    log_output = log_stream.getvalue()

    assert raw_secret not in log_output
    assert "***MASKED***" in log_output


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_secret_string_immutability() -> None:
    """Verify SecretString is an immutable frozen dataclass."""
    sec = SecretString.from_plaintext("initial_token_123")
    with pytest.raises(FrozenInstanceError):
        # pyright: ignore[reportAttributeAccessIssue]
        sec._cipher_bytes = b"tampered_cipher_bytes"  # type: ignore[misc]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_dpapi_application_entropy_isolation() -> None:
    """Verify application entropy prevents decryption when salt is wrong or missing."""
    test_payload = b"CRITICAL_FINANCIAL_API_KEY_9999"

    # Encrypt with default salt entropy
    ciphertext = encrypt_dpapi(test_payload, entropy=DEFAULT_APP_ENTROPY)

    # Decrypt with correct entropy must succeed bit-perfect
    decrypted = decrypt_dpapi(ciphertext, entropy=DEFAULT_APP_ENTROPY)
    assert decrypted == test_payload

    # Decrypt with WRONG entropy must fail-fast with DPAPIDesyncError
    wrong_entropy = b"UNAUTHORIZED_MALICIOUS_APP_SALT"
    with pytest.raises(
        DPAPIDesyncError, match="DPAPI master key or entropy desynchronized"
    ):
        decrypt_dpapi(ciphertext, entropy=wrong_entropy)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_dpapi_encrypt_decrypt_roundtrip() -> None:
    """Verify native Windows DPAPI bit-perfect cryptographic roundtrip."""
    test_payload = b"AETERNA_SUPER_SECRET_PAYLOAD_XAUUSD_\x00\xff\xfe"
    ciphertext = encrypt_dpapi(test_payload, description="test_crypto")

    assert ciphertext != test_payload
    assert len(ciphertext) > len(test_payload)

    decrypted = decrypt_dpapi(ciphertext)
    assert decrypted == test_payload


def test_empty_payload_raises_dpapi_error() -> None:
    """Verify encrypting or decrypting empty bytes raises DPAPIError."""
    if sys.platform != "win32":
        pytest.skip("Windows DPAPI requires Win32 OS")

    with pytest.raises(DPAPIError, match="Cannot encrypt empty data payload"):
        encrypt_dpapi(b"")

    with pytest.raises(DPAPIError, match="Cannot decrypt empty cipher payload"):
        decrypt_dpapi(b"")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_corrupt_ciphertext_raises_dpapi_desync_or_error() -> None:
    """Verify corrupt or tampered ciphertext raises DPAPIError or DPAPIDesyncError."""
    corrupt_data = b"RANDOM_CORRUPT_CIPHER_BYTES_1234567890"
    with pytest.raises(DPAPIError):
        decrypt_dpapi(corrupt_data)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_secrets_persistence_roundtrip(tmp_path: Path) -> None:
    """Verify saving and loading secrets file with JIT SecretString wrapping."""
    target_file = tmp_path / ".secrets.enc"

    secrets_to_save = {
        "mt5_login": 98765432,
        "mt5_password": "MyExnessSecurePassword999",
        "mt5_server": "Exness-MT5Real12",
        "telegram_bot_token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        "telegram_admin_id": 99887766,
        "arbitrary_config": "plain_value",
    }

    save_encrypted_secrets(secrets_to_save, filepath=target_file)
    assert target_file.is_file()

    # File on disk must be encrypted binary, zero plaintext
    raw_file_content = target_file.read_bytes()
    assert b"MyExnessSecurePassword999" not in raw_file_content
    assert b"1234567890:ABCdefGHIjklMNOpqrsTUVwxyz" not in raw_file_content

    loaded = load_encrypted_secrets(target_file)

    assert loaded["mt5_login"] == 98765432
    assert loaded["mt5_server"] == "Exness-MT5Real12"
    assert loaded["telegram_admin_id"] == 99887766
    assert loaded["arbitrary_config"] == "plain_value"

    # Sensitive fields must be wrapped in JIT SecretString without plaintext attribute
    assert isinstance(loaded["mt5_password"], SecretString)
    assert isinstance(loaded["telegram_bot_token"], SecretString)
    assert not hasattr(loaded["mt5_password"], "_value")
    assert not hasattr(loaded["telegram_bot_token"], "_value")

    assert str(loaded["mt5_password"]) == "***MASKED***"
    assert loaded["mt5_password"].get_secret_value() == "MyExnessSecurePassword999"
    assert (
        loaded["telegram_bot_token"].get_secret_value()
        == "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
    )


def test_missing_secrets_file_raises_not_found(tmp_path: Path) -> None:
    """Verify loading from non-existent file path raises FileNotFoundError."""
    non_existent = tmp_path / "does_not_exist.enc"
    with pytest.raises(FileNotFoundError, match="Encrypted secrets file not found"):
        load_encrypted_secrets(non_existent)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_env_loader_strips_inline_comment_and_quotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inline `.env` comments must not corrupt numeric IDs (regression: admin ID became non-integer)."""
    (tmp_path / ".env").write_text(
        'TELEGRAM_BOT_TOKEN="123:abc"\n'
        "TELEGRAM_ADMIN_USER_ID=9876543210  # Admin ID, do not share\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    creds = load_credentials_from_env()

    assert creds is not None
    assert creds["telegram_admin_id"] == 9876543210
    assert isinstance(creds["telegram_bot_token"], SecretString)
    assert creds["telegram_bot_token"].get_secret_value() == "123:abc"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires Win32 OS")
def test_setup_secrets_cli_execution(tmp_path: Path) -> None:
    """Verify scripts/setup_secrets.py runs cleanly and writes encrypted payload."""
    test_out = tmp_path / ".secrets.enc"

    inputs = iter(["11223344", "Demo-Server", "55667788", "@AeternaSignalsTest"])
    passwords = iter(["SuperSecureMT5Pass", "TelegramBotTokenSecret"])

    def mock_input(_prompt: str = "") -> str:
        return next(inputs)

    def mock_getpass(_prompt: str = "") -> str:
        return next(passwords)

    with patch("builtins.input", mock_input), patch("getpass.getpass", mock_getpass):
        exit_code = run_setup(output_path=test_out)

    assert exit_code == 0
    assert test_out.is_file()

    loaded = load_encrypted_secrets(test_out)
    assert loaded["mt5_login"] == 11223344
    assert loaded["mt5_server"] == "Demo-Server"
    assert loaded["telegram_admin_id"] == 55667788
    assert isinstance(loaded["mt5_password"], SecretString)
    assert loaded["mt5_password"].get_secret_value() == "SuperSecureMT5Pass"
    assert isinstance(loaded["telegram_bot_token"], SecretString)
    assert loaded["telegram_bot_token"].get_secret_value() == "TelegramBotTokenSecret"
