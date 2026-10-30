## Preconditions
1. Rancangan arsitektur untuk modul target telah berstatus `READY` atau disetujui oleh Lead Architect.
2. Requirement terkait telah terdaftar di `docs/aeterna/requirements.md`.

## Inputs
- `$ARGUMENTS`: ID atau nama rancangan modul yang hendak diubah menjadi task packet OMP (contoh: `TASK-M1-01 SQLite Schema`).

## Procedure
1. Panggil sub-agent `aeterna-briefer`.
2. Muat template `docs/aeterna/omp-task-template.md`.
3. Tentukan file yang di-whitelist pada seksi `Scope` (maksimal 3 file) dan tetapkan batasan `Forbidden Scope`.
4. Rincikan persyaratan implementasi yang bertestable, RTM task, dan invariants numerik.
5. Susun perintah Acceptance Commands otomatis (`uv run pytest`, `cargo test`, `go test`, linter).
6. Deklarasikan ketiadaan efek samping (*side-effects*) dan tetapkan diff budget.
7. Tulis file task packet ke `.handoff/tasks/TASK-M<X>-<YY>.md`.
8. Tampilkan perintah terminal untuk dieksekusi oleh operator via OMP.

## Output
File paket tugas mandiri `.handoff/tasks/TASK-M<X>-<YY>.md` berstatus `READY` dan instruksi pemanggilan OMP.

## Abort conditions
- Modul belum memiliki acceptance criteria atau test case yang dapat diuji mekanis.
- Scope file tidak dibatasi dengan tegas atau mencoba memodifikasi file di luar modul yang ditugaskan.
