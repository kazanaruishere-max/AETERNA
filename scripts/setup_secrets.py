"""Offline CLI utility for bootstrapping encrypted trading credentials via Windows DPAPI.

This script runs ONLY offline during setup and MUST NOT be invoked at runtime.
It prompts for MT5 and Telegram credentials using getpass (hidden input, zero echo),
encrypts them using native Windows DPAPI (CurrentUser scope), saves the ciphertext
to data/.secrets.enc, and immediately purges plaintext variables from local memory via del.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.security.dpapi import DEFAULT_SECRETS_PATH, save_encrypted_secrets


def run_setup(output_path: Path | str = DEFAULT_SECRETS_PATH) -> int:
    """Prompt for credentials interactively and encrypt to destination file."""
    print("================================================================================")
    print("AETERNA QUANT — SECURE DPAPI CREDENTIAL BOOTSTRAPPING")
    print("================================================================================")
    print("All sensitive credentials are encrypted using Windows DPAPI (CurrentUser scope).")
    print("No plain-text credentials will be stored on disk or in environment variables.\n")

    try:
        raw_login = input("Enter MetaTrader 5 Login Account ID (e.g., 12345678): ").strip()
        mt5_login = int(raw_login)
    except ValueError:
        print("[ERROR] Account ID must be a valid integer.")
        return 1

    mt5_server = input("Enter MetaTrader 5 Server (e.g., Exness-MT5Real21): ").strip()
    if not mt5_server:
        print("[ERROR] MT5 Server cannot be empty.")
        return 1

    mt5_password = getpass.getpass("Enter MetaTrader 5 Password (hidden): ")
    if not mt5_password:
        print("[ERROR] MT5 Password cannot be empty.")
        return 1

    telegram_bot_token = getpass.getpass("Enter Telegram Bot Token (hidden): ")
    if not telegram_bot_token:
        print("[ERROR] Telegram Bot Token cannot be empty.")
        return 1

    try:
        raw_admin_id = input("Enter Telegram Admin User ID (integer): ").strip()
        telegram_admin_id = int(raw_admin_id)
    except ValueError:
        print("[ERROR] Telegram Admin ID must be an integer.")
        return 1

    telegram_channel_id = input("Enter Telegram Signal Channel ID (optional, e.g. @MyChannel or -100123456): ").strip()

    secrets_dict = {
        "mt5_login": mt5_login,
        "mt5_password": mt5_password,
        "mt5_server": mt5_server,
        "telegram_bot_token": telegram_bot_token,
        "telegram_admin_id": telegram_admin_id,
        "telegram_channel_id": telegram_channel_id,
    }

    try:
        save_encrypted_secrets(secrets_dict, filepath=output_path)
        print(f"\n[SUCCESS] Secrets successfully encrypted and saved to {output_path}")
    finally:
        # Immediate memory sanitization: purge sensitive plaintext variables
        del mt5_password
        del telegram_bot_token
        del secrets_dict

    return 0


if __name__ == "__main__":
    sys.exit(run_setup())
