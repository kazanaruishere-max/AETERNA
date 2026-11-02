"""Security and cryptographic isolation module."""

from engine.security.dpapi import (
    DEFAULT_APP_ENTROPY,
    DEFAULT_SECRETS_PATH,
    DPAPIDesyncError,
    DPAPIError,
    SecretString,
    decrypt_dpapi,
    encrypt_dpapi,
    load_encrypted_secrets,
    save_encrypted_secrets,
)

__all__ = [
    "DEFAULT_APP_ENTROPY",
    "DEFAULT_SECRETS_PATH",
    "DPAPIDesyncError",
    "DPAPIError",
    "SecretString",
    "decrypt_dpapi",
    "encrypt_dpapi",
    "load_encrypted_secrets",
    "save_encrypted_secrets",
]
