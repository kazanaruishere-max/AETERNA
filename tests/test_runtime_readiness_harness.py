"""Unit tests for runtime readiness verification harness.

Module: tests.test_runtime_readiness_harness
Responsibility: Verifies readiness harness guards:
1. Valid lockfile payload with UNAVAILABLE equity passes validation.
2. Fabricated lockfile payload with UNAVAILABLE + non-zero drawdown is rejected.
3. Non-UNAVAILABLE equity payload does not enforce zero drawdown.
4. Missing required payload fields raise AssertionError.
5. All functions in scripts/verify_runtime_readiness.py remain strictly < 50 lines.
6. Markdown report formats dynamic status and termination method without hardcoding.
Covers: REQ-RUNTIME-009
Owner: aeterna-verifier
Tier: Tier A
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from scripts.verify_runtime_readiness import (
    _build_markdown_report,
    _format_watchdog_section,
    _validate_lockfile_payload,
)


def test_validate_lockfile_payload_unavailable_valid() -> None:
    """Verify lockfile payload with UNAVAILABLE equity and 0.0 drawdown is accepted."""
    payload: dict[str, Any] = {
        "timestamp_utc": "2026-11-20T12:00:00+00:00",
        "trigger_reason": "MANUAL_TELEGRAM_KILLSWITCH",
        "peak_equity": 1000.0,
        "current_equity": 0.0,
        "drawdown_pct": 0.0,
        "equity_source": "UNAVAILABLE",
    }
    # Should execute cleanly without raising AssertionError
    _validate_lockfile_payload(payload)


def test_validate_lockfile_payload_rejects_fabricated_drawdown() -> None:
    """Verify lockfile payload with UNAVAILABLE equity and non-zero drawdown is rejected."""
    payload: dict[str, Any] = {
        "timestamp_utc": "2026-11-20T12:00:00+00:00",
        "trigger_reason": "MANUAL_TELEGRAM_KILLSWITCH",
        "peak_equity": 1000.0,
        "current_equity": 0.0,
        "drawdown_pct": 100.0,
        "equity_source": "UNAVAILABLE",
    }
    with pytest.raises(AssertionError, match="Fabricated drawdown detected"):
        _validate_lockfile_payload(payload)


def test_validate_lockfile_payload_rejects_fabricated_equity() -> None:
    """Verify lockfile payload with UNAVAILABLE equity and non-zero current_equity is rejected."""
    payload: dict[str, Any] = {
        "timestamp_utc": "2026-11-20T12:00:00+00:00",
        "trigger_reason": "MANUAL_TELEGRAM_KILLSWITCH",
        "peak_equity": 1000.0,
        "current_equity": 500.0,
        "drawdown_pct": 0.0,
        "equity_source": "UNAVAILABLE",
    }
    with pytest.raises(AssertionError, match="Fabricated equity detected"):
        _validate_lockfile_payload(payload)


def test_validate_lockfile_payload_available_equity_allows_drawdown() -> None:
    """Verify payload with available equity (not UNAVAILABLE) allows real drawdown."""
    payload: dict[str, Any] = {
        "timestamp_utc": "2026-11-20T12:00:00+00:00",
        "trigger_reason": "MAX_DRAWDOWN_BREACH",
        "peak_equity": 1000.0,
        "current_equity": 850.0,
        "drawdown_pct": 15.0,
        "equity_source": "EXNESS_MT5",
    }
    # Should execute cleanly without raising AssertionError
    _validate_lockfile_payload(payload)


def test_validate_lockfile_payload_missing_required_field() -> None:
    """Verify missing required lockfile field raises AssertionError."""
    payload: dict[str, Any] = {
        "timestamp_utc": "2026-11-20T12:00:00+00:00",
        "trigger_reason": "MANUAL_TELEGRAM_KILLSWITCH",
        "peak_equity": 1000.0,
        "current_equity": 0.0,
        # drawdown_pct is missing
        "equity_source": "UNAVAILABLE",
    }
    with pytest.raises(AssertionError, match="Missing required lockfile field"):
        _validate_lockfile_payload(payload)


def test_all_functions_in_readiness_script_under_50_lines() -> None:
    """Permanently enforce that every function in scripts/verify_runtime_readiness.py is < 50 lines."""
    script_path = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "verify_runtime_readiness.py"
    )
    assert script_path.exists(), f"Script not found at {script_path}"
    tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))

    oversized: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            line_count = end - node.lineno + 1
            if line_count >= 50:
                oversized.append((node.name, line_count))

    assert not oversized, (
        f"Functions exceeding 49 lines found in verify_runtime_readiness.py: {oversized}"
    )


def test_format_watchdog_section_dynamic_status_and_termination() -> None:
    """Verify watchdog section formats dynamic status and actual termination method."""
    summary: dict[str, Any] = {
        "watchdog_pid": 12345,
        "exit_code": 0,
        "termination_method": "terminate()",
        "order_before": {"allowed": True, "reason": "OK"},
        "lockfile_payload": {"test": 1},
        "order_after": {
            "allowed": False,
            "reason": "circuit_breaker_lock_active",
        },
        "status_after": {"killswitch_active": True},
        "db_avail": {
            "status": "CUSTOM_PASS_STATUS",
            "system_state": "PAUSED",
            "is_paused": True,
        },
        "db_failed": {
            "status": "CUSTOM_WARN_STATUS",
            "lockfile_written": True,
            "db_persisted": False,
            "note": "degraded test note",
        },
    }
    lines = _format_watchdog_section(summary)
    full_text = "\n".join(lines)

    assert "termination_method=`terminate()`" in full_text
    assert "(Status: CUSTOM_PASS_STATUS)" in full_text
    assert "(Status: CUSTOM_WARN_STATUS - degraded test note)" in full_text
    assert "(Status: PASS)" not in full_text  # confirms not hardcoded


def test_build_markdown_report_includes_commit_and_verdict() -> None:
    """Verify build_markdown_report correctly formats commit, verdict, and sections."""
    commit = "a1b2c3d4e5f67890"
    verdict = "AUTO_READINESS_PASS"
    report = _build_markdown_report(
        commit_hash=commit,
        acceptance_results=[
            {
                "command": "cmd1",
                "exit_code": 0,
                "duration_sec": 0.5,
                "passed": True,
            }
        ],
        watchdog_summary=None,
        chart_summary=None,
        verdict=verdict,
    )
    assert f"- **Git Commit**: `{commit}`" in report
    assert f"- **Final Verdict**: **`{verdict}`**" in report
    assert "| `cmd1` | `0` | 0.5 | PASS |" in report
