---
name: aeterna-handoff
description: Protokol pencatatan state sesi, status milestone gate, task aktif OMP, dan mitigasi risiko ke .handoff/latest.md.
license: Proprietary
compatibility: opencode
metadata:
  workflow: handoff
  persistence: local
---

# Purpose
Menjamin kontinuitas proyek tanpa kehilangan konteks antara sesi kerja, antar-subagent, dan antara Lead Architect dengan builder OMP. Menyimpan rekam jejak state milestone, keputusan arsitektur, dan mitigasi risiko secara deterministik.

# When to use
- Gunakan pada akhir sesi kerja sebelum menutup terminal.
- Gunakan saat pergantian topik besar atau transisi antar milestone.
- Gunakan pada awal sesi baru untuk memulihkan konteks kerja terakhir.

# Hard rules
1. File handoff disimpan di `.handoff/YYYY-MM-DD.md` dan disalin ke `.handoff/latest.md`.
2. Dilarang menyertakan kredensial, API key, atau kata sandi akun MT5 ke dalam file handoff.
3. Wajib menyertakan Gate Ledger dengan status riil (tidak boleh mengasumsikan lulus tanpa bukti log).
4. Wajib mencantumkan daftar risiko kritis (P0/P1) dan cara mendeteksinya.
5. Task berikutnya wajib mencantumkan owner sub-agent dan entry criteria.

# Required inputs
- Milestone aktif saat ini (M1–M7).
- Hasil verifikasi terakhir dari `aeterna-verifier`.
- Daftar task OMP yang sedang berjalan atau antre di `.handoff/tasks/`.

# Procedure
1. Baca status commit git terakhir: `git log -1 --oneline`.
2. Evaluasi status Milestone Gate saat ini (`GATE-M1` s.d. `GATE-M7`).
3. Kumpulkan task yang selesai, sedang aktif, dan terblokir.
4. Tulis dokumen handoff mengikuti template resmi.
5. Salin konten ke `.handoff/latest.md`.
6. Informasikan ke operator ringkasan handoff 3 baris.

# Output contract
```markdown
# HANDOFF <YYYY-MM-DD>
## 1. Snapshot
- Milestone: M<1-7> (<Nama Milestone>)
- Active Branch: <branch>
- Latest Commit: <hash>
- Rigor Tier: A | B | C

## 2. Gate Ledger
- Gate: GATE-M<X>
- Evidence Command: <perintah>
- Status: PASS | IN_PROGRESS | BLOCKED

## 3. Decision Log
- ADR Terakhir: ADR-00X (<Ringkasan>)

## 4. Active OMP Tasks
- TASK-M<X>-<YY>: [STATUS] -> Files: <path>

## 5. Critical Risks (P0/P1) & Detection
- Risiko: <Deskripsi> | Deteksi: <Cara Cek>

## 6. Next 3 Actions
1. [ ] Action 1 (Owner: aeterna-<role>)
2. [ ] Action 2 (Owner: aeterna-<role>)
3. [ ] Action 3 (Owner: OMP)
```

# Self-check
1. [ ] Apakah `.handoff/latest.md` telah diperbarui?
2. [ ] Apakah tidak ada API key atau password di teks handoff?
3. [ ] Apakah bukti command gate berasal dari output terminal riil?

# Failure modes
- **Gejala**: Handoff menyebutkan milestone lolos padahal belum ada log test.
- **Tindakan**: Verifier menandai `status: BLOCKED`, handoff wajib dikembalikan ke status `IN_PROGRESS` hingga test riil dijalankan.
