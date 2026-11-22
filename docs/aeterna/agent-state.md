---
state_version: 21
updated_utc: "2026-11-21"
project: "AETERNA Quant"
phase: "P1 Journal"
mode: "SIGNAL_ONLY"
active_role: "aeterna-lead"
audit_protocol: "AUDIT_BY_EXCEPTION"
verification_protocol: "BUILDER_SELF_VERIFY_FIRST"
active_task: null
task_packet: null
branch: "main"
authored_from_head: "458fdba"
base_ref: "main"
base_commit: "458fdba"
main_head: "458fdba"
allowed_paths: []
gate_status:
  GATE-RUNTIME-LOOP-B: "PASSED"
  GATE-RUNTIME-VIRTUAL-TRACKER: "PASSED"
  GATE-NEWS-CALENDAR: "PASSED"
  GATE-E2E-RUNTIME: "PASSED"
  GATE-M4: "PASSED"
  GATE-M5: "PENDING_HUMAN_AUDIT"
  GATE-VIRTUAL-JOURNAL: "QUEUED"
  GATE-P1-E2E-OBSERVER_WRITE: "CODE_PASS_LIVE_BLOCKED"
  GATE-P1-E2E-PUBLISHER_ADMIN: "CODE_PASS_LIVE_BLOCKED"
  GATE-PROD-NEWS-SNAPSHOT: "SNAPSHOT_ACTIVE_WEB_ADAPTER"
  GATE-PROD_CREDENTIAL_SOURCE: "RESOLVED_ENV_LOGGED"
  GATE-P1-E2E-SPREAD_ZSCORE: "CODE_PASS_LIVE_BLOCKED"
  GATE-PUBLIC-RELEASE: "BETA_RELEASE_OPENAETERNA_DEV_MAIN_AETERNA"
next_action: "Development source of truth is GitHub AETERNA main at 458fdba. OpenAeterna is beta/public release only; do not push dev updates there. Core focus: wait market open, run live P1 E2E, then beta. Forward still after M5 + 50-100 samples."
---

# AETERNA Agent State
## 1. What this is
AETERNA Quant adalah platform riset dan eksekusi XAUUSD deterministik. Fase aktif P1 Journal, mode SIGNAL_ONLY, tanpa modal riil. LLM/AI CLI hanya developer tooling offline; produksi tidak boleh memakai LLM.

## 2. Read map
- `engine/runtime/` -> Loop A/B, virtual tracker, dashboard, service, bootstrap, news loader, chart snapshot
- `engine/state_machine/` -> news dan spread state
- `engine/risk_gate/` -> sizing, drawdown, rollover
- `engine/shared/db/` -> SQLite WAL repository
- `instruments/xauusd/strategies/` -> logika strategi dan adapter
- `tests/e2e/` -> smoke test runtime end-to-end

## 3. Boot sequence
1. Baca file ini.
2. Jika `active_task` tidak null, baca `task_packet`.
3. Baca `docs/aeterna/invariant-cheatsheet.md`.
4. Jangan baca seluruh repo; gunakan read map di atas.
5. Cek `git merge-base --is-ancestor <base_commit> HEAD`; jika gagal, laporkan `BLOCKED`.
6. Sentuh hanya `allowed_paths`; jalankan command task packet; output envelope; stop setelah PR.

## 4. Guardrails
- `risk_per_trade=0.5%`, `daily_loss=2.0%`, `max_dd=10.0%`, `max_positions=1`, `max_trades=5`, `min_rr=2.0`.
- Exit 5 lapis tetap wajib.
- Dilarang `gh pr merge`, `git merge`, `order_send`, dan `PositionModify`.
- Dilarang konten publik berisi lot, equity, tiket, server, instruksi transaksi, atau klaim performa.
- Dilarang mematikan atau me-restart 9router port 20128.
- ZERO LLM di jalur produksi.

## 5. Stop conditions
- `active_task` null: jangan menulis kode.
- `allowed_paths` kosong: hanya audit read-only, jangan edit.
- `base_commit` bukan ancestor dari HEAD: laporkan `BLOCKED`.
- File di luar `allowed_paths`: stop.
- Gate yang dibutuhkan task belum PASSED: laporkan `BLOCKED`.
- Konteks bertentangan atau klaim tidak bisa diverifikasi: laporkan `NEEDS_DECISION`.

## 6. On demand
- `docs/aeterna/agent-audit-latest.md` -> hanya jika gate gagal atau task menyentuh known defect.
- `docs/aeterna/agent-contract.md` -> hanya sebelum envelope final atau pekerjaan gate/security.
- `docs/AGENTS.local.md` -> kebijakan operator lokal; baca jika ada potensi konflik kebijakan.
