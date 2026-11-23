---
state_version: 30
updated_utc: "2026-11-23"
project: "AETERNA Quant"
phase: "P1 Journal"
mode: "SIGNAL_ONLY"
active_role: "aeterna-lead"
audit_protocol: "AUDIT_BY_EXCEPTION"
verification_protocol: "BUILDER_SELF_VERIFY_FIRST"
active_task: null
task_packet: null
branch: "main"
authored_from_head: "486c322"
base_ref: "main"
base_commit: "486c322"
main_head: "486c322"
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
  GATE-PUBLIC-RELEASE: "RELEASE_OPENAETERNA_BETA_DEV_AETERNA"
next_action: "XAUUSD focus locked. Live P1 stopped at 08:00Z with NO_SETUP; restart gap incident recorded locally; PLAN-08 contract merged at c726cbf. GitHub Actions triggers optimized locally: PR-only CI, code-gated jobs, monthly CodeQL, MT5-only Windows. Next: validate first PR, then approve REQ-RUNTIME-011 and execute DATA-A only. No replay implementation, runtime adapter, PSAR EA, k8s, weekly-only news, or user telemetry before gates."
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

## 7. Plans (2026-11-22)
- PLAN-01 PSAR EA: DEFERRED_CANDIDATE | `.handoff/plans/PLAN-01-PSAR-SCALPING.md`
- PLAN-02 Monthly maintenance: ACCEPTED_WITH_GUARD | `.handoff/plans/PLAN-02-MONTHLY-MAINTENANCE.md`
- PLAN-03 Kubernetes/Docker: REJECTED_FOR_NOW | `.handoff/plans/PLAN-03-KUBERNETES-DOCKER.md`
- PLAN-04 Weekly news JSON: ACCEPTED_AS_ARCHIVE_ONLY | `.handoff/plans/PLAN-04-WEEKLY-NEWS-SNAPSHOT.md`
- PLAN-05 Floating/spike/leverage/margin: ACCEPTED_PHASED_DEFENSE | `.handoff/plans/PLAN-05-MARGIN-SPIKE-DEFENSE.md`
- PLAN-06 User forward-test telemetry: CONDITIONAL_INTERNAL_ONLY | `.handoff/plans/PLAN-06-USER-FORWARD-TELEMETRY.md`
- PLAN-07 Instrument adapter workflow: ACCEPTED_AS_WORKFLOW_ONLY | contract-first + XAUUSD focus | `.handoff/plans/PLAN-07-INSTRUMENT-ADAPTER-WORKFLOW.md`
- PLAN-08 Restart gap replay: CONTRACT_MERGED | `c726cbf` | `docs/aeterna/restart-gap-replay-contract.md`
- Register: `.handoff/plans/PLAN-REGISTER-2026-11-22.md`; full ledger: `.handoff/2026-11-22.md` / `.handoff/latest.md`.
