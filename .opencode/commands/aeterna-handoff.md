## Preconditions
1. Sesi kerja hendak diakhiri, atau terjadi transisi milestone / pergantian topik besar.

## Skills Injected
{file:.opencode/skills/aeterna-handoff/SKILL.md}

## Inputs
- `$ARGUMENTS`: Catatan opsional atau instruksi prioritas untuk sesi berikutnya.

## Procedure
1. Muat skill `aeterna-handoff`.
2. Baca commit git terakhir via `git log -1 --oneline`.
2. Evaluasi status Milestone Gate saat ini (`docs/aeterna/requirements.md`).
3. Kumpulkan task yang selesai, task yang sedang berjalan, dan blocker yang aktif.
4. Tulis file handoff tanggal hari ini: `.handoff/YYYY-MM-DD.md`.
5. Perbarui file `.handoff/latest.md` dengan snapshot lengkap.
6. Berikan ringkasan handoff 3 baris ke command line interface.

## Output
File `.handoff/YYYY-MM-DD.md` dan `.handoff/latest.md` terisi lengkap dan ringkasan status operasional.

## Abort conditions
- Terdapat kredensial sensitif atau kata sandi yang tidak sengaja tertulis pada teks handoff.
