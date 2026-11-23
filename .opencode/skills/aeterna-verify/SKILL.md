---
name: aeterna-verify
description: Harness-neutral mechanical verification gate for AETERNA Quant — multi-stack commands, golden tests, scope and ownership checks, raw-output mandate, and zero fabrication.
license: AGPL-3.0-only
compatibility: universal
metadata:
  protocol_version: "2.0.0"
  authority: verification
  target_harnesses: [claude-code, codex-cli, deepseek-harness, antigravity-cli, opencode, generic-agentic-cli]
  fallback_docs: [VERIFY.md, docs/aeterna/clean-code-rules.md]
---

# AETERNA Verify — Evidence, Not Optimism

## 1. Purpose

Menegakkan verification gate mekanis lintas Python, Rust, dan Go. Skill ini menolak ringkasan tanpa perintah, angka tanpa output, dan klaim PASS tanpa return code.

## 2. Authority & Precedence

1. Raw output terminal adalah bukti utama.
2. Self-verification builder tidak menggantikan independent verifier untuk Tier A, gate, risiko, keuangan, keamanan, atau kontradiksi.
3. Human approval gate tidak bisa digantikan oleh skill, builder, lead, atau verifier.
4. Satu warning yang diabaikan = `FAIL`, bukan `PASS with note`.
5. Jika command tidak bisa dijalankan, nyatakan `NOT_RUN`; jangan mengarang hasil.

## 3. When to Use

- Setiap task packet selesai dijalankan builder.
- Sebelum PR / report-back.
- Sebelum gate milestone.
- Setelah refactor untuk membuktikan behavior parity.
- Saat audit clean code atau golden test.

## 4. Required Inputs

- Task packet dengan `allowed_paths` dan `acceptance_commands`.
- Path file/branch yang diverifikasi.
- Scope tier (A/B/C).
- Raw output dari perintah yang dijalankan.

## 5. Command Matrix

| Stack | Format / lint | Typecheck / vet | Test | Extra |
| :--- | :--- | :--- | :--- | :--- |
| Python | `uv run ruff check .`, `uv run ruff format --check .` | `uv run pyright` | `uv run pytest tests/ -q` | Golden tests finansial wajib. |
| Rust | `cargo fmt --check` | `cargo clippy -- -D warnings` | `cargo test --all` | No `unwrap()` di jalur komputasi. |
| Go | `gofmt -l .` | `go vet ./...` | `go test ./...` | Watchdog panic-free. |
| Repo | `git diff --check` | `git status --porcelain=v1` | `git merge-base --is-ancestor` | Scope + ownership check. |

Gunakan `uv`, bukan `python` langsung. Untuk command Windows, jangan mematikan 9router port `20128`.

## 6. Golden Tests — Wajib

Jika stack menyentuh jalur finansial, verifikasi keberadaan dan hasil:

1. Sizing lot & batas `0.5%` risk.
2. State machine `NORMAL → PRE_NEWS → PAUSED → RECOVERY → NORMAL`.
3. EWMA `α = 0.08`, Z-score `≥3.0` pause, `<1.5` resume dengan `K=12`, `M=5`.
4. Exit 5 lapis secara terpisah.
5. Slippage simulator Rust.
6. Rollover force close 15 menit sebelum daily break.

Tanpa golden test yang relevan → `FAIL` atau `NOT_APPLICABLE` dengan justifikasi.

## 7. Procedure

1. Baca task packet; catat `allowed_paths`.
2. Cek `git merge-base --is-ancestor <base_commit> HEAD`.
3. Jalankan seluruh `acceptance_commands` persis.
4. Jalankan command matrix sesuai stack yang disentuh.
5. Cek `git diff --stat` terhadap scope.
6. Cek file baru terhadap `docs/aeterna/code-ownership.md`.
7. Cek suppressed errors (`# type: ignore`, `// nolint`) tanpa persetujuan.
8. Cek raw output lengkap dan return code `0`.
9. Terbitkan `Verification Audit Report` + Blok Accountability.

## 8. Output Contract

```yaml
verification_audit:
  scope_check: PASS | FAIL
  base_commit_ancestor: PASS | FAIL
  code_ownership: PASS | FAIL | NOT_APPLICABLE
  linter_typecheck:
    python: PASS | FAIL | NOT_APPLICABLE
    rust: PASS | FAIL | NOT_APPLICABLE
    go: PASS | FAIL | NOT_APPLICABLE
  test_suite:
    command: "<command>"
    result: "<N passed, 0 failed>"
    return_code: 0
    raw_output_attached: true
  golden_tests: PASS | FAIL | NOT_APPLICABLE
  behavior_parity: CONFIRMED | NOT_APPLICABLE
  suppressed_errors: NONE | LISTED
  verdict: PASS | FAIL
  evidence:
    - command: "<command>"
      output_excerpt: "<verbatim>"
```

Blok accountability:

```markdown
✅ Terverifikasi: <apa> + <perintah> → <hasil nyata>
⚠️ Belum terverifikasi: <asumsi/gap>
🔻 Risiko teratas: <1-2 risiko> — deteksi: <cara>
```

## 9. Self-Check

1. [ ] Apakah semua command dijalankan langsung?
2. [ ] Apakah return code 0?
3. [ ] Apakah raw output ditempelkan apa adanya?
4. [ ] Apakah scope dan ownership patuh?
5. [ ] Apakah golden test relevan tersedia?
6. [ ] Apakah tidak ada angka yang dibuat-buat?
7. [ ] Apakah independent verifier dipanggil bila Tier A/gate/security?

## 10. Failure Modes

- **Gejala**: Test lulus tapi ada unused import / warning.
  **Tindakan**: `FAIL`; bersihkan dead code.
- **Gejala**: Builder menulis "all tests passed" tanpa output.
  **Tindakan**: `BLOCKED`; minta raw output.
- **Gejala**: File baru belum ada di code-ownership.
  **Tindakan**: `FAIL`; daftarkan dulu.

## 11. Harness Binding

Jika harness memiliki skill system, muat skill ini. Jika tidak, baca `VERIFY.md`, `docs/aeterna/clean-code-rules.md`, dan file ini; laporkan `fallback_docs_read`. Klaim memanggil skill yang tidak tersedia = `BLOCKED`.
