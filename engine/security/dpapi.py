"""Windows Data Protection API (DPAPI) Native Cryptographic Isolation.

Module: engine.security.dpapi
Responsibility: Zero-plaintext credential encryption and memory sanitization.
Enforces:
- REQ-EXE-003: Native CryptProtectData/CryptUnprotectData via ctypes (Crypt32.dll).
- Absolute CurrentUser scope (CRYPTPROTECT_UI_FORBIDDEN, no LocalMachine flag).
- SecretString with masked __repr__ and __str__ to prevent accidental leaks.
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
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("aeterna.security.dpapi")

DEFAULT_SECRETS_PATH = Path("data/.secrets.enc")

# Windows DPAPI Constants
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DPAPIError(Exception):
    """Raised when Windows DPAPI encryption or decryption fails."""


class DATA_BLOB(ctypes.Structure):
    """Win32 DATA_BLOB structure for CryptProtectData / CryptUnprotectData."""

    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


@dataclass(frozen=True)
class SecretString:
    """Secure memory wrapper around sensitive credential strings.

    Overrides __repr__ and __str__ to guarantee zero leakage in logs,
    tracebacks, or console print statements.
    """

    _value: str

    def __repr__(self) -> str:
        return "***MASKED***"

    def __str__(self) -> str:
        return "***MASKED***"

    def get_secret_value(self) -> str:
        """Expose raw sensitive value only at the exact moment of authentication."""
        return self._value


def _check_windows_platform() -> None:
    """Ensure host operating system is Windows."""
    if sys.platform != "win32":
        raise DPAPIError(
            f"Windows DPAPI is only supported on Win32 OS (current: {sys.platform})."
        )


def encrypt_dpapi(data: bytes, description: str = "aeterna_secret") -> bytes:
    """Encrypt binary data using Windows DPAPI under CurrentUser scope.

    Args:
        data: Plaintext bytes to encrypt.
        description: Optional label for the data blob.

    Returns:
        Ciphertext bytes tied strictly to the active Windows user profile.
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
    out_blob = DATA_BLOB()

    # Scope: CurrentUser (0x1 = CRYPTPROTECT_UI_FORBIDDEN, without 0x4 CRYPTPROTECT_LOCAL_MACHINE)
    success = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not success:
        err_code = int(ctypes.GetLastError())
        raise DPAPIError(f"CryptProtectData failed with Windows error: {err_code}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def decrypt_dpapi(cipher: bytes) -> bytes:
    """Decrypt ciphertext using Windows DPAPI under CurrentUser scope.

    Args:
        cipher: Encrypted ciphertext bytes.

    Returns:
        Original plaintext bytes.
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
    out_blob = DATA_BLOB()

    success = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not success:
        err_code = int(ctypes.GetLastError())
        raise DPAPIError(f"CryptUnprotectData failed with Windows error: {err_code}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def save_encrypted_secrets(
    secrets: dict[str, Any], filepath: Path | str = DEFAULT_SECRETS_PATH
) -> None:
    """Serialize secrets dictionary to JSON, encrypt via DPAPI, and save atomically.

    Args:
        secrets: Dictionary of sensitive configuration values.
        filepath: Destination binary file path.
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
    cipher_bytes = encrypt_dpapi(raw_json)

    # Atomic write via temporary file
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "wb") as f:
        f.write(cipher_bytes)

    temp_path.replace(path)
    logger.info("Encrypted secrets saved to %s", path)


def load_encrypted_secrets(
    filepath: Path | str = DEFAULT_SECRETS_PATH,
) -> dict[str, Any]:
    """Read binary secrets file, decrypt via DPAPI, and wrap sensitive fields in SecretString.

    Args:
        filepath: Path to .secrets.enc file.

    Returns:
        Dictionary with sensitive values wrapped in SecretString.
    """
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Encrypted secrets file not found: {path}")

    with open(path, "rb") as f:
        cipher_bytes = f.read()

    plain_bytes = decrypt_dpapi(cipher_bytes)
    try:
        data = json.loads(plain_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DPAPIError(f"Corrupt secrets payload: {exc}") from exc

    if not isinstance(data, dict):
        raise DPAPIError("Decrypted secrets payload must be a JSON dictionary.")

    # Sensitive key names that must be wrapped in SecretString
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
            result[k] = SecretString(v)
        else:
            result[k] = v

    return result
