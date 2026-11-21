"""Windows Data Protection API (DPAPI) Native Cryptographic Isolation.

Module: engine.security.dpapi
Responsibility: Zero-plaintext credential encryption and JIT memory sanitization.
Enforces:
- REQ-EXE-003: Native CryptProtectData/CryptUnprotectData via ctypes (Crypt32.dll).
- Absolute CurrentUser scope with injected application entropy (pOptionalEntropy).
- SecretString storing only ciphertext in RAM with Just-In-Time (JIT) DPAPI decryption.
- Custom DPAPIDesyncError on master key or MAC/entropy desync.
Owner: aeterna-security
Tier: Tier A
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false

from __future__ import annotations

import ctypes
import json
import logging
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("aeterna.security.dpapi")

DEFAULT_SECRETS_PATH = Path("data/.secrets.enc")

# Windows DPAPI Constants & Application Salt Entropy
CRYPTPROTECT_UI_FORBIDDEN = 0x1
DEFAULT_APP_ENTROPY: bytes = b"AETERNA_QUANT_XAUUSD_SECURE_SALT"


class DPAPIError(Exception):
    """Raised when Windows DPAPI encryption or decryption fails."""


class DPAPIDesyncError(DPAPIError):
    """Raised when DPAPI master key or entropy is desynchronized (e.g. password changed, bad MAC)."""


class DATA_BLOB(ctypes.Structure):
    """Win32 DATA_BLOB structure for CryptProtectData / CryptUnprotectData."""

    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


@dataclass(frozen=True)
class SecretString:
    """Secure memory wrapper storing ONLY ciphertext bytes in RAM.

    Plaintext is NEVER stored in self attributes.
    Overrides __repr__ and __str__ to guarantee zero plain-text leakage in logs.
    get_secret_value() decrypts ciphertext Just-In-Time (JIT) via DPAPI
    at the exact moment of authentication.
    """

    _cipher_bytes: bytes
    _entropy: bytes = DEFAULT_APP_ENTROPY

    def __repr__(self) -> str:
        return "***MASKED***"

    def __str__(self) -> str:
        return "***MASKED***"

    def get_secret_value(self) -> str:
        """Decrypt ciphertext Just-In-Time (JIT) and return plaintext string."""
        raw_bytes = decrypt_dpapi(self._cipher_bytes, entropy=self._entropy)
        return raw_bytes.decode("utf-8")

    @classmethod
    def from_plaintext(
        cls, plaintext: str, entropy: bytes = DEFAULT_APP_ENTROPY
    ) -> SecretString:
        """Encrypt plaintext immediately using DPAPI and store only ciphertext."""
        cipher = encrypt_dpapi(plaintext.encode("utf-8"), entropy=entropy)
        return cls(_cipher_bytes=cipher, _entropy=entropy)


def _check_windows_platform() -> None:
    """Ensure host operating system is Windows."""
    if sys.platform != "win32":
        raise DPAPIError(
            f"Windows DPAPI is only supported on Win32 OS (current: {sys.platform})."
        )


def encrypt_dpapi(
    data: bytes,
    entropy: bytes = DEFAULT_APP_ENTROPY,
    description: str = "aeterna_secret",
) -> bytes:
    """Encrypt binary data using Windows DPAPI under CurrentUser scope with application entropy.

    Args:
        data: Plaintext bytes to encrypt.
        entropy: Application salt bytes passed to pOptionalEntropy.
        description: Optional label for the data blob.

    Returns:
        Ciphertext bytes tied strictly to the active Windows user profile and application salt.
    """
    _check_windows_platform()
    if not data:
        raise DPAPIError("Cannot encrypt empty data payload.")

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    in_buffer = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(
        len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char))
    )

    entropy_buffer = ctypes.create_string_buffer(entropy)
    entropy_blob = DATA_BLOB(
        len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_char))
    )

    out_blob = DATA_BLOB()

    # Scope: CurrentUser (0x1 = CRYPTPROTECT_UI_FORBIDDEN, without 0x4 CRYPTPROTECT_LOCAL_MACHINE)
    success = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not success:
        get_last_error = getattr(ctypes, "GetLastError", None)
        err_code = int(get_last_error()) if get_last_error is not None else 0
        raise DPAPIError(f"CryptProtectData failed with Windows error: {err_code}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def decrypt_dpapi(
    cipher: bytes,
    entropy: bytes = DEFAULT_APP_ENTROPY,
) -> bytes:
    """Decrypt ciphertext using Windows DPAPI under CurrentUser scope with application entropy.

    Args:
        cipher: Encrypted ciphertext bytes.
        entropy: Application salt bytes passed to pOptionalEntropy.

    Returns:
        Original plaintext bytes.

    Raises:
        DPAPIDesyncError: If master key, OS password, MAC, or entropy is desynchronized.
        DPAPIError: For general DPAPI operational errors.
    """
    _check_windows_platform()
    if not cipher:
        raise DPAPIError("Cannot decrypt empty cipher payload.")

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    in_buffer = ctypes.create_string_buffer(cipher)
    in_blob = DATA_BLOB(
        len(cipher), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char))
    )

    entropy_buffer = ctypes.create_string_buffer(entropy)
    entropy_blob = DATA_BLOB(
        len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_char))
    )

    out_blob = DATA_BLOB()

    success = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not success:
        get_last_error = getattr(ctypes, "GetLastError", None)
        err_code = int(get_last_error()) if get_last_error is not None else 0

        # Win32 codes indicating MAC failure, master key invalid, or desynchronized entropy:
        # 13: ERROR_INVALID_DATA (wrong entropy / MAC failure)
        # 0x80090006: NTE_BAD_MAC (or signed -2146893818)
        # 0x8009000B: NTE_BAD_KEY_STATE
        # 0x80090016: NTE_KEYSET_NOT_DEF
        desync_codes = {13, 0x80090006, 0x8009000B, 0x80090016, -2146893818}
        if err_code in desync_codes or (err_code & 0xFFFFFFFF) in {
            0x80090006,
            0x8009000B,
            0x80090016,
        }:
            raise DPAPIDesyncError(
                f"DPAPI master key or entropy desynchronized (Win32 error: {err_code}, "
                f"hex: 0x{err_code & 0xFFFFFFFF:x}). Windows user password may have changed or salt mismatch."
            )
        raise DPAPIError(f"CryptUnprotectData failed with Windows error: {err_code}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def save_encrypted_secrets(
    secrets: dict[str, Any],
    filepath: Path | str = DEFAULT_SECRETS_PATH,
    entropy: bytes = DEFAULT_APP_ENTROPY,
) -> None:
    """Serialize secrets dictionary to JSON, encrypt via DPAPI, and save atomically.

    Args:
        secrets: Dictionary of sensitive configuration values.
        filepath: Destination binary file path.
        entropy: Application salt bytes.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Unwrap any existing SecretString before serialization
    serializable: dict[str, Any] = {}
    for k, v in secrets.items():
        if isinstance(v, SecretString):
            serializable[k] = v.get_secret_value()
        else:
            serializable[k] = v

    raw_json = json.dumps(serializable, ensure_ascii=False).encode("utf-8")
    cipher_bytes = encrypt_dpapi(raw_json, entropy=entropy)
    del raw_json
    del serializable

    # Atomic write via temporary file
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "wb") as f:
        f.write(cipher_bytes)

    temp_path.replace(path)
    logger.info("Encrypted secrets saved to %s", path)


def _clean_env_value(raw: str) -> str:
    """Strip whitespace, wrapping quotes, and trailing inline `# comment` from a .env value."""
    val = raw.strip()
    if val[:1] in ("'", '"'):
        end = val.find(val[0], 1)
        return val[1:end] if end != -1 else val[1:]
    return re.split(r"\s+#", val, maxsplit=1)[0].strip()


def load_credentials_from_env() -> dict[str, Any] | None:
    """Read credentials from .env file or environment variables if present."""
    import os

    env_path = Path(".env")
    env_vars: dict[str, str] = {}

    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = _clean_env_value(val)
        except OSError as exc:
            logger.warning("Could not read .env file: %s", exc)

    # Read from parsed file or process environment
    def get_val(key: str) -> str | None:
        return env_vars.get(key) or os.environ.get(key)

    token = get_val("TELEGRAM_BOT_TOKEN")
    admin_id_str = get_val("TELEGRAM_ADMIN_USER_ID") or get_val("TELEGRAM_ADMIN_ID")

    # If minimal credentials are not set in .env, return None
    if not token and not admin_id_str:
        return None

    res: dict[str, Any] = {}
    if token:
        res["telegram_bot_token"] = SecretString.from_plaintext(token)
    if admin_id_str:
        if admin_id_str.isdigit() or (
            admin_id_str.startswith("-") and admin_id_str[1:].isdigit()
        ):
            res["telegram_admin_id"] = int(admin_id_str)
        else:
            logger.warning(
                "Invalid non-integer TELEGRAM_ADMIN_ID in environment: %s", admin_id_str
            )

    channel_id = get_val("TELEGRAM_CHANNEL_ID") or get_val("TELEGRAM_SIGNAL_CHANNEL_ID")
    if channel_id:
        res["telegram_channel_id"] = channel_id

    mt5_login_str = get_val("EXNESS_MT5_LOGIN") or get_val("MT5_LOGIN")
    if mt5_login_str:
        if mt5_login_str.isdigit():
            res["mt5_login"] = int(mt5_login_str)
        else:
            logger.warning(
                "Invalid non-integer EXNESS_MT5_LOGIN in environment: %s", mt5_login_str
            )

    mt5_pass = get_val("EXNESS_MT5_PASSWORD") or get_val("MT5_PASSWORD")
    if mt5_pass:
        res["mt5_password"] = SecretString.from_plaintext(mt5_pass)

    mt5_srv = get_val("EXNESS_MT5_SERVER") or get_val("MT5_SERVER")
    if mt5_srv:
        res["mt5_server"] = mt5_srv

    return res


def load_trading_secrets_with_source(
    filepath: Path | str = DEFAULT_SECRETS_PATH,
    entropy: bytes = DEFAULT_APP_ENTROPY,
) -> tuple[dict[str, Any], str]:
    """Unified credential loader returning secrets dict and credential source ('ENV' or 'DPAPI').

    Args:
        filepath: Path to .secrets.enc DPAPI encrypted file.
        entropy: Application salt bytes.

    Returns:
        tuple[dict[str, Any], str]: Decrypted/parsed secrets and source identifier ('ENV' or 'DPAPI').

    Raises:
        FileNotFoundError: If neither .env credentials nor DPAPI secrets file could be loaded.
    """
    env_creds = load_credentials_from_env()
    if env_creds:
        return env_creds, "ENV"

    path = Path(filepath)
    if path.is_file():
        try:
            secrets = load_encrypted_secrets(path, entropy=entropy)
            return secrets, "DPAPI"
        except (DPAPIError, OSError, ValueError) as exc:
            logger.warning(
                "Failed to decrypt DPAPI secrets (%s), no credentials found...", exc
            )

    raise FileNotFoundError(
        "No credentials found. Either create .env (see .env.example) or run: uv run python scripts/setup_secrets.py"
    )


def load_trading_secrets(
    filepath: Path | str = DEFAULT_SECRETS_PATH,
    entropy: bytes = DEFAULT_APP_ENTROPY,
) -> dict[str, Any]:
    """Unified credential loader: checks .env first for quick local developer override, then DPAPI (.secrets.enc)."""
    secrets, _ = load_trading_secrets_with_source(filepath=filepath, entropy=entropy)
    return secrets


def load_encrypted_secrets(
    filepath: Path | str = DEFAULT_SECRETS_PATH,
    entropy: bytes = DEFAULT_APP_ENTROPY,
) -> dict[str, Any]:
    """Read binary secrets file, decrypt via DPAPI, and wrap sensitive fields in JIT SecretString.

    Args:
        filepath: Path to .secrets.enc file.
        entropy: Application salt bytes.

    Returns:
        Dictionary with sensitive values wrapped in JIT SecretString (only ciphertext in RAM).
    """
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Encrypted secrets file not found: {path}")

    with open(path, "rb") as f:
        cipher_bytes = f.read()

    plain_bytes = decrypt_dpapi(cipher_bytes, entropy=entropy)
    try:
        data = json.loads(plain_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DPAPIError(f"Corrupt secrets payload: {exc}") from exc
    finally:
        del plain_bytes

    if not isinstance(data, dict):
        raise DPAPIError("Decrypted secrets payload must be a JSON dictionary.")

    # Sensitive key names that must be wrapped in JIT SecretString
    sensitive_keys = {
        "password",
        "mt5_password",
        "token",
        "telegram_bot_token",
        "secret",
        "api_key",
    }

    result: dict[str, Any] = {}
    for k, v in data.items():
        if k in sensitive_keys and isinstance(v, str):
            result[k] = SecretString.from_plaintext(v, entropy=entropy)
        else:
            result[k] = v

    del data
    return result
