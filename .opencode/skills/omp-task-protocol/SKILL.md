---
name: omp-task-protocol
description: Protokol penyusunan, pembatasan scope, dan evaluasi paket tugas mandiri (self-contained task packet) untuk builder OMP.
license: Proprietary
compatibility: opencode
metadata:
  target_builder: omp
  workflow: task-packet
---

# Purpose
Mengatur standarisasi pembuatan paket tugas mandiri (*task packet*) dari OpenCode ke OMP (`omp.exe`), pembatasan file yang boleh disentuh (*scope boundary*), dan format evaluasi hasil pekerjaan agar bebas dari celah kritis.

# When to use
- Gunakan saat `aeterna-briefer` mengubah rancangan teknis yang telah disetujui menjadi paket tugas siap eksekusi.
- Gunakan saat memvalidasi apakah paket tugas sudah memenuhi Definition of Ready (DoR).
- Gunakan saat membaca dan memverifikasi laporan balik hasil kerja OMP.

# Hard rules
1. Task packet wajib mandiri (*self-contained*): OMP tidak boleh membutuhkan riwayat chat OpenCode.
2. File yang boleh disentuh wajib di-*whitelist* eksplisit pada seksi `Scope`. File di luar scope dilarang disentuh.
3. Wajib menyertakan RTM (`REQ-*`), hard invariants, dan acceptance commands mekanis.
4. Wajib menyertakan deklarasi efek samping (*side-effects declaration*).
5. Jika berupa tugas refactoring, wajib menyertakan path *characterization test* eksisting.
6. Diff budget maksimal 3 file dan < 300 baris per task packet.

# Required inputs
- Rancangan modul teknis dari sub-agent spesialis (`aeterna-*`).
- Daftar REQ ID dari `docs/aeterna/requirements.md`.
- File target implementasi dan test.

# Procedure
1. Baca template standar di `docs/aeterna/omp-task-template.md`.
2. Petakan requirement ke file spesifik dan buat RTM task.
3. Tetapkan acceptance commands dengan runner resmi (`uv run`, `cargo`, `go`).
4. Daftarkan file ke entri ownership di `docs/aeterna/code-ownership.md`.
5. Tulis file task packet ke `.handoff/tasks/TASK-M<Milestone>-<Num>.md`.
6. Instruksikan operator untuk mengeksekusi OMP: `omp @.handoff/tasks/TASK-M<Milestone>-<Num>.md`.

# Output contract
File task packet lengkap pada path `.handoff/tasks/TASK-M<X>-<YY>.md` mematuhi 15 seksi `docs/aeterna/omp-task-template.md`.

# Self-check
1. [ ] Apakah semua file yang boleh disentuh tercantum di §2 Scope?
2. [ ] Apakah perintah acceptance test dapat dijalankan otomatis tanpa input manusia?
3. [ ] Apakah invariants cheatsheet tercantum lengkap?
4. [ ] Apakah RTM memiliki test case yang spesifik?

# Failure modes
- **Gejala**: OMP mengedit file di luar scope yang diizinkan.
- **Tindakan**: Verifier menolak laporan OMP, instruksikan `git checkout -- <file_di_luar_scope>` dan ulangi pengujian.
