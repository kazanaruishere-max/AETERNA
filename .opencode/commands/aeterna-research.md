## Preconditions
1. Pertanyaan riset dirumuskan dalam satu kalimat yang bisa dijawab ya/tidak.
2. Topik belum memiliki brief aktif di `.handoff/research/` (atau brief lama sudah kedaluwarsa >90 hari).

## Skills Injected
{file:.opencode/skills/aeterna-invariants/SKILL.md}

## Source Registry
Baca `docs/aeterna/RESEARCH_SOURCES.md`. Untuk topik strategi trading, SSRN Blog Trading Strategies (`https://blog.ssrn.com/tag/trading-strategies/`) adalah index discovery; ikuti tautan ke paper SSRN/DOI/PDF asli sebelum klaim apa pun berstatus `EVIDENCE`.

## Inputs
- `$ARGUMENTS`: pertanyaan riset (contoh: `mean-reversion M15 pada EURUSD sesi Asia`).

## Procedure
1. Panggil sub-agent `aeterna-research`; pastikan ia tidak menulis di luar `.handoff/research/`.
2. Untuk strategi trading, kumpulkan kandidat dari SSRN Blog Trading Strategies, lalu buka paper SSRN/DOI/PDF asli. Sumber primer lain: arXiv/DOI, BIS, Fed, dokumentasi broker. Blog, forum, dan konten afiliasi hanya sebagai petunjuk awal, bukan bukti.
3. Beri tag taksonomi pada setiap klaim: `EVIDENCE` | `HYPOTHESIS` | `CONTRADICTED` | `UNVERIFIED`.
4. Wajibkan untuk setiap `EVIDENCE`: URL, tahun, tanggal akses, sampel, periode, horizon, dan status biaya transaksi.
5. Turunkan ke `HYPOTHESIS` jika tranferabilitas ke M15–H1 retail belum jelas.
6. Tulis minimal satu kriteria falsifikasi yang bisa dijalankan di Rust backtest kita, dengan ambang gagal dalam angka.
7. Simpan ke `.handoff/research/BRIEF-<slug>.md`, lalu kembalikan ringkasan + verdict (`ADOPT` | `TEST_FIRST` | `REJECT`) ke Lead.

## Output
Brief riset berlabel di `.handoff/research/BRIEF-<slug>.md` dengan daftar `unverified_items` yang diekspos terbuka.

## Abort conditions
- Sumber utama tidak dapat diakses atau tidak dapat diverifikasi ulang lewat URL.
- Brief akan menyimpulkan `ADOPT` tanpa bukti sampel/periode/biaya.
- Rekomendasi menyentuh pelonggaran invariant risiko.
