# Research Source Registry

Dokumen ini mendefinisikan sumber mana yang boleh dipakai `aeterna-research` untuk mencari paper, data, dan bukti strategi trading. Status bukti tetap mengikuti `docs/aeterna/agent-contract.md §8`.

## Source Hierarchy

| Level | Jenis | Contoh | Status default |
| :--- | :--- | :--- | :--- |
| 1 | Primary paper | SSRN paper page/PDF, arXiv, journal DOI | Boleh `EVIDENCE` jika lengkap |
| 2 | Official/venue | BIS, Federal Reserve/FRED, exchange rules, broker docs | Boleh `EVIDENCE` jika lengkap |
| 3 | Internal evidence | `db/schema.sql`, internal DB, backtest golden tests, audit reports | Boleh `EVIDENCE` internal |
| 4 | Discovery only | blog, forum, newsletter, aggregator, affiliate content | Tidak pernah `EVIDENCE` |

## SSRN Trading Strategies Blog

URL:

```text
https://blog.ssrn.com/tag/trading-strategies/
```

Accessed:

```text
2026-11-21
```

Role:

```text
DISCOVERY_ONLY
```

Rules:

1. Gunakan hanya untuk menemukan judul/topik paper trading strategy.
2. Jangan pakai halaman blog sebagai bukti ilmiah.
3. Ikuti tautan ke paper SSRN asli, DOI, atau PDF.
4. Catat SSRN ID/DOI, penulis, tanggal paper, abstrak, sampel, periode, instrumen, horizon, dan biaya transaksi.
5. Jika hanya halaman blog/top-list yang tersedia, status klaim adalah `UNVERIFIED`.
6. Halaman ini saat ini banyak berisi arsip top-paper 2019–2020; jangan mengklaim sebagai riset terkini tanpa verifikasi tanggal paper.

## Primary Source Checklist

Sebuah paper hanya boleh menjadi `EVIDENCE` jika memuat:

- penulis dan institusi;
- tahun/tanggal;
- SSRN ID, DOI, atau identifier lain yang bisa dicek;
- abstrak atau teks penuh;
- instrumen dan sampel;
- jumlah observasi;
- periode data;
- horizon (tick/M15/H1/H4/D1);
- apakah spread, komisi, slippage, dan biaya pinjaman/funding diperhitungkan;
- hasil yang bisa direproduksi atau setidaknya kriteria falsifikasi yang jelas.

Jika salah satu item kritis hilang, turunkan status ke `HYPOTHESIS` atau `UNVERIFIED`.

## Transferability Gate

Paper yang menggunakan futures institusional,High Frequency Trading, atau data pra-2015 tidak otomatis berlaku untuk retail XAUUSD M15–H1. Jika perbedaan venue/periode/biaya tidak dibahas, statusnya turun menjadi `HYPOTHESIS`.

## Internal Data Sources

Sumber internal yang boleh dipakai untuk falsifikasi:

- `db/schema.sql` — struktur dan batas data.
- `data/trading.db` atau DB turunan lokal — observasi, candle, state, dan hasil backtest.
- `tests/analysis/` — golden test dan determinisme backtest.
- `docs/aeterna/VERIFIED_TRACKRECORD.md` — status gate teknis.
- `docs/aeterna/agent-audit-latest.md` — audit internal bila diperlukan.

## Forbidden as Evidence

- Blog post tanpa paper asli.
- Forum, komentar, media sosial, dan konten afiliasi.
- Klaim performa tanpa sampel dan periode.
- Angka PnL/equity/ticket/server dari hasil eksperimen lokal yang masuk brief riset publik.
- Sumber yang tidak bisa dibuka ulang lewat URL/DOI.
