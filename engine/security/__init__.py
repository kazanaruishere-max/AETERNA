"""Security and cryptographic isolation module."""

from engine.security.acl import (
    ACLError,
    get_current_windows_user,
    lock_application_storage,
    lock_file_to_current_user,
)
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
from engine.security.log_sanitizer import (
    LogSanitizer,
    sanitize_text,
)

__all__ = [
    "DEFAULT_APP_ENTROPY",
    "DEFAULT_SECRETS_PATH",
    "ACLError",
    "DPAPIDesyncError",
    "DPAPIError",
    "LogSanitizer",
    "SecretString",
    "decrypt_dpapi",
    "encrypt_dpapi",
    "get_current_windows_user",
    "load_encrypted_secrets",
    "lock_application_storage",
    "lock_file_to_current_user",
    "sanitize_text",
    "save_encrypted_secrets",
]
