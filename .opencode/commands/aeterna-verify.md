## Preconditions
1. Builder OMP telah menyelesaikan implementasi task packet dan melaporkan hasil eksekusinya.
2. File task packet acuan tersedia di `.handoff/tasks/`.

## Inputs
- `$ARGUMENTS`: ID Task yang hendak diaudit (contoh: `TASK-M1-01`).

## Procedure
1. Panggil sub-agent `aeterna-verifier`.
2. Verifikasi kepatuhan scope via `git diff --stat`: pastikan tidak ada file di luar whitelist yang disentuh.
3. Verifikasi pendaftaran kepemilikan kode di `docs/aeterna/code-ownership.md`.
4. Jalankan linter dan formatter resmi (Python `ruff` & `pyright`, Rust `clippy`, Go `go vet`).
5. Jalankan test suite dan Golden Tests deterministik di terminal; tangkap teks output asli.
6. Periksa RTM di `docs/aeterna/requirements.md` dan pastikan seluruh REQ task terverifikasi.
7. Terbitkan Verification Report dan Blok Accountability.

## Output
Laporan audit kelulusan verifikasi (`PASS` atau `FAIL`) dengan output riil terminal dan Blok Accountability.

## Abort conditions
- Terdapat error/warning linter atau typecheck yang diabaikan.
- Ditemukan modifikasi pada file di luar scope yang ditentukan.
- Terjadi deviasi numerik pada Golden Test kalkulasi risiko finansial.
