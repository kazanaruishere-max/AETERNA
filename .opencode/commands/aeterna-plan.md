## Preconditions
1. Dokumen acuan `PRD.md`, `architecture.md`, `security.md`, dan `docs/AGENTS.local.md` tersedia dan dapat dibaca.
2. Operator menentukan topik perancangan atau nomor requirement/milestone target.

## Inputs
- `$ARGUMENTS`: Topik arsitektur, modul yang hendak dirancang, atau nomor milestone (contoh: `M1 SQLite WAL Schema`).

## Procedure
1. Baca konteks wajib modul terkait sesuai `docs/aeterna/agent-contract.md`.
2. Delegasikan analisis mendalam ke sub-agent arsitek/spesialis yang berwenang (`aeterna-architect`, `aeterna-risk`, `aeterna-backtest`, atau lainnya).
3. Susun analisis pemisahan modul `engine/` vs `instruments/`, skema antarmuka, dan invariant finansial.
4. Periksa apakah terdapat kontradiksi antar-dokumen acuan.
5. Susun disposisi requirement (`COVERED / DEFERRED / REJECTED`) dan formulasi ADR.
6. Hasilkan rancangan terstruktur dalam format amplop baku tanpa menyentuh file kode produksi.

## Output
Amplop perancangan lengkap berstatus `READY` atau `NEEDS_DECISION` memuat skema, formula, dan identifikasi risiko.

## Abort conditions
- Parameter keuangan yang diusulkan melanggar `docs/aeterna/invariant-cheatsheet.md`.
- Terdeteksi usulan integrasi model LLM ke jalur eksekusi produksi (Zero-LLM violation).
