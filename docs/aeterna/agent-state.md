---
state_version: 2
updated_utc: "2026-11-19"
project: "AETERNA Quant"
phase: "P1 Journal"
mode: "SIGNAL_ONLY"
active_role: "aeterna-lead"
active_task: null
task_packet: null
branch: "docs/readme-robust-ascii-workflow"
authored_from_head: "a32346a"
base_ref: "origin/main"
base_commit: "e8906df"
allowed_paths: []
gate_status:
  GATE-RUNTIME-LOOP-B: "CHANGES_REQUESTED"
  GATE-M4: "PENDING_HUMAN_AUDIT"
  GATE-M5: "PENDING_HUMAN_AUDIT"
  GATE-VIRTUAL-JOURNAL: "QUEUED"
next_action: "Jalankan canary read-only; jika lulus, buat TASK-RUNTIME-06-LOOKAHEAD-FIX."
---

# AETERNA Agent State
## 1. What this is
AETERNA Quant adalah platform riset dan eksekusi XAUUSD deterministik. Fase aktif P1 Journal, mode SIGNAL_ONLY, tanpa modal riil. LLM/AI CLI hanya developer tooling offline; produksi tidak boleh memakai LLM.

## 2. Read map
- `engine/runtime/` -> Loop A/B, virtual tracker, dashboard, service
- `engine/state_machine/` -> news dan spread state
- `engine/risk_gate/` -> sizing, drawdown, rollover
- `engine/shared/db/` -> SQLite WAL repository
- `instruments/xauusd/strategies/` -> logika strategi
- `tests/runtime/` -> regression test runtime

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
- `base_commit` bukan ancestor dari HEAD: laporkan `BLOCKED`.
- File di luar `allowed_paths`: stop.
- Gate yang dibutuhkan task belum PASSED: laporkan `BLOCKED`.
- Konteks bertentangan atau klaim tidak bisa diverifikasi: laporkan `NEEDS_DECISION`.

## 6. On demand
- `docs/aeterna/agent-audit-latest.md` -> hanya jika gate gagal atau task menyentuh known defect.
- `docs/aeterna/agent-contract.md` -> hanya sebelum envelope final atau pekerjaan gate/security.
- `docs/AGENTS.local.md` -> kebijakan operator lokal; baca jika ada potensi konflik kebijakan.
