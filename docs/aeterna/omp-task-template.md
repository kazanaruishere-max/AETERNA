# Legacy Alias — Autonomous Builder Task Packet Template

Path `docs/aeterna/omp-task-template.md` dipertahankan hanya untuk kompatibilitas dengan task packet lama.

Template kanonik: `docs/aeterna/task-packet-template.md`.

Jika file ini dibuka oleh agent/harness mana pun:

1. Baca template kanonik di atas.
2. Gunakan `aeterna-task-protocol` sebagai protokol penulisan dan evaluasi.
3. Jangan memperlakukan OMP sebagai satu-satunya builder.
4. Laporkan `fallback_docs_read` bila skill system tidak tersedia.

Task packet baru wajib mengikuti format v4 dengan `protocol: aeterna-task-protocol`.
