---
name: omp-task-protocol
description: Protokol CLI-agnostic untuk menyusun, membatasi scope, dan mengevaluasi paket tugas mandiri (self-contained task packet) bagi autonomous builder mana pun.
license: AGPL-3.0-only
compatibility: any-cli
metadata:
  target_builder: any-cli
  workflow: task-packet
---

# Purpose
Mengatur standarisasi pembuatan paket tugas mandiri (*task packet*) untuk autonomous builder dari CLI mana pun, pembatasan file yang boleh disentuh (*scope boundary*), dan format evaluasi hasil pekerjaan agar bebas dari celah kritis. Detail operasional: `docs/aeterna/AUTONOMOUS_BUILDER.md`.

# When to use
- Gunakan saat `aeterna-lead` mengubah rancangan teknis yang telah disetujui menjadi paket tugas siap eksekusi.
- Gunakan saat memvalidasi apakah paket tugas sudah memenuhi Definition of Ready (DoR).
- Gunakan saat membaca dan memverifikasi laporan balik hasil kerja OMP.

# Hard rules
1. Task packet wajib mandiri (*self-contained*): builder tidak boleh membutuhkan riwayat chat CLI mana pun.
2. File yang boleh disentuh wajib di-*whitelist* eksplisit pada seksi `Scope`. File di luar scope dilarang disentuh.
3. Wajib menyertakan RTM (`REQ-*`), hard invariants, dan acceptance commands mekanis.
4. Wajib menyertakan deklarasi efek samping (*side-effects declaration*).
5. Jika berupa tugas refactoring, wajib menyertakan path *characterization test* eksisting.
6. Diff budget maksimal 3 file dan < 300 baris per task packet.
7. **Git Branch & PR Mandate (Tier A & B)**: Mulai TASK-M2-04, seluruh task Tier A dan B wajib dialokasikan branch `feat/m<Milestone>-<slug>` dan membuat PR via `gh pr create`. Direct commit ke `main` dilarang.
8. **Larangan Mutlak Auto-Merge**: Dilarang memanggil `gh pr merge` atau auto-merge API. Merge hanya dilakukan manual oleh Human Operator.
9. **Builder Self-Verification Mandate**: Setiap task packet wajib menginstruksikan builder untuk menjalankan seluruh acceptance commands dan menempelkan `Verification Audit Report` + raw output ke PR/report-back. Jika CLI memiliki skill system, panggil skill verifikasi yang setara; jika tidak, baca `VERIFY.md` dan laporkan `fallback_docs_read`. Lead tidak perlu otomatis memanggil verifier jika bukti self-verification lengkap, kecuali task menyentuh Tier A/gate/keuangan/keamanan, ada kontradiksi, atau verifier diminta operator.

# Required inputs
- Rancangan modul teknis dari sub-agent spesialis (`aeterna-*`).
- Daftar REQ ID dari `docs/aeterna/requirements.md`.
- File target implementasi dan test.

# Procedure
1. Baca template standar di `docs/aeterna/omp-task-template.md`.
2. Alokasikan Task ID dan nama branch `feat/m<Milestone>-<slug>`.
3. Petakan requirement ke file spesifik dan buat RTM task.
4. Tetapkan acceptance commands dengan runner resmi (`uv run`, `cargo`, `go`) serta seksi 8.1 Git workflow (`git checkout -b`, `git commit`, `git push`, `gh pr create`).
5. Daftarkan file ke entri ownership di `docs/aeterna/code-ownership.md`.
6. Tulis explicit instruction: `Jalankan acceptance commands, gunakan skill verifikasi jika tersedia atau baca VERIFY.md, lalu lampirkan Verification Audit Report + raw output ke PR/report-back.`
7. Tulis file task packet ke `.handoff/tasks/TASK-M<Milestone>-<Num>.md`.
8. Instruksikan operator mengeksekusi packet dengan CLI pilihan: Claude Code, Codex CLI, OpenCode, Antigravity CLI, atau builder lain yang mematuhi `AGENTS.md`.

# Output contract
File task packet lengkap pada path `.handoff/tasks/TASK-M<X>-<YY>.md` mematuhi 15 seksi `docs/aeterna/omp-task-template.md`.

# Self-check
1. [ ] Apakah semua file yang boleh disentuh tercantum di §2 Scope?
2. [ ] Apakah perintah acceptance test dapat dijalankan otomatis tanpa input manusia?
3. [ ] Apakah invariants cheatsheet tercantum lengkap?
4. [ ] Apakah RTM memiliki test case yang spesifik?
5. [ ] Apakah task packet memerintahkan verifikasi CLI-agnostic dan menempelkan raw output?

# Failure modes
- **Gejala**: Builder mengedit file di luar scope yang diizinkan.
- **Tindakan**: Verifier menolak laporan builder, instruksikan `git checkout -- <file_di_luar_scope>` dan ulangi pengujian.
