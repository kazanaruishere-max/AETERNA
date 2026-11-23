# Autonomous Builder Task Packet Template v4 — AETERNA Quant

Canonical template for `aeterna-task-protocol`. Dipakai oleh builder dari harness mana pun: Claude Code, Codex CLI, DeepSeek harness, Antigravity CLI, OpenCode, atau generic agentic CLI. Legacy path `docs/aeterna/omp-task-template.md` tetap dikenali sebagai alias.

Seluruh seksi wajib terisi sebelum task berstatus `READY`. Kontrak operasional: `docs/aeterna/AUTONOMOUS_BUILDER.md`.

---

```markdown
# TASK-M<Milestone>-<Num>: <Judul Task Singkat & Imperatif>

metadata:
  task_id: TASK-M<Milestone>-<Num>
  protocol: aeterna-task-protocol
  protocol_version: "2.0.0"
  tier: A | B | C
  target_milestone: M<1-7>
  target_branch: feat/m<Milestone>-<slug>
  worktree_dir: .worktrees/<slug>
  covers_req: [REQ-<DOM>-<NUM>, REQ-<DOM>-<NUM>]
  depends_on: [TASK-M<X>-<Y>]
  base_commit: <hash_commit_terakhir>
  builder_harness: claude-code | codex-cli | deepseek-harness | antigravity-cli | opencode | generic
  status: READY | DRAFT | BLOCKED

---

## 1. Required Reading (Wajib Dibaca Sebelum Mulai)
Builder wajib membaca file-file berikut secara berurutan:
1. `AGENTS.md`
2. `docs/aeterna/agent-state.md`
3. `docs/aeterna/invariant-cheatsheet.md`
4. `docs/aeterna/REPO_BOUNDARY.md`
5. `docs/aeterna/AUTONOMOUS_BUILDER.md`
6. `docs/aeterna/clean-code-rules.md`
7. `VERIFY.md`
8. `<file_konteks_terkait_1>`

Jika skill system tersedia, muat `aeterna-task-protocol`, `aeterna-invariants`, dan skill verifikasi yang setara. Jika tidak, baca fallback doc dan laporkan `fallback_docs_read`.

---

## 2. Scope File (HANYA File Ini Yang Boleh Dibuat / Diedit)
Dilarang keras menyentuh file di luar daftar berikut:
- `engine/<submodul>/<nama_file>.py` (Implementasi)
- `tests/<submodul>/test_<nama_file>.py` (Pengujian unit)

Maksimal 3 file dan < 300 baris diff.

---

## 3. Forbidden Scope (Dilarang Disentuh)
- Seluruh file di luar daftar seksi 2.
- `instruments/xauusd/config/parameters.yaml` tanpa instruksi eksplisit.
- `.env`, secret, kredensial, account ID, server broker.
- Port 20128 / proses 9router.
- File Tier A lain tanpa owner approval.

---

## 4. Requirements (Persyaratan Implementasi Spesifik)
1. Persyaratan 1 (harus terukur dan bertipe tegas).
2. Persyaratan 2.
3. Persyaratan 3.

---

## 5. Requirement Traceability Matrix (RTM)
| REQ ID | Implementasi | Test Case | Target Output |
| :--- | :--- | :--- | :--- |
| `REQ-XXX-001` | `path/to/file.py:func_name` | `tests/.../test_xxx.py:test_case` | Lolos validasi tanpa error |

---

## 6. Hard Invariants (Wajib Dipatuhi)
- `risk_per_trade_pct = 0.5%`
- `max_daily_loss_pct = 2.0%`
- `max_drawdown_killswitch_pct = 10.0%`
- `max_concurrent_positions = 1`
- `max_trades_per_day = 5`
- `min_rr = 2.0`
- ZERO LLM di jalur produksi.
- Do Not Kill port 20128 (9router).

---

## 7. Test Matrix
| Tipe Pengujian | Path File Test | Skenario Pengujian |
| :--- | :--- | :--- |
| **Unit Test** | `tests/.../test_unit.py` | Validasi kalkulasi input boundary |
| **Golden Test** | `tests/.../test_golden.py` | Uji deterministik nilai tetap |
| **Edge Case** | `tests/.../test_edge.py` | Anomali network, data kosong, zero-division |

---

## 8. Acceptance Commands & Expected Exit Code
Perintah wajib dijalankan builder; return code harus 0.

Builder WAJIB menempelkan `Verification Audit Report` dan raw output ke PR body / report-back. Jika CLI memiliki skill system, panggil skill verifikasi yang setara; jika tidak, baca `VERIFY.md` dan laporkan `fallback_docs_read`. Tanpa bukti ini, task tidak boleh dilaporkan selesai.

```powershell
uv run pytest tests/<submodul>/test_<nama_file>.py -v
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Tambahkan `cargo test --all`, `cargo clippy -- -D warnings`, `go test ./...`, `go vet ./...` bila stack tersentuh.

---

## 8.1 Git Branch & Pull Request Protocol (Wajib untuk Tier A & B)
Untuk task Tier A dan B, dilarang commit langsung ke `main`.

```powershell
git checkout -b feat/m<Milestone>-<slug>
# implement
git add <file_di_seksi_2>
git commit -m "<type>(<scope>): <ringkasan imperatif>"
git push -u origin feat/m<Milestone>-<slug>
gh pr create --title "<type>(<scope>): <ringkasan imperatif>" --body "<report-back>"
```

STOP setelah PR. Dilarang `gh pr merge`, `git merge`, atau auto-merge. Merge hanya human operator.

Catatan Tier C: dokumentasi/chore non-breaking boleh direct commit jika diinstruksikan eksplisit operator.

---

## 9. Rollback Plan
Jika implementasi gagal:
```powershell
git checkout -- <file_di_scope>
git clean -fd <file_baru_untracked>
```

---

## 10. Ownership Manifest
| File | Tanggung Jawab Tunggal | Owner Subagent | Tier |
| :--- | :--- | :---: | :---: |
| `path/to/file.py` | Deskripsi tanggung jawab 1 kalimat | `aeterna-<role>` | A / B |

---

## 11. Clean Code Requirements
- Maksimal 50 baris per fungsi.
- Maksimal 400 baris per file (maks 800).
- Maksimal 4 tingkat indentasi.
- Zero dead code / unused imports.
- Explicit type annotations pada fungsi publik.

---

## 12. Refactor Contract (Wajib jika menyentuh kode eksisting)
- **Characterization Test**: `tests/.../test_legacy.py` wajib dijalankan sebelum dan sesudah refactor.
- **Commit Terpisah**: wajib `refactor(<scope>): ...`.
- **Perilaku dilarang berubah**: kontrak publik, skema database, format log.

---

## 13. Side-Effect Declaration
- **Public API**: TIDAK BERUBAH
- **Database Schema**: TIDAK BERUBAH / Migrasi: NONE
- **Config YAML**: TIDAK BERUBAH
- **Logging Format**: TIDAK BERUBAH

---

## 14. Diff Budget
- Maksimal file diubah: 3 file.
- Maksimal total penambahan baris: < 300 baris.

---

## 15. Report-Back Contract
Builder wajib melaporkan:
1. Daftar file yang diubah/dibuat.
2. `context_manifest` + `skills_loaded` atau `fallback_docs_read` + `builder_harness`.
3. `Verification Audit Report`.
4. Raw output seluruh perintah verifikasi (teks asli tanpa rekayasa).
5. Checklist clean code.
6. Side effects dan deviasi teknis.
7. Nomor PR atau alasan PR tidak dibuat.
```
