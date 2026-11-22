# AETERNA Quant

[![Lisensi: AGPL-3.0-only](https://img.shields.io/badge/License-AGPL--3.0--only-blue.svg)](LICENSE)
[![Status: P1 Journal](https://img.shields.io/badge/Status-P1%20Journal-yellow.svg)](docs/aeterna/VERIFIED_TRACKRECORD.md)
[![Mode: SIGNAL_ONLY](https://img.shields.io/badge/Mode-SIGNAL__ONLY-blue.svg)](VERIFY.md)

AETERNA Quant adalah engine riset deterministik eksperimental untuk XAUUSD. Sistem ini menggabungkan runtime multi-timeframe, state machine spread/berita, jurnal virtual, watchdog Go independen, dan panel administrasi Telegram.

> Ini perangkat lunak riset, bukan nasihat keuangan dan bukan layanan sinyal. Lihat [DISCLAIMER.md](DISCLAIMER.md).

## Status

- Fase: `P1 Journal`
- Mode runtime: `SIGNAL_ONLY`, `LIVE_ORDER=DISABLED`
- Gate: `GATE-M4 PASSED`
- Menunggu: `GATE-M5`, `GATE-VIRTUAL-JOURNAL`
- Tidak ada klaim performa. "Terverifikasi" berarti tes deterministik dan gate teknis, bukan profitabilitas.

Lihat [Catatan Terverifikasi](docs/aeterna/VERIFIED_TRACKRECORD.md).

## Arsitektur

- **Python 3.12+**: tri-loop runtime, adapter strategi, virtual tracker, isolasi DPAPI, kontrol admin Telegram.
- **Rust/PyO3**: PnL backtest, pemodelan slippage, verifikasi Monte Carlo.
- **Go**: watchdog lokal independen dan gerbang risiko pra-entry.
- **SQLite WAL**: skema kanonik, cursor bar, observasi sinyal, telemetri berita.
- **ONNX Runtime CPU**: inferensi regime deterministik. Tidak ada LLM di jalur produksi.

## Multi-Timeframe

| Layer | Timeframe | Fungsi |
| :--- | :--- | :--- |
| Regime | H4 | Deteksi bias makro |
| Setup | H1 | Konteks struktur dan level |
| Eksekusi | M15 | Observasi entry, SL/TP, invalidasi waktu |

## Verifikasi

Perintah persis, keluaran yang diharapkan, peta gate, dan item yang belum terverifikasi ada di [VERIFY.md](VERIFY.md).

## Data dan Reproducibility

Database broker, data tick, log live, laporan akun, identifier akun, dan weight model tanpa lisensi tidak dipublikasikan. Reproduksi dilakukan dari sumber data Anda sendiri dengan membandingkan invariant struktural, bukan PnL.

## Keamanan

Lihat [SECURITY.md](SECURITY.md). Laporkan kerentanan secara privat melalui tab Security repository.

## Legal

- Sumber: [AGPL-3.0-only](LICENSE)
- [DISCLAIMER.md](DISCLAIMER.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [CHANGELOG.md](CHANGELOG.md)

## Bukan Tujuan

- Siaran sinyal publik/VIP pada rilis ini.
- Order live otonom oleh agen AI.
- Nasihat investasi, hukum, atau pajak.
- Klaim performa yang tidak dapat diverifikasi.
