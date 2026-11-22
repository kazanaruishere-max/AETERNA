# Verified Track Record

## Scope

This page records engineering verification for public releases. It does not record or imply trading profitability.

## What "Verified" Means

- Deterministic tests pass at a pinned commit.
- Numerical invariants match `docs/aeterna/invariant-cheatsheet.md`.
- Multi-stack checks pass with exact commands.
- Human-approved gates are named with date and commit.
- Evidence is reproducible from the public tag and `VERIFY.md`.

It does **not** mean: profitable, suitable for live capital, regulated, audited by a financial authority, or a signal service.

## Evidence Format

Each row should contain: UTC date · tag · commit SHA · exact command · exit code · artifact SHA256 · environment. Public rows omit account IDs, broker servers, tickets, balances, equity, PnL, and local paths.

## Gate Table — baseline `v0.1.0`

| Gate | Status | Baseline Evidence |
| :--- | :--- | :--- |
| `GATE-RUNTIME-LOOP-B` | PASSED | closed-bar M15 golden tests |
| `GATE-RUNTIME-VIRTUAL-TRACKER` | PASSED | 5-layer virtual exit tests |
| `GATE-NEWS-CALENDAR` | PASSED | source contract + UTC offset golden tests |
| `GATE-E2E-RUNTIME` | PASSED | runtime bootstrap E2E |
| `AUTO_READINESS` | PASS | deterministic one-command readiness harness |
| `GATE-M4` | PASSED | human approval 2026-11-21, commit `3561b95` |
| `GATE-M5` | PENDING | demo SL/TP evidence required |
| `GATE-VIRTUAL-JOURNAL` | QUEUED | 50–100 internal samples required |

## Command Evidence — baseline

```text
uv run pytest tests/ -q -> 354 passed
uv run pytest tests/runtime/test_news_sources.py -q -> 27 passed
uv run pytest tests/test_runtime_readiness_harness.py -q -> 8 passed
go test ./... -count=1 (engine/watchdog) -> ok
uv run ruff check . -> All checks passed!
uv run pyright -> 0 errors, 0 warnings, 0 informations
git diff --check -> clean
MQL5 ExportCalendar compile -> 0 errors, 0 warnings
CI public release baseline -> 7/7 SUCCESS
```

## Artifact Index

Release archives should include `SHA256SUMS`, `VERIFY.md`, `THIRD_PARTY_NOTICES.md`, and redacted gate reports. Artifact hashes are published on the GitHub release page for each tag.

## Corrections and History

Corrections are recorded in `CHANGELOG.md`. Historical internal audit files are not part of the public release; this page is the public-facing summary.

## Explicit Non-Claims

- No PnL, return, win rate, Sharpe ratio, drawdown result, or equity curve is published.
- No broker, account, ticket, Telegram admin ID, or server identifier is published.
- No claim that the strategy is profitable or suitable for live capital.
- No claim of regulatory audit or certification.
