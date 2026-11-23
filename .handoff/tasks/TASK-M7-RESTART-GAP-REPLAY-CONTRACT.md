# TASK-M7-RESTART-GAP-REPLAY-CONTRACT

metadata:
  task_id: TASK-M7-RESTART-GAP-REPLAY-CONTRACT
  protocol: aeterna-task-protocol
  protocol_version: "2.0.0"
  tier: A
  target_milestone: M7/P1
  target_branch: feat/m7-restart-gap-replay-contract
  covers_req: [REQ-RUNTIME-001, REQ-RUNTIME-003]
  depends_on: []
  base_commit: d47e0a2
  builder_harness: any
  status: DRAFT
  approval: PENDING_OPERATOR

---

## 0. PROMPT — COPY/PASTE KE BUILDER

```text
You are an AETERNA builder operating under aeterna-task-protocol.

Read first:
1. AGENTS.md
2. docs/aeterna/agent-state.md
3. docs/aeterna/invariant-cheatsheet.md
4. docs/aeterna/AUTONOMOUS_BUILDER.md
5. docs/aeterna/task-packet-template.md
6. .handoff/plans/PLAN-08-RESTART-GAP-REPLAY.md
7. this task packet

Task: produce the CONTRACT PHASE ONLY for automatic restart gap detection/replay.

Hard constraints:
- Do NOT write runtime code.
- Do NOT modify db/schema.sql yet.
- Do NOT modify engine/runtime/*.
- Do NOT implement replay.
- Do NOT touch order_send / PositionModify / 9router port 20128.
- Do NOT gh pr merge / git merge.
- Do NOT add dependencies.
- Do NOT put account IDs, tokens, or credentials in docs/tests.

Deliverable:
1. docs/aeterna/restart-gap-replay-contract.md
2. update docs/aeterna/requirements.md with a proposed REQ-RUNTIME-011 (status DRAFT)
3. open a PR with the contract only, then STOP.

The contract must specify:
- gap detection formula and edge cases
- replay ordering and idempotency
- LIVE vs REPLAY provenance
- config_hash / strategy_id / model_id checkpointing
- phase 1 STRATEGY_ONLY semantics
- why full state replay is not claimed
- schema DDL proposal (but do not apply it)
- max_replay_bars as an operator decision, no invented default
- Telegram summary-only behavior
- 15 required tests from PLAN-08
- fail-closed behavior
- explicit non-authorization

Verification:
uv run pytest tests/ -q
uv run ruff check .
uv run pyright
git diff --check

Report raw output and stop after PR.
```

---

## 1. Required Reading

1. `AGENTS.md`
2. `docs/aeterna/agent-state.md`
3. `docs/aeterna/invariant-cheatsheet.md`
4. `docs/aeterna/AUTONOMOUS_BUILDER.md`
5. `docs/aeterna/task-packet-template.md`
6. `.handoff/plans/PLAN-08-RESTART-GAP-REPLAY.md`
7. `.handoff/tasks/TASK-M7-RESTART-GAP-REPLAY-CONTRACT.md`

---

## 2. Scope File — Phase 0 Only

- `docs/aeterna/restart-gap-replay-contract.md` (new)
- `docs/aeterna/requirements.md`

Maksimal 2 file. Tidak ada file runtime.

---

## 3. Forbidden Scope

- `db/schema.sql`
- `engine/**`
- `tests/**` kecuali tidak ada perubahan test pada phase ini
- `.env`, secret, account ID, Telegram admin ID
- `order_send`, `PositionModify`, `gh pr merge`, `git merge`
- port 20128 / 9router

---

## 4. Requirements

1. Contract harus mendefinisikan gap:
   ```text
   current_closed = floor(now/900)*900 - 900
   first_missed = last_cursor + 900
   last_missed = current_closed
   missed_count = ((last_missed - first_missed)/900) + 1
   ```
2. Contract harus mendefinisikan `NO_BASELINE`, `NO_GAP`, `GAP_TOO_LARGE`, `CONFIG_DRIFT`.
3. Contract harus memisahkan `origin=LIVE` dan `origin=REPLAY`.
4. Contract harus menyatakan replay phase 1 = `STRATEGY_ONLY`; live state machine tidak diklaim historis.
5. Contract harus memuat DDL proposal untuk `replay_runs` dan kolom `origin`, `replay_id`, `config_hash`.
6. Contract harus menyatakan replay observations tidak dihitung sebagai sampel live.
7. Contract harus menyatakan replay tidak mengirim OBSERVATION live; hanya satu ringkasan admin.
8. Contract harus menyatakan cursor advance hanya setelah bar sukses.
9. Contract harus menyatakan `RESTART_REPLAY_MAX_BARS` adalah open decision operator.
10. Contract harus menyatakan fail-closed jika data/candle tidak lengkap.
11. Contract harus menambahkan `REQ-RUNTIME-011` sebagai `DRAFT`, bukan `VERIFIED`.
12. Contract harus memuat 15 acceptance tests dari PLAN-08 §13.

---

## 5. RTM

| REQ ID | Deliverable | Target |
| :--- | :--- | :--- |
| `REQ-RUNTIME-001` | schema contract proposal | audit-safe replay tables |
| `REQ-RUNTIME-003` | restart-safe cursor extension | gap replay semantics |
| `REQ-RUNTIME-011` | new DRAFT requirement | implementation gate |

---

## 6. Hard Invariants

- Zero LLM production.
- SIGNAL_ONLY.
- 0.5% risk / 2.0% daily loss / 10.0% DD.
- 1 posisi / 5 trade/hari / R:R 2.0.
- Exit 5 lapis.
- Do Not Kill port 20128.
- No order live.

---

## 7. Test Matrix — Phase 0

Phase 0 tidak mengubah kode. Verifikasi hanya:

```powershell
uv run pytest tests/ -q
uv run ruff check .
uv run pyright
git diff --check
```

Tidak boleh mengklaim replay PASS. Yang diverifikasi hanya kontrak dan tidak ada regresi.

---

## 8. Acceptance Commands

```powershell
uv run pytest tests/ -q
uv run ruff check .
uv run pyright
git diff --check
```

---

## 9. Git Protocol

```powershell
git checkout -b feat/m7-restart-gap-replay-contract d47e0a2
# edit contract files only
git add docs/aeterna/restart-gap-replay-contract.md docs/aeterna/requirements.md
git commit -m "docs(runtime): define restart gap replay contract"
git push -u origin feat/m7-restart-gap-replay-contract
gh pr create --title "docs(runtime): define restart gap replay contract" --body "<report-back>"
```

STOP setelah PR. Merge manual oleh operator.

---

## 10. Report-Back Contract

Wajib melaporkan:

1. file yang diubah/dibuat,
2. `skills_loaded` atau `fallback_docs_read`,
3. `builder_harness`,
4. raw output verifikasi,
5. daftar open decisions,
6. nomor PR.

---

## 11. Abort Conditions

- Ada dorongan untuk mengubah schema/runtime.
- `RESTART_REPLAY_MAX_BARS` diisi tanpa keputusan operator.
- Replay diklaim ekuivalen live.
- Ada secret/account ID di docs.
- Test suite gagal.

---

## 12. Explicit Non-Authorization

Task packet ini hanya untuk contract phase. Bukan izin implementasi, bukan izin schema migration, bukan izin replay runtime.
