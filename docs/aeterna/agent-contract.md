# Universal Agent Contract — AETERNA Quant Project (docs/aeterna/agent-contract.md)

Dokumen ini memuat kontrak kerja mutlak (*hard constraints*) bagi seluruh agen AI (`aeterna-*`). Setiap agen yang menghasilkan output tanpa mematuhi kontrak ini dianggap menghasilkan draft cacat dan otomatis berstatus `BLOCKED`.

---

## 1. Context Gate (Wajib Paham Konteks, Bukan Sekadar Selesai)

1. Sebelum menghasilkan analisis atau keputusan apa pun, agen **wajib membaca**:
   - `docs/AGENTS.local.md`
   - `docs/aeterna/invariant-cheatsheet.md`
   - Daftar `REQUIRED CONTEXT` spesifik pada modul agen masing-masing.
2. Setiap respons final agen wajib diawali dengan blok metadata `context_manifest`. Agen wajib menyebutkan file dan bab/baris yang telah dibaca beserta alasannya.
3. Jika dokumen yang dibutuhkan tidak ditemukan atau terjadi anomali, agen **dilarang berasumsi**. Agen wajib menyetel `status: BLOCKED` dan mencatat pertanyaan di `open_questions`.

---

## 2. Evidence Rule & No-Guessing

1. Dilarang keras melakukan klaim tanpa bukti rujukan (*zero unsubstantiated claims*).
2. Setiap temuan atau rekomendasi arsitektur wajib mencantumkan bukti spesifik:
   - File dan nomor baris (`file_path:line_number`), ATAU
   - Nomor pasal dokumen (`architecture.md §3.3`), ATAU
   - Output riil perintah terminal yang dieksekusi.
3. Jika terdapat dua dokumen yang bertentangan, agen **dilarang memilih sendiri tanpa izin**. Catat ke dalam blok `contradictions` dan tetapkan `status: NEEDS_DECISION`.

---

## 3. Completeness Sweep & Traceability

1. Setiap item pekerjaan wajib memiliki ID penelusuran:
   - `REQ-<DOMAIN>-<NUM>`: Requirement acuan dari PRD/Architecture/Security.
   - `TASK-<MILESTONE>-<NUM>`: Unit task yang diberikan ke builder (OMP).
   - `TEST-<MODULE>-<NUM>`: Skenario pengujian deterministik.
   - `GATE-<MILESTONE>`: Verification gate milestone.
   - `ADR-<NUM>`: Architecture Decision Record.
2. Dalam setiap desain, seluruh requirement dalam scope harus diberi status disposisi lengkap:
   - `COVERED`: Diimplementasikan dalam paket tugas saat ini.
   - `DEFERRED`: Ditunda ke milestone berikutnya dengan justifikasi tertulis.
   - `REJECTED`: Ditolak karena bertentangan dengan invariant / arsitektur, dengan alasan tertulis.

---

## 4. Code Ownership & Single Responsibility

1. Setiap file, fungsi, dan modul wajib memiliki tanggung jawab tunggal (*Single Responsibility Principle*) yang dapat didefinisikan dalam 1 kalimat jelas.
2. Tidak boleh ada file yatim piatu (*orphan code*). Setiap file baru wajib didaftarkan di `docs/aeterna/code-ownership.md` dengan nama sub-agent pemiliknya.
3. Dilarang membuat kode mati (*dead code*), helper tanpa pemanggil, atau abstraksi dini (*premature abstractions*) yang belum dibutuhkan.

---

## 5. Clean Code Gate & Batasan Numerik Keras

Kode yang dibangun oleh OMP dan diverifikasi oleh OpenCode wajib mematuhi metrik berikut:
- **Panjang Fungsi**: Maksimal 50 baris per fungsi.
- **Panjang File**: Tipikal 200–400 baris, maksimal 800 baris.
- **Nesting Level**: Maksimal 4 tingkat indentasi.
- **Immutability**: Utamakan objek immutable (`frozen=True` di Python, *move semantics* di Rust).
- **Error Handling**: Dilarang menelan error secara diam-diam (`except: pass` di Python, `.unwrap()` di Rust jalur produksi, `_ = err` di Go).
- **Linter Pass**: Lulus 100% tanpa kompromi pada `ruff`, `clippy`, dan `go vet`.

---

## 6. Refactor Safety & Larangan Efek Samping (Side-Effect Ban)

1. **Behavior-Preserving**: Refactoring hanya boleh dilakukan untuk meningkatkan keterbacaan, efisiensi, dan modularitas **tanpa mengubah perilaku eksternal sistem**.
2. **Characterization Tests First**: Sebelum kode di-refactor, test suite wajib memastikan perilaku eksisting terkunci. Setelah refactor, test yang sama harus tetap lulus.
3. **Pemisahan Commit**: Commit refactor dilarang dicampur dengan commit penambahan fitur baru.
4. **Side-Effect Ban**: Dilarang mengubah kontrak publik API, skema database, struktur konfigurasi YAML, format log, atau jalur jaringan di luar cakupan task. Setiap potensi efek samping wajib dideklarasikan tertulis pada task packet.

---

## 7. Skema Output Amplop Baku (Standard Output Envelope)

Seluruh sub-agent wajib menyusun respons dalam format YAML/Markdown berikut:

```yaml
envelope:
  status: READY | BLOCKED | NEEDS_DECISION
  role: aeterna-<role>
  milestone: M<1-7>
  tier: A | B | C

context_manifest:
  - file: "docs/architecture.md"
    sections: ["§3.3", "§5.1"]
    reason: "Validasi parameter formula EWMA spread z-score"

findings:
  - id: FIND-001
    severity: P0 | P1 | P2 | P3
    claim: "Deskripsi temuan teknis"
    evidence: "file:line atau dokumen rujukan"
    impact: "Dampak terhadap risiko/keuangan/sistem"

decisions:
  - id: ADR-00X
    decision: "Keputusan teknis yang diambil"
    rationale: "Alasan berbasis first-principles"
    alternatives: ["Alternatif A (ditolak karena X)", "Alternatif B (ditolak karena Y)"]

contradictions:
  - source_a: "PRD.md §3"
    source_b: "parameters.yaml line 12"
    conflict: "Perbedaan nilai threshold"
    resolution_owner: "Lead Architect"

open_questions:
  - id: Q-001
    question: "Pertanyaan yang butuh keputusan operator"
    blocking: true

coverage_sweep:
  - req_id: REQ-ARCH-014
    section: "§5.2 Exit Logic 5 Lapis"
    disposition: COVERED
    note: "Dituangkan ke TASK-M4-02"

side_effects:
  public_api: "TIDAK BERUBAH"
  database_schema: "TIDAK BERUBAH"
  runtime_config: "TIDAK BERUBAH"
  logging_format: "TIDAK BERUBAH"

next_action: "Langkah terarah berikutnya"
```

---

## 8. Checklist Self-Check 10 Poin (Pra-Output)

Sebelum mengirimkan output, agen wajib memverifikasi secara internal:
1. [ ] Apakah `context_manifest` telah mencakup semua dokumen rujukan wajib?
2. [ ] Apakah seluruh angka parameter identik dengan `invariant-cheatsheet.md`?
3. [ ] Apakah sistem mempertahankan prinsip ZERO LLM pada jalur produksi?
4. [ ] Apakah semua temuan didukung oleh bukti spesifik (*evidence-backed*)?
5. [ ] Apakah tidak ada asumsi yang disembunyikan tanpa label?
6. [ ] Apakah modul yang dirancang mematuhi batas tanggung jawab tunggal (*SRP*)?
7. [ ] Apakah ada potensi efek samping yang belum dideklarasikan?
8. [ ] Apakah task packet OMP mandiri dan tidak memerlukan riwayat chat OpenCode?
9. [ ] Apakah perintah verifikasi dan acceptance criteria dapat diuji secara mekanis?
10. [ ] Apakah proses ini menjamin kelangsungan hidup 9router (port 20128)?
