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

### 1.1 Universal Capability & Skill Binding (Harness-Agnostic)
1. Kontrak ini berlaku untuk agentic AI mana pun: Claude Code, Codex CLI, DeepSeek harness, Antigravity CLI, OpenCode, atau harness lain yang dapat membaca file, menjalankan command, dan menulis kode.
2. Protokol task kanonik adalah `aeterna-task-protocol`. `omp-task-protocol` adalah alias deprecated untuk konfigurasi lama dan tidak membatasi builder ke OMP.
3. Jika harness memiliki skill system, builder WAJIB memuat skill yang tersedia pada Turn 1 sesuai kebutuhan:
   - task packet: `aeterna-task-protocol`;
   - invariant: `aeterna-invariants`;
   - gate / phase: `aeterna-milestone-gate`;
   - verifikasi: `aeterna-verify` / `verification-loop`;
   - handoff: `aeterna-handoff`;
   - pendukung: `diagnose`, `security-review`, `tdd-workflow`, `coding-standards`, `api-design`, `backend-patterns`.
4. Jika harness tidak memiliki skill system, builder WAJIB membaca file skill/doc setara sebagai teks biasa, minimal:
   - `.opencode/skills/aeterna-task-protocol/SKILL.md`
   - `.opencode/skills/aeterna-invariants/SKILL.md`
   - `docs/aeterna/AUTONOMOUS_BUILDER.md`
   - `docs/aeterna/task-packet-template.md`
   - `docs/aeterna/clean-code-rules.md`
   - `VERIFY.md`
5. Builder wajib melaporkan:
   ```yaml
   skills_loaded: [...]
   fallback_docs_read: [...]
   builder_harness: claude-code | codex-cli | deepseek-harness | antigravity-cli | opencode | generic
   ```
6. Dilarang mengklaim memanggil skill yang tidak tersedia di harness.
7. Output builder yang tidak memuat deklarasi capability di `context_manifest` otomatis berstatus `BLOCKED`.
8. Nama harness tidak mengubah bukti, scope, invariant, atau gate.

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

Kode yang dibangun oleh builder harness mana pun dan diverifikasi oleh verifier yang ditunjuk wajib mematuhi metrik berikut:
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

### 6.1 Larangan Mutlak Otomasi Merge (`gh pr merge` Ban)
1. Perintah `gh pr merge`, `git merge`, atau auto-merge API **DILARANG KERAS** dipanggil oleh agent atau builder harness mana pun tanpa pengecualian.
2. Peran `aeterna-verifier` dibatasi HANYA untuk menerbitkan rekomendasi status:
   - `MERGE_READY`: Seluruh tes lokal lulus, CI hijau, scope patuh, dan golden test valid.
   - `CHANGES_REQUESTED`: Terdapat kegagalan pengujian, deviasi lint, atau pelanggaran scope.
3. Tombol atau perintah merge **HANYA BOLEH DIJALANKAN SECARA MANUAL OLEH HUMAN OPERATOR**. Pelanggaran terhadap aturan ini berstatus P0 Violation (Security & Safety Breach).

### 6.2 Verification Ladder

1. **Builder Self-Verification**: builder wajib menjalankan seluruh acceptance commands, lint, typecheck, dan test; lalu menempelkan `Verification Audit Report` + raw output ke PR/report-back. Jika CLI memiliki skill, gunakan skill verifikasi yang setara; jika tidak, gunakan fallback doc `VERIFY.md` dan laporkan `fallback_docs_read`.
2. **Lead Evidence Review**: Lead menerima self-verification jika lengkap dan konsisten. Lead tidak wajib otomatis memanggil verifier independen untuk task non-gate.
3. **Independent Verifier by Exception**: verifier independen wajib dipanggil untuk Tier A/gate, perubahan risiko/keuangan/keamanan, kontradiksi, bukti tidak lengkap, gate transition, atau permintaan operator.
4. Self-verification bukan independent audit dan tidak menghapus Two-Key Review pada modul Tier A.
5. Human approval gate tetap tidak bisa digantikan oleh skill, builder, lead, atau verifier.

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

## 8. Evidence Taxonomy & Research Envelope (Anti-Halusinasi)

Setiap klaim eksternal (literatur, anomali pasar, aturan venue, angka kinerja) wajib melewati `aeterna-research` dan diberi **tepat satu** tag status:

| Tag | Arti | Boleh dipakai di desain? |
| :--- | :--- | :---: |
| `EVIDENCE` | Ada sumber + sampel + periode + asumsi biaya | Ya, dengan sitasi |
| `HYPOTHESIS` | Logis, belum diuji di data kita | Ya, wajib ada kriteria falsifikasi |
| `CONTRADICTED` | Ada bukti berlawanan | Ya, sebutkan sumber & kondisi |
| `UNVERIFIED` | Tidak ada sumber yang bisa dicek ulang | **Tidak** |

Verdict dipisahkan dari tag: `ADOPT` | `TEST_FIRST` | `REJECT`, ditulis di akhir brief.

Source hierarchy dan source registry wajib mengikuti `docs/aeterna/RESEARCH_SOURCES.md`. SSRN Blog Trading Strategies (`https://blog.ssrn.com/tag/trading-strategies/`) adalah **discovery-only index**, bukan jurnal dan bukan bukti. Setiap kandidat paper harus diikuti ke halaman SSRN/DOI/PDF asli sebelum klaim boleh berstatus `EVIDENCE`.

Setiap item `EVIDENCE` wajib memuat: URL, terbitan, tahun, tanggal akses, aset, jumlah observasi, periode, horizon, dan status biaya transaksi. Bila transferabilitas ke horizon M15–H1 retail belum jelas, statusnya **turun** menjadi `HYPOTHESIS`.

Brief disimpan di `.handoff/research/BRIEF-<slug>.md` dan wajib mengekspos `unverified_items` secara terbuka, bukan menyembunyikannya.

---

## 9. Roster Agen & Aturan Rasionalisasi

Roster aktif per v2 (8 agen + 1 dorman):

| Agen | Status | Domain Tier A yang dipegang |
| :--- | :--- | :--- |
| `aeterna-lead` | primary | keputusan akhir, task packet, fase P0–P4 |
| `aeterna-research` | aktif | tidak memegang kode; hanya `.handoff/research/` |
| `aeterna-architect` | aktif | `db/`, `engine/shared/db/`, kontrak antarmuka |
| `aeterna-strategy` | aktif | `instruments/*/strategies/` |
| `aeterna-backtest` | aktif | `engine/analysis_engine/` |
| `aeterna-risk` | aktif | `engine/risk_gate/`, `engine/state_machine/`, `engine/watchdog/` |
| `aeterna-security` | aktif | `engine/security/`, `scripts/` |
| `aeterna-ingestion` | aktif | `engine/ingestion/` |
| `aeterna-verifier` | aktif | `tests/`, audit independen |
| `aeterna-execution` | **dorman** (aktif di fase P4) | `engine/execution/`, `engine/telegram_bot/` |

Aturan rasionalisasi:
1. **Dilarang melebur agen pemilik modul Tier A ke agen pengaudit.** Two-Key Review (`code-ownership.md §2`) mensyaratkan perancang dan pengaudit adalah pihak berbeda. Meleburnya membatalkan kontrol, bukan menyederhanakan.
2. Agen hanya boleh dimatikan/dorman jika domainnya tidak dipakai pada fase aktif, dan status itu wajib tercatat di tabel ini.
3. Setiap perubahan roster wajib disertai pembaruan `code-ownership.md` pada commit yang sama.

---

## 10. Checklist Self-Check 10 Poin (Pra-Output)

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
