"""Automated one-command runtime readiness verification harness.

Module: scripts.verify_runtime_readiness
Responsibility: Runs acceptance suite, dummy watchdog killswitch E2E, chart
                render/admin Telegram check, and generates audit Markdown report.
Owner: aeterna-security
Tier: Tier A
Covers: REQ-RUNTIME-009
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.analysis_engine.python.types import CandleDict
from engine.execution.emergency_handler import EmergencyHandler
from engine.runtime.chart_snapshot import render_ohlc_png
from engine.runtime.dashboard import ObservationCard, SignalOnlyDashboard

PROHIBITED_TOKENS: tuple[str, ...] = (
    "buy sekarang",
    "sell sekarang",
    "buy now",
    "sell now",
    "win rate",
    "pastikan untung",
    "garansi",
    "profit",
    "equity",
    "balance",
    "ticket",
    "server",
    "lot",
)


def _run_cmd(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str, float]:
    """Execute subprocess and return exit code, stdout, stderr, and elapsed seconds."""
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr, time.perf_counter() - t0


def _get_acceptance_commands(
    repo_root: Path,
) -> list[tuple[str, list[str], Path, dict[str, str] | None]]:
    """Return configured acceptance commands with their working directory and environment."""
    env = dict(os.environ, PYO3_PYTHON=sys.executable)
    return [
        (
            "uv run pytest tests/ -q",
            ["uv", "run", "pytest", "tests/", "-q"],
            repo_root,
            None,
        ),
        (
            "uv run pytest tests/e2e/test_runtime_bootstrap_e2e.py -v",
            ["uv", "run", "pytest", "tests/e2e/test_runtime_bootstrap_e2e.py", "-v"],
            repo_root,
            None,
        ),
        (
            "uv run pytest tests/test_emergency_handler.py -v",
            ["uv", "run", "pytest", "tests/test_emergency_handler.py", "-v"],
            repo_root,
            None,
        ),
        (
            "uv run pytest tests/test_runtime_readiness_harness.py -v",
            ["uv", "run", "pytest", "tests/test_runtime_readiness_harness.py", "-v"],
            repo_root,
            None,
        ),
        ("uv run ruff check .", ["uv", "run", "ruff", "check", "."], repo_root, None),
        ("uv run pyright", ["uv", "run", "pyright"], repo_root, None),
        (
            "go test -count=1 ./...",
            ["go", "test", "-count=1", "./..."],
            repo_root / "engine" / "watchdog",
            None,
        ),
        (
            "cargo test --all",
            ["cargo", "test", "--all"],
            repo_root / "engine" / "analysis_engine" / "rust",
            env,
        ),
        ("git diff --check", ["git", "diff", "--check"], repo_root, None),
    ]


def _run_acceptance_suite(repo_root: Path) -> tuple[bool, list[dict[str, Any]]]:
    """Run all mandatory acceptance commands and record raw exit codes and outputs."""
    commands = _get_acceptance_commands(repo_root)
    results: list[dict[str, Any]] = []
    all_passed = True
    for name, cmd, cwd, c_env in commands:
        code, out, err, sec = _run_cmd(cmd, cwd=cwd, env=c_env)
        passed = code == 0
        results.append(
            {
                "command": name,
                "exit_code": code,
                "stdout": out,
                "stderr": err,
                "duration_sec": round(sec, 2),
                "passed": passed,
            }
        )
        if not passed:
            all_passed = False
            break
    return all_passed, results


def _init_dummy_db(db_path: Path, schema_path: Path) -> None:
    """Initialize temporary database from schema.sql and seed baseline system_state."""
    schema_sql = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
        now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        seed_q = (
            "INSERT INTO system_state (id, state, current_spread, spread_baseline, "
            "spread_z_score, active_positions_count, equity_usd, daily_pnl_usd, "
            "trades_today_count, last_news_event, last_updated_utc) "
            "VALUES (1, 'NORMAL', 0.15, 0.15, 0.0, 0, 1000.0, 0.0, 0, NULL, ?)"
        )
        conn.execute(seed_q, (now_utc,))
        conn.commit()


def _http_request(
    url: str, method: str = "GET", payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute synchronous localhost HTTP request returning parsed JSON payload."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]


def _wait_for_watchdog(url: str, timeout_sec: float = 8.0) -> dict[str, Any]:
    """Poll watchdog /v1/status until ready or timeout expires."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            res = _http_request(url, method="GET")
            if res.get("status") == "RUNNING":
                return res
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.1)
    raise TimeoutError(f"Watchdog at {url} did not become ready within {timeout_sec}s")


def _build_watchdog_binary(repo_root: Path, bin_path: Path) -> None:
    """Compile Go watchdog binary into temporary destination."""
    code, out, err, _ = _run_cmd(
        ["go", "build", "-o", str(bin_path), "."], cwd=repo_root / "engine" / "watchdog"
    )
    if code != 0:
        raise RuntimeError(f"Failed to build watchdog binary: {err or out}")


def _validate_lockfile_payload(payload: dict[str, Any]) -> None:
    """Validate lockfile payload schema and reject fabricated financial metrics."""
    required = (
        "timestamp_utc",
        "trigger_reason",
        "peak_equity",
        "current_equity",
        "drawdown_pct",
    )
    for f in required:
        if f not in payload:
            raise AssertionError(f"Missing required lockfile field: {f}")
    if payload.get("equity_source") == "UNAVAILABLE":
        if payload.get("drawdown_pct") != 0.0:
            raise AssertionError(
                f"Fabricated drawdown detected: equity_source=UNAVAILABLE but drawdown_pct={payload.get('drawdown_pct')}"
            )
        if payload.get("current_equity") != 0.0:
            raise AssertionError(f"Fabricated equity detected: {payload}")


def _verify_killswitch_db_available(
    db_path: Path, lockfile_path: Path
) -> dict[str, Any]:
    """Verify DB-available scenario: persists PAUSED in DB and sets handler.is_paused=True."""
    from engine.shared.db.database import DatabaseManager

    db_mgr = DatabaseManager(db_path=str(db_path))
    db_mgr.init_db()

    handler = EmergencyHandler(
        db_manager=db_mgr,
        lockfile_path=lockfile_path,
        peak_equity=1000.0,
    )

    if not handler.execute_emergency_killswitch() or not lockfile_path.exists():
        raise RuntimeError(
            "EmergencyHandler failed to write lockfile in DB-available scenario"
        )

    if not handler.is_paused:
        raise AssertionError("Expected handler.is_paused=True when DB is available")

    state_rec = db_mgr.get_system_state()
    if state_rec is None or state_rec.state != "PAUSED":
        raise AssertionError(f"Expected DB state PAUSED, got: {state_rec}")

    payload = json.loads(lockfile_path.read_text(encoding="utf-8"))
    _validate_lockfile_payload(payload)

    return {
        "status": "PASS",
        "system_state": state_rec.state,
        "is_paused": handler.is_paused,
        "payload": payload,
    }


def _verify_killswitch_db_failed(lockfile_path: Path) -> dict[str, Any]:
    """Verify DB-failed scenario: lockfile written fail-closed, reported as PARTIAL/WARN."""
    handler = EmergencyHandler(
        lockfile_path=lockfile_path,
        db_manager="DB_INIT_FAILED",
        peak_equity=1000.0,
    )

    if not handler.execute_emergency_killswitch() or not lockfile_path.exists():
        raise RuntimeError(
            "EmergencyHandler failed to write lockfile in DB-failed scenario"
        )

    payload = json.loads(lockfile_path.read_text(encoding="utf-8"))
    _validate_lockfile_payload(payload)

    if handler.is_paused:
        raise AssertionError(
            "handler.is_paused must remain False when DB repository fails"
        )

    return {
        "status": "PARTIAL/WARN",
        "lockfile_written": True,
        "db_persisted": False,
        "is_paused": handler.is_paused,
        "payload": payload,
        "note": "Lockfile written fail-closed, DB state update skipped (DB unavailable)",
    }


def _stop_dummy_watchdog(proc: subprocess.Popen[bytes]) -> tuple[int, str]:
    """Safely terminate dummy watchdog process and return actual exit code and termination method."""
    if proc.poll() is not None:
        return proc.returncode, "already_stopped"
    proc.terminate()
    try:
        proc.wait(timeout=5.0)
        return proc.returncode if proc.returncode is not None else 0, "terminate()"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)
        return proc.returncode if proc.returncode is not None else -1, "kill()"


def _prepare_watchdog_env(
    repo_root: Path, tmp_dir: Path
) -> tuple[Path, Path, Path, Path]:
    """Initialize test directory, dummy db, PID file, and compiled watchdog binary."""
    data_dir = tmp_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "logs").mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "trading.db"
    pid_path = data_dir / "python_engine.pid"
    lockfile_path = data_dir / "EMERGENCY_KILLSWITCH.lock"
    bin_name = "watchdog.exe" if sys.platform == "win32" else "watchdog"
    bin_path = tmp_dir / bin_name

    _init_dummy_db(db_path, repo_root / "db" / "schema.sql")
    pid_path.write_text("999999\n", encoding="utf-8")
    _build_watchdog_binary(repo_root, bin_path)
    return bin_path, db_path, pid_path, lockfile_path


def _test_watchdog_gate_lifecycle(
    data_dir: Path, db_path: Path, lockfile_path: Path
) -> dict[str, Any]:
    """Execute pre-killswitch, killswitch triggers, and post-killswitch assertions."""
    status_init = _wait_for_watchdog("http://127.0.0.1:20130/v1/status")
    order = {
        "pair": "XAUUSDm",
        "direction": "BUY",
        "lot_size": 0.01,
        "entry_price": 2000.0,
        "sl_price": 1995.0,
        "account_equity": 1000.0,
    }
    res_before = _http_request(
        "http://127.0.0.1:20130/v1/validate_order", method="POST", payload=order
    )
    if not res_before.get("allowed"):
        raise AssertionError(f"Expected order allowed before killswitch: {res_before}")

    db_failed_summary = _verify_killswitch_db_failed(lockfile_path)
    res_after = _http_request(
        "http://127.0.0.1:20130/v1/validate_order", method="POST", payload=order
    )
    if (
        res_after.get("allowed")
        or res_after.get("reason") != "circuit_breaker_lock_active"
    ):
        raise AssertionError(f"Expected circuit_breaker_lock_active: {res_after}")

    status_after = _http_request("http://127.0.0.1:20130/v1/status", method="GET")
    if not status_after.get("killswitch_active"):
        raise AssertionError(f"Expected killswitch_active=True: {status_after}")

    db_avail_summary = _verify_killswitch_db_available(
        db_path, data_dir / "AVAIL_KILLSWITCH.lock"
    )
    return {
        "status_init": status_init,
        "order_before": res_before,
        "lockfile_payload": db_failed_summary["payload"],
        "order_after": res_after,
        "status_after": status_after,
        "db_avail": db_avail_summary,
        "db_failed": db_failed_summary,
    }


def _verify_dummy_watchdog(repo_root: Path, tmp_dir: Path) -> dict[str, Any]:
    """Run full dummy E2E test verifying order gating before and after killswitch."""
    bin_path, db_path, pid_path, lockfile_path = _prepare_watchdog_env(
        repo_root, tmp_dir
    )
    cmd = [
        str(bin_path),
        "-bind",
        "127.0.0.1:20130",
        "-db",
        str(db_path),
        "-pid-file",
        str(pid_path),
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(tmp_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    res: dict[str, Any] = {}
    try:
        res = _test_watchdog_gate_lifecycle(tmp_dir / "data", db_path, lockfile_path)
        res["watchdog_pid"] = proc.pid
    finally:
        exit_code, method = _stop_dummy_watchdog(proc)
        res["exit_code"] = exit_code
        res["termination_method"] = method
    return res


class _FakeTelegramTransport:
    """Mock Telegram client transport recording photo deliveries."""

    def __init__(self) -> None:
        self.photos: list[tuple[int, bytes, str]] = []

    def send_photo(self, chat_id: int, photo: bytes, caption: str) -> bool:
        self.photos.append((chat_id, photo, caption))
        return True

    def send(self, payload: dict[str, Any]) -> bool:
        return True


def _render_and_validate_png() -> bytes:
    """Render synthetic OHLC PNG and assert required PNG chunks and title marker."""
    candles: list[CandleDict] = [
        {
            "timestamp_utc": f"2026-11-20T12:{i * 15:02d}:00Z",
            "open": 2000.0 + i,
            "high": 2005.0 + i,
            "low": 1995.0 + i,
            "close": 2002.0 + i,
            "tick_volume": 100,
        }
        for i in range(10)
    ]
    png = render_ohlc_png(
        candles, zone_low=1995.0, zone_high=2008.0, invalidation_level=1990.0
    )
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("Missing PNG magic header")
    for chunk in (b"IHDR", b"IDAT", b"IEND", b"XAUUSD OBSERVATION"):
        if chunk not in png:
            raise AssertionError(f"Missing required marker {chunk!r}")
    return png


def _publish_and_validate_dashboard(png: bytes) -> dict[str, Any]:
    """Verify SignalOnlyDashboard publish to admin and strict non-admin rejection."""
    admin_id, fake = 999_000_001, _FakeTelegramTransport()
    dash = SignalOnlyDashboard(
        client=fake, admin_chat_id=admin_id, reasoning_enabled=False
    )
    card = ObservationCard(
        timestamp_utc="2026-11-20T12:00:00Z",
        symbol="XAUUSDm",
        regime_bias="RANGE_BOUND",
        zone_low=1995.0,
        zone_high=2008.0,
        invalidation_level=1990.0,
        liquidity_state="NORMAL",
        blackout_window=None,
        sample_count=10,
        reasoning=(
            "REGIME=RANGE_BOUND",
            "STRATEGY=volatility_breakout",
            "RR=2.00",
            "STATE=NORMAL",
            "NEWS=CLEAR",
        ),
    )
    if (
        not dash.publish_with_chart(card, photo=png, chat_id=admin_id)
        or len(fake.photos) != 1
    ):
        raise RuntimeError("Failed to publish chart to admin_chat_id")
    cid, sent_photo, caption = fake.photos[0]
    if cid != admin_id or sent_photo != png:
        raise AssertionError("Delivered photo or chat_id mismatch")
    if dash.publish_with_chart(card, photo=png, chat_id=admin_id + 1):
        raise AssertionError("Publish to non-admin unexpectedly allowed")
    lower_caption = caption.lower()
    for tok in PROHIBITED_TOKENS:
        if tok in lower_caption:
            raise AssertionError(
                f"Prohibited financial token {tok!r} detected in caption"
            )
    return {
        "admin_chat_id": admin_id,
        "photo_bytes_len": len(png),
        "caption_length": len(caption),
    }


def _verify_dummy_chart_and_dashboard() -> dict[str, Any]:
    """Render synthetic OHLC PNG and verify Telegram dashboard admin publication."""
    png = _render_and_validate_png()
    return _publish_and_validate_dashboard(png)


def _format_acceptance_section(
    acceptance_results: list[dict[str, Any]],
) -> list[str]:
    """Format markdown table for acceptance command results."""
    lines = [
        "## 1. Acceptance Commands Matrix\n",
        "| Command | Exit Code | Duration (s) | Status |",
        "| :--- | :---: | :---: | :---: |",
    ]
    for it in acceptance_results:
        tag = "PASS" if it["passed"] else "**FAIL**"
        lines.append(
            f"| `{it['command']}` | `{it['exit_code']}` | {it['duration_sec']} | {tag} |"
        )
    return lines


def _format_watchdog_section(
    watchdog_summary: dict[str, Any] | None,
) -> list[str]:
    """Format dummy watchdog E2E execution results without hardcoded status."""
    lines = ["\n## 2. Dummy Watchdog Fail-Closed E2E\n"]
    if watchdog_summary is None:
        lines.append("- *Watchdog E2E skipped or failed prior to completion.*")
        return lines

    code = watchdog_summary.get("exit_code", 0)
    method = watchdog_summary.get("termination_method", "unknown")
    lines.extend(
        [
            f"- Watchdog Process: PID `{watchdog_summary['watchdog_pid']}` (exit_code={code}, termination_method=`{method}`)",
            f"- Pre-Killswitch Order Check: `allowed={watchdog_summary['order_before'].get('allowed')}` (reason: `{watchdog_summary['order_before'].get('reason')}`)",
            f"- Emergency Lockfile Payload: `{json.dumps(watchdog_summary['lockfile_payload'])}`",
            f"- Post-Killswitch Order Check: `allowed={watchdog_summary['order_after'].get('allowed')}` (reason: `{watchdog_summary['order_after'].get('reason')}`)",
            f"- Post-Killswitch Daemon Health: `killswitch_active={watchdog_summary['status_after'].get('killswitch_active')}`",
        ]
    )
    if "db_avail" in watchdog_summary:
        rec = watchdog_summary["db_avail"]
        status = rec.get("status", "UNKNOWN")
        lines.append(
            f"- DB Available Persistence: `system_state={rec.get('system_state')}`, `handler.is_paused={rec.get('is_paused')}` (Status: {status})"
        )
    if "db_failed" in watchdog_summary:
        rec = watchdog_summary["db_failed"]
        status = rec.get("status", "UNKNOWN")
        note = rec.get("note")
        note_str = f" - {note}" if note else ""
        lines.append(
            f"- DB Failed Persistence: `lockfile_written={rec.get('lockfile_written')}`, `db_persisted={rec.get('db_persisted')}` (Status: {status}{note_str})"
        )
    return lines


def _format_chart_section(chart_summary: dict[str, Any] | None) -> list[str]:
    """Format dummy chart and Telegram publication check results."""
    lines = ["\n## 3. Dummy Chart & Admin Observation Card\n"]
    if chart_summary is not None:
        lines.extend(
            [
                f"- Rendered PNG Size: `{chart_summary['photo_bytes_len']}` bytes with verified magic and metadata title",
                f"- Admin Transport Delivery: Sent to whitelist chat ID `{chart_summary['admin_chat_id']}`",
                "- Admin Whitelist Security: Non-admin publish attempt strictly rejected",
                "- Caption Purity: All financial and trading instruction tokens confirmed absent",
            ]
        )
    else:
        lines.append("- *Chart verification skipped or failed prior to completion.*")
    return lines


def _build_markdown_report(
    commit_hash: str,
    acceptance_results: list[dict[str, Any]],
    watchdog_summary: dict[str, Any] | None,
    chart_summary: dict[str, Any] | None,
    verdict: str,
) -> str:
    """Format final audit report in GitHub-flavored Markdown."""
    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# AETERNA Runtime Readiness Verification Report\n",
        f"- **Timestamp (UTC)**: `{now_utc}`",
        f"- **Git Commit**: `{commit_hash}`",
        f"- **Final Verdict**: **`{verdict}`**\n",
    ]
    lines.extend(_format_acceptance_section(acceptance_results))
    lines.extend(_format_watchdog_section(watchdog_summary))
    lines.extend(_format_chart_section(chart_summary))
    lines.extend(["\n## 4. Verdict Summary\n", f"**`{verdict}`**\n"])
    return "\n".join(lines)


def _get_current_git_commit(repo_root: Path) -> str:
    """Resolve current Git commit hash of HEAD deterministically."""
    c_res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return c_res.stdout.strip() if c_res.returncode == 0 else "UNKNOWN"


def _run_readiness_checks(
    repo_root: Path,
) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Execute acceptance suite, dummy watchdog E2E, and chart dashboard checks."""
    watchdog_summary: dict[str, Any] | None = None
    chart_summary: dict[str, Any] | None = None
    all_passed, acceptance_results = _run_acceptance_suite(repo_root)

    if all_passed:
        try:
            with tempfile.TemporaryDirectory() as tmp_str:
                watchdog_summary = _verify_dummy_watchdog(repo_root, Path(tmp_str))
            chart_summary = _verify_dummy_chart_and_dashboard()
        except (
            RuntimeError,
            OSError,
            ValueError,
            TypeError,
            AssertionError,
            sqlite3.Error,
            TimeoutError,
        ) as exc:
            all_passed = False
            sys.stderr.write(f"Readiness verification error: {exc}\n")

    return all_passed, acceptance_results, watchdog_summary, chart_summary


def main(argv: list[str] | None = None) -> int:
    """Parse CLI options, execute verification harness, write report, and exit."""
    parser = argparse.ArgumentParser(
        description="AETERNA Runtime Readiness Verification Harness"
    )
    parser.add_argument(
        "--out",
        default=".handoff/e2e/AUTO_READINESS-LAST.md",
        help="Target Markdown report path",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    commit_hash = _get_current_git_commit(repo_root)
    all_passed, acceptance_results, watchdog_summary, chart_summary = (
        _run_readiness_checks(repo_root)
    )

    verdict = "AUTO_READINESS_PASS" if all_passed else "AUTO_READINESS_FAIL"
    report = _build_markdown_report(
        commit_hash, acceptance_results, watchdog_summary, chart_summary, verdict
    )

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    sys.stdout.write(
        f"\nRuntime Readiness Verdict: {verdict}\nReport written to: {out_path}\n"
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
