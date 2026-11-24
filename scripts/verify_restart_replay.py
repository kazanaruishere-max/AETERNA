"""Module: scripts.verify_restart_replay
Responsibility: Read-only CLI tool to inspect downtime gap status from bar_cursors and system_state.
Owner: aeterna-security
Tier: Tier A
Covers: REQ-RUNTIME-011
"""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from engine.models import BarCursorRecord, Timeframe
from engine.runtime.restart_replay import (
    DEFAULT_CANONICAL_CONFIG_PATH,
    RESTART_REPLAY_MAX_BARS_APPROVED,
    compute_config_hash,
    detect_gap,
)

logger = logging.getLogger("aeterna.scripts.verify_restart_replay")


def _iso_utc(ts: float | None) -> str:
    """Format epoch timestamp as ISO UTC string."""
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_readonly_connection(db_path: Path) -> sqlite3.Connection:
    """Open a strictly read-only SQLite connection using URI mode."""
    if not db_path.is_file():
        raise FileNotFoundError(f"Database file does not exist: {db_path}")
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _read_bar_cursor(
    conn: sqlite3.Connection, symbol: str, timeframe: str
) -> BarCursorRecord | None:
    """Fetch bar cursor row without modifying database state."""
    query = """
        SELECT symbol, timeframe, last_closed_bar_ts, updated_at_ms, config_hash
        FROM bar_cursors
        WHERE symbol = ? AND timeframe = ?
    """
    try:
        cur = conn.execute(query, (symbol, timeframe))
        row = cur.fetchone()
        if not row:
            return None
        return BarCursorRecord(
            symbol=str(row[0]),
            timeframe=cast(Timeframe, str(row[1])),
            last_closed_bar_ts=int(row[2]),
            updated_at_ms=int(row[3]),
            config_hash=str(row[4]) if row[4] is not None else None,
        )
    except sqlite3.OperationalError:
        return None


def _read_system_state(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Fetch current system_state row without modifying database state."""
    query = """
        SELECT state, current_spread, spread_baseline, spread_z_score,
               active_positions_count, equity_usd, daily_pnl_usd,
               trades_today_count, last_news_event, last_updated_utc
        FROM system_state
        WHERE id = 1
    """
    try:
        cur = conn.execute(query)
        row = cur.fetchone()
        if not row:
            return None
        return {
            "state": str(row[0]),
            "current_spread": float(row[1]),
            "spread_baseline": float(row[2]),
            "spread_z_score": float(row[3]),
            "active_positions_count": int(row[4]),
            "equity_usd": float(row[5]),
            "daily_pnl_usd": float(row[6]),
            "trades_today_count": int(row[7]),
            "last_news_event": str(row[8]) if row[8] else None,
            "last_updated_utc": str(row[9]),
        }
    except sqlite3.OperationalError:
        return None


def _read_latest_replay_run(
    conn: sqlite3.Connection, symbol: str
) -> dict[str, Any] | None:
    """Fetch the latest replay run record for auditing."""
    query = """
        SELECT replay_id, status, missed_count, started_at_utc, finished_at_utc,
               observations_created, blocked_created, error_text
        FROM replay_runs
        WHERE symbol = ?
        ORDER BY started_at_utc DESC
        LIMIT 1
    """
    try:
        cur = conn.execute(query, (symbol,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "replay_id": str(row[0]),
            "status": str(row[1]),
            "missed_count": int(row[2]),
            "started_at_utc": str(row[3]),
            "finished_at_utc": str(row[4]) if row[4] else None,
            "observations_created": int(row[5]),
            "blocked_created": int(row[6]),
            "error_text": str(row[7]) if row[7] else None,
        }
    except sqlite3.OperationalError:
        return None


def inspect_gap_status(
    db_path: str | Path,
    symbol: str = "XAUUSDm",
    timeframe: str = "M15",
    now_utc: float | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute pure read-only gap inspection across bar_cursors and system_state."""
    target_db = Path(db_path)
    now_ts = float(time.time() if now_utc is None else now_utc)

    resolved_config = Path(config_path) if config_path else DEFAULT_CANONICAL_CONFIG_PATH
    current_hash = (
        compute_config_hash(resolved_config) if resolved_config.is_file() else "UNKNOWN"
    )

    if not target_db.is_file():
        return {
            "error": f"Database file not found: {target_db}",
            "status": "DB_NOT_FOUND",
            "db_path": str(target_db),
            "safety_assertions": {
                "read_only": True,
                "db_mutations": 0,
                "mt5_orders": 0,
                "port_20128_contacted": False,
            },
        }

    with _get_readonly_connection(target_db) as conn:
        cursor = _read_bar_cursor(conn, symbol, timeframe)
        sys_state = _read_system_state(conn)
        latest_run = _read_latest_replay_run(conn, symbol)

    detection = detect_gap(
        now_utc=now_ts,
        last_cursor=cursor,
        current_config_hash=current_hash,
        max_replay_bars=RESTART_REPLAY_MAX_BARS_APPROVED,
    )

    return {
        "db_path": str(target_db),
        "symbol": symbol,
        "timeframe": timeframe,
        "inspection_utc": _iso_utc(now_ts),
        "inspection_epoch": int(now_ts),
        "current_closed_bar_ts": detection.current_closed_bar_ts,
        "current_closed_bar_utc": _iso_utc(detection.current_closed_bar_ts),
        "config_hash": current_hash,
        "gap_detection": {
            "status": detection.status.value,
            "missed_count": detection.missed_count,
            "first_missed_bar_ts": detection.first_missed_bar_ts,
            "first_missed_bar_utc": _iso_utc(detection.first_missed_bar_ts),
            "last_missed_bar_ts": detection.last_missed_bar_ts,
            "last_missed_bar_utc": _iso_utc(detection.last_missed_bar_ts),
            "error_text": detection.error_text,
        },
        "bar_cursor": {
            "exists": cursor is not None,
            "last_closed_bar_ts": cursor.last_closed_bar_ts if cursor else None,
            "last_closed_bar_utc": _iso_utc(cursor.last_closed_bar_ts) if cursor else None,
            "cursor_config_hash": cursor.config_hash if cursor else None,
            "updated_at_ms": cursor.updated_at_ms if cursor else None,
        },
        "system_state": sys_state,
        "latest_replay_run": latest_run,
        "safety_assertions": {
            "read_only": True,
            "db_mutations": 0,
            "mt5_orders": 0,
            "port_20128_contacted": False,
        },
    }


def format_text_report(data: dict[str, Any]) -> str:
    """Format inspection result as human-readable text."""
    if "error" in data:
        return f"[ERROR] {data['error']}"

    gap = data["gap_detection"]
    cur = data["bar_cursor"]
    st = data["system_state"]
    run = data["latest_replay_run"]

    lines = [
        "=" * 78,
        "AETERNA RESTART GAP & SYSTEM STATE VERIFICATION (READ-ONLY)",
        "=" * 78,
        f"Database Path:   {data['db_path']}",
        f"Symbol / TF:     {data['symbol']} / {data['timeframe']}",
        f"Inspection Time: {data['inspection_utc']} (Epoch: {data['inspection_epoch']})",
        f"Current Closed:  {data['current_closed_bar_utc']} (TS: {data['current_closed_bar_ts']})",
        f"Config Hash:     {data['config_hash']}",
        "-" * 78,
        "[BAR CURSOR]",
        f"  Cursor Exists: {cur['exists']}",
        f"  Last Closed:   {cur['last_closed_bar_utc']} (TS: {cur['last_closed_bar_ts']})",
        f"  Config Hash:   {cur['cursor_config_hash']}",
        f"  Updated (ms):  {cur['updated_at_ms']}",
        "-" * 78,
        "[SYSTEM STATE]",
    ]

    if st:
        lines.extend([
            f"  State:         {st['state']}",
            f"  Spread:        {st['current_spread']:.2f} pts (Baseline: {st['spread_baseline']:.2f} pts)",
            f"  Spread Z-Score:{st['spread_z_score']:.2f}",
            f"  Active Pos:    {st['active_positions_count']}",
            f"  Trades Today:  {st['trades_today_count']}",
            f"  Updated UTC:   {st['last_updated_utc']}",
        ])
    else:
        lines.append("  System State:  NONE (table empty or uninitialized)")

    lines.extend([
        "-" * 78,
        "[GAP STATUS]",
        f"  Status:        {gap['status']}",
        f"  Missed Bars:   {gap['missed_count']}",
        f"  First Missed:  {gap['first_missed_bar_utc']} (TS: {gap['first_missed_bar_ts']})",
        f"  Last Missed:   {gap['last_missed_bar_utc']} (TS: {gap['last_missed_bar_ts']})",
    ])
    if gap.get("error_text"):
        lines.append(f"  Error Detail:  {gap['error_text']}")

    lines.extend([
        "-" * 78,
        "[LATEST REPLAY RUN]",
    ])
    if run:
        lines.extend([
            f"  Replay ID:     {run['replay_id']}",
            f"  Status:        {run['status']}",
            f"  Missed/Obs/Blk:{run['missed_count']} / {run['observations_created']} / {run['blocked_created']}",
            f"  Started UTC:   {run['started_at_utc']}",
            f"  Finished UTC:  {run['finished_at_utc']}",
        ])
    else:
        lines.append("  Replay Runs:   NONE")

    lines.extend([
        "-" * 78,
        "[SAFETY INVARIANTS]",
        "  Read-Only Mode:       VERIFIED (mode=ro)",
        "  Live DB Mutations:    0 (strictly read-only queries)",
        "  MT5 Order Requests:   0 (no order endpoints touched)",
        "  9router Port 20128:   UNTOUCHED (zero traffic sent)",
        "=" * 78,
    ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser."""
    parser = argparse.ArgumentParser(
        description="Read-only AETERNA downtime gap verification utility."
    )
    parser.add_argument(
        "--db-path",
        default="data/trading.db",
        help="Path to SQLite trading database (default: data/trading.db)",
    )
    parser.add_argument(
        "--symbol",
        default="XAUUSDm",
        help="Instrument symbol (default: XAUUSDm)",
    )
    parser.add_argument(
        "--timeframe",
        default="M15",
        help="Target timeframe (default: M15)",
    )
    parser.add_argument(
        "--now-utc",
        type=float,
        default=None,
        help="Override evaluation epoch timestamp (for testing/auditing)",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Path to canonical parameters YAML for config_hash verification",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report in JSON format",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    report = inspect_gap_status(
        db_path=args.db_path,
        symbol=args.symbol,
        timeframe=args.timeframe,
        now_utc=args.now_utc,
        config_path=args.config_path,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text_report(report))

    if "error" in report:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
