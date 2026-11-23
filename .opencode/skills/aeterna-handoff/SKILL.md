---
name: aeterna-handoff
description: Harness-neutral continuity protocol for AETERNA Quant — dated handoff, latest mirror, tracked agent-state, gate ledger, plan/task pointers, risks, and 3-line operator summary.
license: AGPL-3.0-only
compatibility: universal
metadata:
  protocol_version: "2.0.0"
  authority: continuity
  target_harnesses: [claude-code, codex-cli, deepseek-harness, antigravity-cli, opencode, generic-agentic-cli]
  persistence: local
---

# AETERNA Handoff — Continuity With Evidence

## 1. Purpose

Menjaga kontinuitas antar sesi, harness, sub-agent, dan operator tanpa kehilangan keputusan, gate status, task aktif, atau risiko. Handoff bukan catatan santai; ia adalah **state snapshot yang auditabel**.

## 2. When to Use

- Akhir sesi kerja.
- Pergantian topik besar.
- Transisi milestone / phase.
- Awal sesi baru untuk recovery konteks.
- Setelah keputusan arsitektur atau plan selection yang penting.

## 3. Hard Rules

1. Tulis `.handoff/YYYY-MM-DD.md`.
2. Salin identik ke `.handoff/latest.md`.
3. Perbarui `docs/aeterna/agent-state.md` (tracked) dengan:
   - `state_version` increments by 1,
   - `updated_utc`,
   - `branch`,
   - `authored_from_head`, `base_commit`, `main_head`,
   - `active_task`, `allowed_paths`, `gate_status`, `next_action`.
4. Dilarang memuat kredensial, API key, account ID, server broker, tiket, atau data pribadi.
5. Gate Ledger wajib memakai status riil: `PASSED`, `IN_PROGRESS`, `BLOCKED`, `CODE_PASS_LIVE_BLOCKED`, `QUEUED`, `PENDING_HUMAN_AUDIT`.
6. Wajib mencantumkan P0/P1 risks + detection.
7. Wajib mencantumkan plan/task pointer, bukan hanya narasi.
8. `next_action` wajib memuat phase aktif (P0–P4), gate yang belum lulus, dan uji termurah berikutnya.
9. Informasikan operator ringkasan tepat 3 baris.

## 4. Required Inputs

- `git log -1 --oneline` terbaru.
- `docs/aeterna/agent-state.md`.
- `docs/aeterna/invariant-cheatsheet.md`.
- `docs/aeterna/REPO_BOUNDARY.md`.
- Gate evidence terakhir dari `VERIFY.md` / verifier.
- Daftar task aktif atau antre di `.handoff/tasks/`.
- Daftar plan di `.handoff/plans/` bila relevan.

## 5. Procedure

1. Jalankan `git log -1 --oneline` dan `git status --porcelain=v1`.
2. Baca state, boundary, dan gate ledger sebelumnya.
3. Kumpulkan fakta: commit, phase, gate, task, plan, risiko.
4. Tulis handoff harian memakai template §7.
5. Salin identik ke `.handoff/latest.md`.
6. Update `docs/aeterna/agent-state.md`.
7. Verifikasi mirror dengan `git diff --no-index --exit-code .handoff/<date>.md .handoff/latest.md`.
8. Verifikasi `git diff --check`.
9. Scan secret dengan rg/pattern internal.
10. Laporkan 3 baris ke operator. Jangan commit kecuali diminta.

## 6. Gate Ledger Rules

- `PASSED` hanya jika raw output command / approval manusia ada.
- `CODE_PASS_LIVE_BLOCKED` dipakai untuk kode yang lolos test tetapi menunggu kondisi live.
- `QUEUED` dipakai untuk gate yang belum mulai.
- `PENDING_HUMAN_AUDIT` dipakai untuk human review gate yang belum disetujui.
- Jangan menulis `PASSED` hanya karena task selesai.

## 7. Output Contract

```markdown
# HANDOFF <YYYY-MM-DD> — <TOPIC>

## 1. Snapshot
- Phase: P0 | P1 | P2 | P3 | P4
- Milestone: M<1-7>
- Active branch: <branch>
- Latest commit: <hash>
- Mode: SIGNAL_ONLY | EXECUTION
- Rigor tier: A | B | C
- Repo boundary: AETERNA = development; OpenAeterna = release

## 2. Gate Ledger
- GATE-X: <STATUS> | Evidence: <command / document> | Raw output: attached | missing

## 3. Decision Log
- DECISION-<date>-<slug>: <keputusan + alasan + evidence status>

## 4. Active Tasks
- TASK-M<X>-<YY>: [STATUS] | Owner: <agent/human> | Files: <paths>

## 5. Plan Pointers
- Register: <path>
- Plans: <paths>

## 6. Critical Risks (P0/P1) & Detection
- Risiko: <deskripsi> | Deteksi: <cara cek>

## 7. Next 3 Actions
1. [ ] Action 1 (Owner: <aeterna-role | operator>)
2. [ ] Action 2 (Owner: <aeterna-role | operator>)
3. [ ] Action 3 (Owner: <aeterna-role | operator>)

## 8. Verification
- git diff --check: PASS | FAIL
- mirror diff: IDENTICAL | DIVERGED
- secret scan: CLEAN | HITS
```

## 8. Self-Check

1. [ ] Apakah state_version naik?
2. [ ] Apakah dated handoff dan latest identik?
3. [ ] Apakah gate status bersumber dari bukti nyata?
4. [ ] Apakah phase/gate/next_action tercantum?
5. [ ] Apakah tidak ada secret atau account identifier?
6. [ ] Apakah 3-line operator summary diberikan?

## 9. Failure Modes

- **Gejala**: Handoff menyebut gate PASSED tanpa log.
  **Tindakan**: Turunkan ke `IN_PROGRESS`/`BLOCKED` sampai bukti tersedia.
- **Gejala**: latest dan dated berbeda.
  **Tindakan**: Copy ulang identik, verifikasi dengan diff.
- **Gejala**: Handoff berisi kredensial.
  **Tindakan**: Hapus, rotasi bila perlu, tulis ulang sebelum selesai.

## 10. Harness Binding

Harness mana pun harus menulis file yang sama. Jika skill system tersedia, muat skill ini. Jika tidak, baca file ini sebagai fallback dan laporkan `fallback_docs_read`. Format file lebih penting daripada nama harness.
