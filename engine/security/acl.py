"""Windows Access Control List (ACL) Security Lockdown.

Module: engine.security.acl
Responsibility: File and database permission lockdown strictly to Current User.
Enforces:
- REQ-EXE-005: Native icacls lockdown (/inheritance:r, /grant:r %USER%:(F)).
- Native Win32 identity retrieval via advapi32.GetUserNameW (no %USERNAME% shell variable).
- Strict regex whitelist guard on username to prevent command injection.
- Shell-free subprocess execution (shell=False) with graceful no-op on non-Windows platforms.
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
import logging
import re
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger("aeterna.security.acl")

# Strict regex whitelist for safe Windows usernames (rejects &, |, ;, >, <, quotes, etc.)
RE_SAFE_USERNAME = re.compile(r"^[a-zA-Z0-9_\-\.\$ ]+$")


class ACLError(Exception):
    """Raised when Windows ACL permission lockdown fails."""


def get_current_windows_user() -> str:
    """Retrieve current Windows username directly from kernel Win32 API.

    Guarantees:
    - Never reads os.environ['USERNAME'] to avoid shell variable spoofing.
    - Uses advapi32.GetUserNameW directly.
    """
    if sys.platform != "win32":
        raise ACLError("Windows ACL identity is only supported on Win32 OS.")

    advapi32 = getattr(ctypes.windll, "advapi32", None)
    if advapi32 is None:
        raise ACLError("Win32 advapi32 library is not accessible.")

    buffer = ctypes.create_unicode_buffer(256)
    size = wintypes.DWORD(256)

    success = advapi32.GetUserNameW(buffer, ctypes.byref(size))
    if not success:
        get_last_error = getattr(ctypes, "GetLastError", None)
        err_code = int(get_last_error()) if get_last_error is not None else 0
        raise ACLError(f"GetUserNameW failed with Win32 error: {err_code}")

    username = str(buffer.value).strip()
    if not username:
        raise ACLError("GetUserNameW returned an empty username string.")

    if not RE_SAFE_USERNAME.match(username):
        raise ValueError(
            f"Suspicious or insecure Windows username detected: {username!r}. "
            "Must match safe pattern ^[a-zA-Z0-9_\\-\\.\\$ ]+$"
        )

    return username


def lock_file_to_current_user(target_path: Path | str) -> bool:
    """Lock a file or directory so ONLY the current Windows user has Full Access (F).

    Enforces:
    - Removes inherited permissions (/inheritance:r).
    - Grants Full Control exclusively to current user (/grant:r <Username>:(F)).
    - Uses shell=False with argument list to eliminate command injection.
    - Gracefully returns False (no-op) on non-Windows platforms (e.g. Linux CI/CD).

    Args:
        target_path: Path to target file or directory.

    Returns:
        True if locked successfully on Windows, False if skipped on non-Windows.
    """
    if sys.platform != "win32":
        logger.debug("Skipping Windows ACL lockdown on non-Win32 platform (%s)", sys.platform)
        return False

    username = get_current_windows_user()
    if not RE_SAFE_USERNAME.match(username):
        raise ValueError(
            f"Suspicious or insecure Windows username detected: {username!r}. "
            "Must match safe pattern ^[a-zA-Z0-9_\\-\\.\\$ ]+$"
        )

    path = Path(target_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Target path for ACL lockdown does not exist: {path}")

    target_str = str(path)
    grant_spec = f"{username}:(F)"

    # Step 1: Strip inherited permissions
    # Command: icacls "<path>" /inheritance:r
    cmd_strip = ["icacls", target_str, "/inheritance:r"]
    try:
        res_strip = subprocess.run(
            cmd_strip,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug("icacls inheritance stripped: %s", res_strip.stdout.strip())
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ACLError(f"Failed to strip ACL inheritance on {target_str}: {exc}") from exc

    # Step 2: Grant Full Control exclusively to Current User
    # Command: icacls "<path>" /grant:r "<Username>:(F)"
    cmd_grant = ["icacls", target_str, "/grant:r", grant_spec]
    try:
        subprocess.run(
            cmd_grant,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("Successfully locked %s to user %s (ACL: Full Control)", target_str, username)
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.warning("Failed to grant exclusive ACL on %s: %s", target_str, exc)
        raise ACLError(f"Failed to grant exclusive ACL on {target_str} to {username}: {exc}") from exc

    return True


def lock_application_storage(base_dir: Path | str | None = None) -> list[Path]:
    """Lock down all sensitive databases, secrets, lockfiles, and logs to Current User.

    Args:
        base_dir: Root workspace directory (default: current working directory).

    Returns:
        List of paths that were locked.
    """
    if sys.platform != "win32":
        return []

    root = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    locked_paths: list[Path] = []

    # Target patterns
    patterns = [
        "data/*.db",
        "data/*.db-wal",
        "data/*.db-shm",
        "data/*.lock",
        "data/.secrets.enc",
        "logs/*.log",
    ]

    for pat in patterns:
        for match in root.glob(pat):
            if match.is_file():
                lock_file_to_current_user(match)
                locked_paths.append(match)

    return locked_paths
