---
name: aeterna-milestone-gate
description: Deterministic milestone and production-readiness gate auditor for AETERNA Quant — M1-M7 evidence, P0-P4 phase ladders, three mandatory human reviews, kill criteria, and no phase skipping.
license: AGPL-3.0-only
compatibility: universal
metadata:
  protocol_version: "2.0.0"
  authority: gate
  source_of_truth: docs/aeterna/requirements.md
  target_harnesses: [claude-code, codex-cli, deepseek-harness, antigravity-cli, opencode, generic-agentic-cli]
---

# AETERNA Milestone Gate — Evidence Before Phase Change

## 1. Purpose

Mencegah lompatan milestone, klaim "selesai" tanpa bukti, dan penggunaan dana riil sebelum audit manusia. Gate status berasal dari **output perintah nyata**, bukan tanggal, optimisme, atau narasi.

## 2. Authority & Precedence

1. Urutan M1 → M2 → M3 → M4 → M5 → M6 → M7 tidak boleh dilewati.
2. Tiga gate wajib audit manusia:
   - `GATE-M2`: PnL Rust, spread penalty, slippage vs hitungan tangan.
   - `GATE-M4`: sizing lot, drawdown, emergency killswitch Go.
   - `GATE-M5`: eksekusi demo, SL/TP terverifikasi di server broker MT5.
3. Forward test resmi hanya boleh mulai setelah `GATE-M5 PASSED`.
4. Jika modal riil `< ~$1,000`, forward test wajib di Standard Demo.
5. Konflik bukti → `NEEDS_DECISION`, bukan `PASSED`.

## 3. Phase Ladder — P0 to P4

| Phase | Nama | Required output | Gate untuk naik |
| :--- | :--- | :--- | :--- |
| P0 | Research | Angka + labelled brief | Evidence review. |
| P1 | Journal | Observasi + outcome virtual | `GATE-VIRTUAL-JOURNAL`, 50–100 sampel. |
| P2 | Internal Signal-Only | Kartu observasi ke admin/staging | Format consistency + level accuracy. |
| P3 | VIP Publication | Konten komunitas | Sampel + verifier + compliance review. |
| P4 | Execution | Order nyata | Paritas backtest-live + slippage + killswitch. |

Dilarang menyarankan naik phase jika gate phase sebelumnya belum `PASSED`. Sebut gate yang belum lulus di `next_action`.

## 4. Milestone Map

| Milestone | Scope | Gate | Human review |
| :--- | :--- | :--- | :--- |
| M1 | Data foundation, SQLite WAL, ingestion MT5/OANDA | `GATE-M1` | Automated |
| M2 | Backtest engine Rust/PyO3, slippage | `GATE-M2` | Required |
| M3 | Satu strategi + regime awal | `GATE-M3` | Automated |
| M4 | Risk gate + state machine + watchdog | `GATE-M4` | Required |
| M5 | Eksekusi Exness + logging transaksi | `GATE-M5` | Required |
| M6 | Telegram control & reporting | `GATE-M6` | Automated |
| M7 | Kronos ONNX, macro, strategi lanjutan | `GATE-M7` | Periodic |

## 5. Required Evidence per Gate

Gate `PASSED` hanya jika:

1. Seluruh REQ dalam scope berstatus `VERIFIED` di `docs/aeterna/requirements.md`.
2. Automated tests dijalankan dengan command resmi:
   - `uv run pytest tests/ -q`
   - `cargo test --all`
   - `go test ./...`
3. Golden tests finansial lulus.
4. Raw output ditempelkan, bukan diringkas menjadi angka saja.
5. Human review gate memiliki bukti approval tertulis jika required.
6. Kill criteria dicek (lihat §6).

## 6. Kill Criteria Check

| Condition | Threshold | Verdict |
| :--- | :--- | :--- |
| Max cumulative forward DD | `> 15.0%` | Project termination. |
| PF `< 1.0` / expectancy negatif | Setelah `≥100` trade **dan** `≥6 minggu` | Strategy failure. |
| Realized slippage `≥2×` model | Pada `>60%` transaksi | Engine recalibration. |

Jika kriteria terpenuhi, gate tidak boleh `PASSED`. Laporkan `BLOCKED` atau `NEEDS_DECISION` sesuai konteks.

## 7. Procedure

1. Baca `docs/aeterna/agent-state.md` untuk phase dan gate_status saat ini.
2. Baca `docs/aeterna/requirements.md` untuk REQ scope milestone.
3. Verifikasi milestone sebelumnya `PASSED`.
4. Jalankan test suite yang relevan; simpan raw output.
5. Cek apakah human review required dan approval tersedia.
6. Cek kill criteria.
7. Terbitkan sertifikat gate.

## 8. Output Contract

```yaml
milestone_gate_audit:
  target_milestone: M<1-7>
  all_reqs_verified: YES | NO
  automated_tests:
    command: "<command>"
    result: "<N passed, 0 failed> | NOT_RUN"
  raw_output_attached: true | false
  golden_tests: PASS | FAIL | NOT_APPLICABLE
  human_review_required: YES | NO
  human_approval: "APPROVED by <operator> on <date> | MISSING"
  kill_criteria_check: ALL_CLEAR | TRIGGERED
  gate_status: PASSED | REJECTED | IN_PROGRESS | BLOCKED
  phase_active: P0 | P1 | P2 | P3 | P4
  gates_not_passed: [...]
  next_action: "<phase + cheapest test>"
```

## 9. Failure Modes

- **Gejala**: Gate M5 diklaim PASSED tanpa bukti SL/TP server-side.
  **Tindakan**: `REJECTED`; minta screenshot/log MT5 dan order ticket mapping internal.
- **Gejala**: Ingin naik P3 sebelum 50–100 sampel internal.
  **Tindakan**: `BLOCKED`; sebut `GATE-VIRTUAL-JOURNAL` belum lulus.
- **Gejala**: Human review disebut "nanti saja".
  **Tindakan**: `BLOCKED`.

## 10. Harness Binding

Jika harness memiliki skill system, muat skill ini pada aktivasi gate/phase. Jika tidak, baca file ini + `VERIFY.md` dan laporkan `fallback_docs_read`. Audit tanpa bukti command nyata otomatis cacat.
