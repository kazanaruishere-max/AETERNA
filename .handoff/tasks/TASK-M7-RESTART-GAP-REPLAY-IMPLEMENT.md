# TASK-M7-RESTART-GAP-REPLAY-IMPLEMENT

metadata:
  task_id: TASK-M7-RESTART-GAP-REPLAY-IMPLEMENT
  protocol: aeterna-task-protocol
  protocol_version: "2.0.0"
  tier: A
  target_milestone: M7/P1
  target_branch: feat/m7-restart-gap-replay
  covers_req: [REQ-RUNTIME-001, REQ-RUNTIME-003, REQ-RUNTIME-011]
  depends_on: [TASK-M7-RESTART-GAP-REPLAY-CONTRACT]
  base_commit: d47e0a2
  builder_harness: any
  status: BLOCKED
  approval: PENDING_CONTRACT_APPROVAL

---

## 0. PROMPT — IMPLEMENTATION (JANGAN JALANKAN DULU)

```text
You are an AETERNA builder operating under aeterna-task-protocol.

STOP unless all true:
1. TASK-M7-RESTART-GAP-REPLAY-CONTRACT is merged.
2. Operator has approved REQ-RUNTIME-011.
3. Schema Contract PR is merged.
4. You have an explicit task packet for the sub-phase you are executing.
5. active_task is not null and allowed_paths match.

Do not implement the whole feature in one PR. Split into three sequential sub-packets:

A. DATA
   - db/schema.sql
   - engine/models/__init__.py
   - engine/shared/db/database.py
   Tests: tests/test_database.py
   Deliverable: replay_runs + origin/replay_id/config_hash columns + repository methods.

B. ENGINE
   - engine/runtime/restart_replay.py (new)
   - engine/runtime/bootstrap.py
   - tests/runtime/test_restart_replay.py (new)
   Deliverable: gap detection, sequential replay, cursor-after-success, fail-closed.

C. E2E
   - tests/e2e/test_runtime_restart_replay_e2e.py (new)
   - scripts/verify_restart_replay.py (new)
   - docs/aeterna/runbook-beta.md
   Deliverable: stop/restart drill, no duplicates, no live-state mutation, Telegram summary.

Hard constraints:
- SIGNAL_ONLY / LIVE_ORDER=DISABLED.
- Zero LLM production.
- No order_send / PositionModify.
- No gh pr merge / git merge.
- No 9router port 20128.
- No live-state mutation.
- No public/VIP alert.
- Replay observations origin=REPLAY and not counted as live sample.
- Zero lookahead: M15 <= bar_ts; H4 fully closed at bar_ts.
- Cursor advances only after successful bar.
- Fail closed on NO_BASELINE, GAP_TOO_LARGE, CONFIG_DRIFT, missing candles.

Required tests (from PLAN-08):
1. no gap when cursor current
2. gap math exact three bars
3. no baseline does not replay blindly
4. gap too large blocks
5. config drift blocks
6. replay oldest to newest
7. replay idempotent on second restart
8. crash mid-replay resumes at last success
9. replay does not mutate live system_state
10. replay marks origin=REPLAY
11. replay does not send live OBSERVATION alert
12. zero lookahead H4 cutoff
13. missing candles blocks, not skips
14. blocked signals deduped
15. replay summary counts

Acceptance:
uv run pytest tests/runtime/test_restart_replay.py -q
uv run pytest tests/e2e/test_runtime_restart_replay_e2e.py -q
uv run pytest tests/ -q
uv run ruff check .
uv run pyright
git diff --check

Report raw output. Stop after PR. Merge manual.
```

---

## 1. Preconditions

- Contract merged.
- `REQ-RUNTIME-011` approved.
- Schema migration approved.
- Operator explicitly assigns `active_task`.
- `RESTART_REPLAY_MAX_BARS` decided.
- `RESTART_REPLAY_MODE` decided.

---

## 2. Forbidden

- One-shot implementation across schema + engine + e2e.
- Replay classified as LIVE.
- Replay sending public/live OBSERVATION.
- Replay writing live `system_state`.
- Replay with config drift.
- Any order or merge automation.

---

## 3. Cheapest Falsification

Before writing code, run a read-only dry-run:

```text
1. Read bar_cursors + system_state.
2. Compute missed bars.
3. Verify M15/H4 candles for each missed bar exist.
4. Verify no config drift.
5. If any check fails, do not implement.
```

---

## 4. Explicit Non-Authorization

File ini BLOCKED. Bukan izin implementasi sampai contract PR dan operator approval selesai.
