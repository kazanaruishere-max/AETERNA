# AETERNA Agent Entrypoint

Dokumen ini adalah pintu masuk netral untuk agent CLI apa pun.

## Wajib Dibaca

1. `docs/aeterna/agent-state.md`
2. `docs/aeterna/invariant-cheatsheet.md`
3. `docs/aeterna/REPO_BOUNDARY.md`
4. `docs/aeterna/AUTONOMOUS_BUILDER.md`
5. `task_packet` yang ditunjuk oleh `agent-state.md`, jika `active_task` tidak null

Jangan membaca seluruh repo terlebih dahulu. Jangan mengarang konteks yang tidak ada di sumber-sumber di atas. Baca `docs/aeterna/agent-audit-latest.md` hanya jika gate gagal atau task menyentuh known defect. Baca `docs/aeterna/agent-contract.md` hanya sebelum envelope final atau pekerjaan gate/security.

## Aturan Kerja

- Jika `active_task` null, jangan menulis kode; lakukan audit read-only atau berhenti.
- Sebelum mulai, pastikan `base_commit` adalah ancestor dari `HEAD` (`git merge-base --is-ancestor <base_commit> HEAD`); jika gagal, laporkan `BLOCKED`.
- Hanya sentuh `allowed_paths` dari task packet.
- Jalankan `acceptance_commands` dari task packet dan lampirkan output asli.
- Jika menjadi builder, ikuti `docs/aeterna/AUTONOMOUS_BUILDER.md` dan protokol kanonik `aeterna-task-protocol` (`aeterna-task-protocol` adalah skill; `omp-task-protocol` hanya alias deprecated). Jika harness memiliki skill system, muat skill yang tersedia; jika tidak, baca fallback doc dan laporkan `fallback_docs_read` + `builder_harness`. Raw output wajib ditempelkan ke PR/report-back.
- Wajib memakai envelope `docs/aeterna/agent-contract.md §7`.
- Dilarang `gh pr merge`, `git merge`, `order_send`, `PositionModify`, atau mematikan 9router port 20128.
- Berhenti setelah membuat PR. Merge hanya oleh human operator.
- Jika konteks bertentangan atau gate belum valid, laporkan `NEEDS_DECISION`/`BLOCKED`, jangan menebak.
