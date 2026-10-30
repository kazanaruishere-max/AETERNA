# OMP Task Packet Template v2 — AETERNA Quant Project (docs/aeterna/omp-task-template.md)

Template resmi paket tugas mandiri (*self-contained task packet*) yang dihasilkan oleh `aeterna-briefer` untuk dikerjakan oleh builder (OMP / `omp.exe`). Seluruh seksi di bawah ini WAJIB terisi lengkap sebelum task berstatus `READY`.

---

```markdown
# TASK-M<Milestone>-<Num>: <Judul Task Singkat & Imperatif>

metadata:
  task_id: TASK-M<Milestone>-<Num>
  tier: A | B | C
  target_milestone: M<1-7>
  covers_req: [REQ-<DOM>-<NUM>, REQ-<DOM>-<NUM>]
  depends_on: [TASK-M<X>-<Y>]
  base_commit: <hash_commit_terakhir>
  status: READY | DRAFT | BLOCKED

---

## 1. Required Reading (Wajib Dibaca Sebelum Mulai)
OMP wajib membaca file-file berikut secara berurutan untuk memahami konteks:
1. `docs/AGENTS.local.md` (Aturan operasional & batasan sistem)
2. `docs/aeterna/invariant-cheatsheet.md` (Nilai numerik & konstanta absolut)
3. `docs/aeterna/clean-code-rules.md` (Standar kode, linter, & refactoring)
4. `<file_konteks_terkait_1>`
5. `<file_konteks_terkait_2>`

---

## 2. Scope File (HANYA File Ini Yang Boleh Dibuat / Diedit)
Dilarang keras menyentuh file di luar daftar berikut:
- `engine/<submodul>/<nama_file>.py` (Implementasi)
- `tests/<submodul>/test_<nama_file>.py` (Pengujian unit)

---

## 3. Forbidden Scope (Dilarang Disentuh)
- Seluruh file di luar daftar seksi 2.
- Dilarang mengubah file konfigurasi `instruments/xauusd/config/parameters.yaml` tanpa instruksi eksplisit.
- Dilarang membuat file `.env` berisi kredensial asli.

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
Perintah yang wajib dijalankan OMP dan harus menghasilkan return code 0:
```powershell
# 1. Jalankan unit test
uv run pytest tests/<submodul>/test_<nama_file>.py -v

# 2. Jalankan linter & formatting check
uv run ruff check .
uv run ruff format --check .

# 3. Jalankan type checking
uv run pyright
```

---

## 9. Rollback Plan
Jika implementasi gagal atau merusak tes eksisting:
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
- Maksimal 4 tingkat indentasi (*guard clauses*).
- Zero dead code / no unused imports.
- Explicit type annotations pada seluruh fungsi publik.

---

## 12. Refactor Contract (Wajib jika menyentuh kode eksisting)
- **Characterization Test**: `tests/.../test_legacy.py` wajib dijalankan sebelum dan sesudah refactor.
- **Commit Terpisah**: Wajib commit terpisah dengan pesan `refactor(<scope>): ...`.
- **Perilaku Yang Dilarang Berubah**: Kontrak input/output fungsi publik, skema database.

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

## 15. Report-Back Contract (Format Laporan OMP)
OMP wajib melaporkan hasil kerja dalam format:
1. Daftar file yang diubah/dibuat.
2. Log eksekusi perintah verifikasi seksi 8 (wajib teks asli tanpa rekayasa).
3. Konfirmasi checklist clean code seksi 11.
4. Kendala / deviasi teknis (jika ada).
```
