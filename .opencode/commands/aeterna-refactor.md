## Preconditions
1. Kode target yang hendak di-refactor telah memiliki characterization test suite yang lulus 100%.
2. Alasan refactoring jelas (peningkatan maintainability/modularitas/efisiensi), bukan sekadar preferensi kosmetik.

## Inputs
- `$ARGUMENTS`: Path file atau modul yang hendak di-refactor (contoh: `engine/risk_gate/sizing.py`).

## Procedure
1. Panggil sub-agent `aeterna-architect` dan `aeterna-verifier` untuk two-key review.
2. Identifikasi batasan perilaku yang dilarang berubah (*behavior-preserving invariant*).
3. Verifikasi bahwa unit test eksisting mengunci perilaku saat ini (*characterization test lock*).
4. Panggil `aeterna-briefer` untuk menyusun task packet refactor dengan seksi §12 Refactor Contract dan §13 Side-Effect Declaration terisi penuh.
5. Instruksikan OMP untuk menjalankan refactor dengan commit terpisah bertipe `refactor(...)`.
6. Jalankan kembali test suite yang sama pasca-refactor untuk membuktikan parity 100%.

## Output
Task packet refactoring aman di `.handoff/tasks/` dengan deklarasi ketiadaan efek samping fungsional.

## Abort conditions
- Modul target belum memiliki automated test suite yang memadai untuk mengunci perilaku eksisting.
- Refactoring mencoba mengubah kontrak publik API atau skema database tanpa tiket migrasi terpisah.
