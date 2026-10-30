# Technical Architecture Specification — AI Trading XAUUSD (v1.0)

Dokumen ini merupakan spesifikasi teknis resmi yang diturunkan dari `ai-trading-master-reference.md` (§4–11, §14) serta kesepakatan desain teknis planning. Dokumen ini menjadi acuan utama implementasi perangkat lunak.

---

## 1. Ikhtisar Arsitektur & Prinsip Desain

Arsitektur sistem dibangun dalam 4 fase modular yang beroperasi secara asinkron dengan prinsip **fail-safe default**:
```
[Fase 1: Ingestion & Filter] → [Fase 2: Analysis Engine] → [Fase 3: Risk & Execution] → [Fase 4: Monitoring & Feedback]
                                      ▲                                                      │
                                      └──────────── Retraining Periodik (Human-in-the-Loop) ─┘
```

### Prinsip Utama
1. **Fail-Safe Default**: Apabila terjadi kegagalan jaringan, anomali data, atau timeout service, sistem wajib default ke posisi *NO-ENTRY* (tidak membuka order baru).
2. **Deterministic Risk Protection**: Proteksi saldo adalah kewenangan proses pengawas independen (*watchdog*), bukan ditentukan oleh model prediksi.
3. **Comprehensive Decision Logging**: Semua keputusan (termasuk sinyal yang dibatalkan/di-block) wajib dicatat ke dalam database untuk auditabilitas penuh.
4. **Separation of Concerns**: Penelitian offline (berat) dipisahkan total dari eksekusi live (ringan, deterministik, sub-detik).

---

## 2. Tech Stack & Komunikasi Antar-Service

| Layer / Komponen | Teknologi | Alasan Pemilihan & Karakteristik |
| :--- | :--- | :--- |
| **Trigger & Scheduling** | Go | Efisien, konkurensi native, footprint memori minimal untuk scheduler |
| **Data Ingestion** | Python 3.12+ (via `uv`) | Ekosistem API lengkap: OANDA v20 REST, MetaTrader 5, dan `fredapi` (data makro & kalender rilis jadwal NFP/CPI/FOMC) |
| **Feature Engineering & Backtest** | Rust (via PyO3) | Performa komputasi tinggi, *memory safety*, eliminasi bottleneck numerik |
| **Model Training** | Python + PyTorch | Framework standar untuk fine-tuning Kronos foundation model |
| **Model Inference (Live)** | ONNX Runtime (CPU) | Sangat ringan, deterministik, latensi rendah di CPU laptop/VPS |
| **Risk Gate Watchdog** | Go | Proses daemon terpisah, independen dari runtime Python/MT5 |
| **Eksekusi Broker** | Python (`MetaTrader5`) | Library resmi Exness MT5 untuk integrasi Windows native |
| **Distribusi Sinyal & Kontrol** | Python / Go | Telegram Bot API (long polling / webhook privat), 2 stream terpisah |
| **Penyimpanan Operasional (Hot)** | SQLite (WAL Mode) | Zero-maintenance IPC antarservice, ACID compliant, latency microsecond |
| **Penyimpanan Arsip (Warm)** | Parquet terkompresi | Format kolom efisien untuk data historis dan pelatihan rolling window |

### Kebijakan Library Eksternal & Audit Kalender Makro
- **Hasil Audit Rigor Kalender Makro (Finnhub & FMP)**:
  - *Finnhub*: Endpoint `/calendar/economic` berstatus **Premium Access Required** (`freeTier: null`); free tier hanya mencakup corporate earnings.
  - *Financial Modeling Prep (FMP)*: Endpoint `/stable/economic-calendar` berstatus **HTTP 402 Payment Required** (`Restricted Endpoint`); free tier FMP tidak mencakup rilis NFP/CPI/PMI.
  - *Solusi Resmi & 100% Free*: Menggunakan **FRED API (`fredapi`)** dari Federal Reserve Bank of St. Louis. Endpoint `release/dates` FRED menyediakan jadwal resmi publikasi ekonomi AS jauh hari sebelumnya (`release_id=10` untuk CPI, `release_id=50` untuk Employment/NFP, `release_id=53` untuk GDP, `release_id=82` untuk PCE) dengan kuota 120 req/menit.
  - *Mekanisme Polling Kalender vs Live Spread*: Kalender blackout (Layer 1) **TIDAK di-poll per detik**; data ditarik 1x per hari saat engine booting / pembukaan sesi. Yang di-poll per detik saat `PRE_NEWS_WATCH` / `PAUSED` adalah **Z-score spread real-time (Layer 2) dari streaming quote MT5**, sehingga konsumsi API eksternal mendekati nol.
- **Larangan Keras Provider Harga Pihak Ketiga**: Dilarang keras menambahkan library data pasar eksternal seperti `yfinance`, `twelvedata`, `polygon-api-client`, `ib_insync`, `alpaca-trade-api`, `tradier`, `marketstack`, atau `tiingo`. Seluruh data harga XAUUSD (M1 OHLCV, tick volume, streaming quote) **100% dipasok oleh OANDA v20 REST (scanning) dan Exness MT5 (eksekusi)**. Provider lain redundan dan berisiko latensi/inkonsistensi spread.

### Mekanisme IPC (Inter-Process Communication) MVP
Sesuai prinsip kesederhanaan, komunikasi antar-service memanfaatkan **Shared SQLite dengan mode WAL (Write-Ahead Logging)**.
- Watchdog, Ingestion, dan Execution membaca/menulis state melalui tabel database terdedikasi.
- Mode WAL mencegah lock write-blocking-read pada lingkungan Windows.
- Polling frekuensi pendek (1–3 detik) pada tabel state sudah mencukupi kebutuhan timeframe intraday M15–H4 tanpa memerlukan broker antrian seperti Kafka/ZeroMQ.

---

## 2.1 Struktur Direktori & Organisasi Kode

Struktur direktori dirancang dengan prinsip modularitas tinggi, memisahkan secara ketat antara **logika engine inti yang agnostik terhadap instrumen** dengan **konfigurasi/strategi spesifik per instrumen pasar**:

```
ai-trading-xauusd/
├── docs/
│   ├── PRD.md
│   ├── architecture.md
│   ├── security.md
│   └── agents.md
├── engine/
│   ├── ingestion/
│   │   ├── python/
│   │   └── go/
│   ├── state_machine/
│   ├── analysis_engine/
│   │   ├── rust/
│   │   └── python/
│   ├── risk_gate/
│   ├── execution/
│   ├── telegram_bot/
│   └── monitoring/
├── instruments/
│   └── xauusd/
│       ├── config/
│       │   └── parameters.yaml
│       ├── strategies/
│       │   ├── volatility_breakout.py
│       │   ├── positioning_contrarian.py
│       │   ├── intermarket_correlation.py
│       │   └── mean_reversion.py
│       └── macro_features/
├── data/
├── tests/
├── .worktrees/
├── go.mod
└── pyproject.toml
```

### Rasional & Prinsip Desain Direktori
1. **Pemisahan `engine/` (Shared, Asset-Agnostic) vs `instruments/` (Pair-Specific)**:
   - Direktori `engine/` memuat komponen inti yang berlaku universal untuk instrumen apa pun: watchdog, state machine, analysis engine runtime, risk gate, execution bridge MT5, bot Telegram, dan monitoring.
   - Mengikuti prinsip *Separation of Concerns* (§1), engine didesain *config-driven*. Saat sistem diekspansi ke pair baru di masa depan (misal: EURUSD, GBPUSD sesuai PRD §2 Fase 3), pengembang **hanya perlu menambah folder instrumen baru** di bawah `instruments/` (misal `instruments/eurusd/`). Seluruh kode di `engine/` **tidak perlu diduplikasi atau diubah**.
2. **Dokumentasi Terpusat di `docs/`**:
   - Seluruh dokumen acuan proyek (`PRD.md`, `architecture.md`, `security.md`, `agents.md`) berada di root direktori `docs/` karena aturan operasional dan arsitektur berlaku untuk keseluruhan proyek, bukan terbatas pada satu pair tertentu.
3. **Konfigurasi `instruments/xauusd/config/parameters.yaml`**:
   - File konfigurasi ini merujuk langsung ke *Starting Parameters YAML* yang telah dispesifikasikan di §9 dokumen ini. Parameter tidak di-hardcode ke dalam kode sumber, melainkan dimuat secara dinamis saat startup.
4. **Strategi Modular di `instruments/xauusd/strategies/`**:
   - Mengisolasi 4 kategori strategi XAUUSD dari §4.1 ke dalam modul terpisah (`volatility_breakout.py`, `positioning_contrarian.py`, `intermarket_correlation.py`, `mean_reversion.py`). Masing-masing strategi mengimplementasikan interface standar yang dievaluasi oleh engine.
5. **Riset Penggerak Makro di `instruments/xauusd/macro_features/`**:
   - Khusus memuat modul kalkulasi variabel makro spesifik XAUUSD (US Real Yield / TIPS 10Y, DXY, pembelian bank sentral) sesuai rancangan §4. Fitur ini diisolasi karena dinamika makro emas berbeda dari pasangan mata uang konvensional.
6. **Penamaan Flat `instruments/xauusd/`**:
   - Penamaan sengaja dibuat flat per-pair (bukan `forex/xauusd/` atau `commodities/xauusd/`) karena secara klasifikasi kontrak broker Exness, XAUUSD masuk kategori *Metals/Commodities*, bukan *Forex*. Jika di masa depan diperlukan pengelompokan kelas aset multi-level, strukturnya akan diperluas secara paralel (`instruments/metals/xauusd/`, `instruments/forex/eurusd/`), bukan bersarang (*nested*). Untuk rilis v1.0, struktur flat adalah pilihan paling sederhana dan efisien.
7. **Isolasi Data & Worktree di `.gitignore`**:
   - Direktori `data/` (penyimpanan database lokal SQLite WAL dan cache Parquet) serta `.worktrees/` (lingkungan kerja terisolasi sub-agent Orca) **wajib terdaftar di `.gitignore`** untuk mencegah kebocoran data historis berukuran besar atau konflik branch antar-agent.

---

## 3. Fase 1 — Ingestion & Filtering

### 3.1 Dual-Broker Architecture
Sistem memisahkan peran broker secara ketat untuk mencegah kontaminasi eksekusi:
- **OANDA (Scanning Only)**: Menggunakan v20 REST/Streaming API langsung. Data *Order/Position Book* OANDA digunakan khusus untuk fitur sentimen positioning retail jangka menengah (refresh tiap 15–30 menit). **OANDA tidak pernah menerima order eksekusi.**
- **Exness (Eksekusi, Forward Test, Live)**: Menggunakan terminal MT5 lokal via package `MetaTrader5` Python resmi pada akun Standard.

### 3.1.1 Leverage Isolation Guard & Margin Calculation
1. **OANDA Leverage Irrelevance**:
   - OANDA berstatus *scanning-only*. Pembatasan leverage pada akun OANDA (misal regulasi 1:20 ESMA/FCA) **TIDAK RELEVAN DAN DILARANG KERAS DIGUNAKAN** sebagai parameter apa pun di backtest engine maupun margin simulation.
2. **Peran Leverage di Exness Standard**:
   - Leverage broker **TIDAK MEMPENGARUHI** kalkulasi PnL per trade:
     $$\text{PnL} = \text{Lot Size} \times \Delta\text{Price} \times \text{Contract Size (100 oz)}$$
   - Leverage akun Exness Standard (dikonfigurasi eksplisit di `parameters.yaml` sebagai placeholder, misal `account_leverage: 200 # TODO: placeholder - update after verification from own Standard account`) HANYA digunakan untuk:
     a. *Margin Availability Check*: Memastikan Free Margin akun mencukupi sebelum order dikirim:
        $$\text{Margin Required} = \frac{\text{Lot Size} \times \text{Contract Size} \times \text{Entry Price}}{\text{Account Leverage}}$$
     b. *Margin Call / Stop-out Simulation*: Memodelkan likuidasi paksa broker saat stress test drawdown ekstrem.
3. **Penyusunan Config Backtest**:
   - Backtest engine memparameterisasi leverage secara independen melalui konfigurasi, bukan hardcode dan bukan meminjam batasan OANDA.

### 3.2 Granularitas Data
- **Data Historis & Storage**: Disimpan dalam format **M1 OHLCV + Tick Volume**. MT5 menyediakan data ini secara native tanpa membebani disk (menghindari raw tick storage puluhan gigabyte).
- **Data Live Monitoring**: Polling harga bid/ask streaming per beberapa detik untuk kalkulasi Z-score spread real-time pada state machine.

### 3.3 News & Volatility State Machine
State machine memproteksi modal dengan menolak trading saat terjadi rilis berita berdampak tinggi:
```
NORMAL ───────► (News terjadwal masuk window / -10 min) ───────► PRE_NEWS_WATCH
                                                                     │
                                                                     ▼ (Waktu rilis / Z > 3.0)
NORMAL ◄────── (Stabil M menit) ◄────── RECOVERY_CHECK ◄─────── PAUSED
                                              │ (Z naik > 1.5)       ▲
                                              └──────────────────────┘
[MANUAL_OVERRIDE] ◄─── Diaktifkan via kontrol Telegram kapan saja
```

#### Formula Matematis State Machine
1. **Spread Baseline (EWMA per sesi trading)**:
   $$S_{baseline}(t) = \alpha \cdot S(t) + (1 - \alpha) \cdot S_{baseline}(t - 1)$$
   dengan $\alpha = 0.08$.
2. **Z-Score Spread Real-Time**:
   $$Z(t) = \frac{S(t) - S_{baseline}(t)}{\sigma_S(t)}$$
3. **Logika Transisi**:
   - Masuk `PAUSED`: $Z(t) \ge 3.0$ ATAU waktu saat ini berada dalam jendela kalender berita *high-impact*.
   - Masuk `RECOVERY_CHECK`: $Z(t) < 1.5$ bertahan selama minimal $K = 12$ pembacaan berturut-turut.
   - Kembali ke `NORMAL`: Kondisi stabil bertahan selama $M = 5$ menit tanpa anomali.

#### 3.3.1 Dynamic DST-Aware Session Engine & Timezone Integrity
1. **Penyimpanan Database (UTC Integrity)**:
   - Seluruh kolom `timestamp` di SQLite (`trades`, `blocked_signals`, `model_registry`) **WAJIB disimpan dalam format string UTC ISO-8601 baku** (contoh: `2026-10-30T06:00:00Z`).
   - Dilarang menyimpan waktu lokal atau WIB di database engine. Konversi ke waktu lokal hanya dilakukan pada layer presentasi (Telegram Bot & Dashboard).
2. **Larangan Hardcoded UTC Offset**:
   - Boundary sesi perdagangan (London Open, NY Open, overlap London-NY) **DILARANG DI-HARDCODE SEBAGAI OFFSET UTC STATIS**.
   - Inggris (GMT ↔ BST) dan Amerika Serikat (EST ↔ EDT) berganti Daylight Saving Time pada tanggal yang berbeda (terdapat jeda disinkronisasi 1–2 minggu pada Maret dan Oktober/November). Offset statis akan membuat scheduler meleset 1 jam dari pembukaan market aktual 2 kali setahun.
   - *Implementasi Wajib*: Scheduler menggunakan modul native Python `zoneinfo.ZoneInfo("Europe/London")` dan `zoneinfo.ZoneInfo("America/New_York")` untuk menghitung jam buka/tutup sesi secara dinamis setiap hari.
3. **Cakupan Jam Operasional (~12 Jam: 13:00 – 01:00 WIB)**:
   - Window operasional mencakup London Open (~14:00/15:00 WIB), overlap London-NY (jam likuiditas tertinggi), hingga pertengahan sesi NY (~01:00 WIB).
   - Ekor sesi NY sore (01:00 – 05:00 WIB) **sengaja dikecualikan secara sadar**: likuiditas emas menipis drastis pasca London close, pergerakan cenderung *choppy/drift*, dan mendekati jendela *daily break* Exness.
4. **Verifikasi Resmi Exness: Jam Daily Break & Rollover XAUUSD**:
   - *Sumber Resmi*: [Exness Help Center: Instrument trading hours (Article 4405235684498)](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours) dan [Exness Contract Specifications](https://www.exness.com/contract-specifications/).
   - *Kutipan Resmi*:
     > *"Exness's trading servers follow the UTC+0 timezone, so every time in MetaTrader and in Exness's schedules is shown in UTC+0... Many CFDs at Exness pause for a short daily break when the underlying market closes or rolls over, which is when the 'Trading is Closed' message appears... Swaps charged: 21:00 GMT+0 (summer) or 22:00 (winter)... Gold and silver: Weekdays with a daily break."*
   - *Jadwal Daily Trading Break XAUUSD Exness (Server Time UTC+0)*:
     | Periode Musim | Jam Trading Break Harian (UTC+0) | Konversi Jam WIB (UTC+7) | Waktu Force Close (15 Min Buffer) |
     | :--- | :---: | :---: | :---: |
     | **Summer (US DST: EDT)** | `20:59 – 22:01 UTC` | `03:59 – 05:01 WIB` | **20:44 UTC (03:44 WIB)** |
     | **Winter (US non-DST: EST)** | `21:59 – 23:01 UTC` | `04:59 – 06:01 WIB` | **21:44 UTC (04:44 WIB)** |
   - *Buffer Rule*: Seluruh posisi terbuka **WAJIB ditutup paksa tepat 15 menit sebelum daily break** sesuai status musim aktif (`20:44 UTC` saat US DST atau `21:44 UTC` saat US non-DST).

### 3.4 Aturan Eksekusi Spesifik Exness
Engine backtest wajib memodelkan perilaku kontrak Exness:
- **Rentang Bebas Slippage**: Selisih harga $\ge$ threshold spesifikasi kontrak akan dieksekusi pada harga pasar (slippage nyata). Ambang ini bersifat adaptif.
- **Stop Level EA**: Pemasangan pending order atau SL/TP wajib menghormati jarak minimum *Stop Level* akun Standard Exness.
- **Gap Rule**: Proteksi eksekusi tanpa slippage hanya berlaku untuk order yang terpasang $\ge 3$ jam setelah pembukaan pasar mingguan.

### 3.5 Deteksi Likuiditas & Graduated Sizing
Sistem menerapkan penanganan likuiditas bertahap (*graduated*), bukan sakelar biner on/off:
- **Layer 1 (Statis - Kalender Likuiditas Rendah)**:
  - Daily trading break & rollover Exness (Summer: 20:59–22:01 UTC / Winter: 21:59–23:01 UTC).
  - Jeda pergantian penutupan New York menuju pembukaan Asia.
  - Menjelang penutupan akhir pekan (Jumat malam).
  - Hari libur bank mayor (AS/Inggris).
- **Layer 2 (Dinamis - Tick Volume Proxy)**:
  - Melacak rata-rata frekuensi tick volume per M1 bar menggunakan EWMA.
  - Jika tick count turun drastis ($Z_{volume} < -2.0$), likuiditas dinilai menipis.
- **Aksi Graduated Sizing**:
  - Likuiditas Normal: Ukuran lot 100% (basis risk 0.5%).
  - Likuiditas Moderat/Menipis: Skala lot dipotong menjadi **50%** dari sizing normal.
  - Kondisi Ekstrem (Rollover / Libur Mayor): **Full Block** (0% sizing / status PAUSED).

---

## 4. Fase 2 — Analysis Engine

Sistem memisahkan mesin riset dan mesin inferensi live untuk menjamin kesinambungan operasional:

### 4.1 Mesin 1: Offline Research & Validation (Periodik)
```
Quant Feature Engineering (Rust) 
  → Strategy Library (4 Kategori) 
  → Regime-based Backtest 
  → Monte Carlo (1000 iterasi) & Walk-Forward Gate 
  → Validated Strategy Pool
```
- **Kategori Strategi XAUUSD**:
  1. *Volatility Breakout*: Ekspansi ATR dan penetrasi level kunci.
  2. *Positioning Contrarian*: Ekstremitas OANDA Order/Position Book ratio.
  3. *Intermarket/Correlation*: Sinyal US Real Yield (TIPS 10Y) dan DXY sebagai filter arah makro.
  4. *Mean-Reversion*: Volatility band adaptif khusus saat terkonfirmasi regime ranging.
- **Siklus Retraining**: Re-kalibrasi ringan tiap 14 hari, re-validasi penuh portofolio strategi tiap 30 hari.

### 4.2 Mesin 2: Live Inference (Per Siklus M15)
```
Live Feature Engineering (Rust) 
  → Regime Detection (Kronos ONNX Runtime) 
  → Strategy Matching 
  → Signal Candidate + Confidence Score
```
- Mesin 2 beroperasi independen menggunakan model dari *Validated Strategy Pool* terakhir saat Mesin 1 sedang melakukan kalkulasi ulang.

### 4.3 Multi-Timeframe Hierarchy
| Layer | Timeframe | Fungsi & Rationale |
| :--- | :---: | :--- |
| **Regime Detection** | **H4** | Konteks makro/teknikal besar, stabil dari noise. Input 512 candle H4 Kronos mencakup ~3.5–4 bulan kalender emas (pas dengan batas context length model). |
| **Strategy Setup** | **H1** | Identifikasi level breakout, mean-reversion band, dan sentimen OANDA Book (yang refresh 15–30 menit, ideal di H1). |
| **Execution & Entry** | **M15** | Presisi waktu entry, perhitungan basis ATR(14), dan batasan time-invalidation. |

---

## 5. Fase 3 — Risk & Execution

### 5.1 Risk Gate Watchdog (Go Daemon)
Proses pengawas independen memvalidasi pra-syarat entry sebelum order dikirim ke MT5:
- Saldo/Equity valid dan drawdown kumulatif $< 10\%$.
- Kerugian hari berjalan $< 2.0\%$.
- Tidak ada posisi aktif lain (`max_concurrent_positions = 1`).
- Kuota harian tersisa (`trades_today < 5`).
- State machine berstatus `NORMAL`.

### 5.2 Exit Logic 5 Lapis Lengkap (Wajib)
Semua posisi yang terbuka dilindungi oleh sistem proteksi berlapis berikut:

```
[Entry Order Terpasang] ──► Lapis 1: Fixed Server-Side SL & TP (Wajib terpasang di Exness)
          │
          ├──► Lapis 2: Dynamic Trailing Stop (Aktif setelah profit mencapai 1R, modify SL di server)
          ├──► Lapis 3: Partial Close / Scale-Out (Likuidasi 50% posisi pada target R pertama)
          ├──► Lapis 4: Time-Based Invalidation (Paksa tutup jika trade diam selama 8 candle M15 / 2 jam)
          └──► Lapis 5: Regime Invalidation (Tutup darurat jika regime H4 berubah berlawanan di tengah posisi)
                                      ▲
                                      │
[Hard Rule Operasional]: Force Close Seluruh Posisi 15 Menit Sebelum Daily Break Exness (20:44 UTC Summer / 21:44 UTC Winter)
```

### 5.3 Hard Requirement: Server-Side Attached SL/TP & Disaster Recovery
1. **Server-Side SL/TP Obligation**: Setiap order buy/sell yang dikirim ke Exness **WAJIB menyertakan parameter SL dan TP langsung ke broker** saat order placement. Dilarang mengandalkan logic client-side virtual SL. Jika laptop crash, koneksi putus, atau listrik padam, posisi tetap terlindungi 100% di server Exness.
2. **Server-Side Trailing Update**: Ketika logic trailing stop terpicu, sistem wajib mengirim perintah `OrderSend` / `order_modify` untuk memperbarui level SL langsung ke server broker.
3. **Jalur Intervensi Darurat Resmi**: Aplikasi **Exness Trade Mobile App** di smartphone ditetapkan sebagai instrumen Disaster Recovery resmi. Operator wajib login aktif pada akun real/demo di smartphone untuk intervensi manual darurat jika sistem laptop tidak merespons.

---

## 6. Fase 4 — Monitoring & Storage

### 6.1 Skema Database SQLite (3 Tabel Inti)
```sql
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    pair TEXT DEFAULT 'XAUUSD',
    data_tag TEXT NOT NULL, -- training, validation, forward_test, live_production
    state_machine_state TEXT NOT NULL,
    regime_detected TEXT NOT NULL,
    strategy_selected TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    hypothesis TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    lot_size REAL NOT NULL,
    exit_reason TEXT, -- sl_hit, tp_hit, trailing_hit, partial_close, time_invalidation, regime_invalidation, pre_rollover_force
    pnl REAL,
    spread_at_entry REAL NOT NULL,
    slippage_realized REAL,
    model_version_id TEXT NOT NULL
);

CREATE TABLE blocked_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    pair TEXT DEFAULT 'XAUUSD',
    reason_blocked TEXT NOT NULL, -- risk_gate_dd, circuit_breaker, state_machine_paused, low_liquidity
    confidence_at_time REAL,
    would_be_entry_price REAL
);

CREATE TABLE model_registry (
    model_version TEXT PRIMARY KEY,
    training_date DATETIME NOT NULL,
    data_range TEXT NOT NULL,
    hyperparameters TEXT NOT NULL,
    backtest_metrics TEXT NOT NULL, -- sharpe, sortino, max_dd, profit_factor
    forward_test_metrics TEXT,
    deployed_at DATETIME,
    status TEXT NOT NULL -- candidate, active, archived, rejected
);
```

### 6.2 Data Tagging & Retensi
- **Tagging**: Setiap baris data wajib memiliki atribut kategori: `training` | `validation` | `forward_test` | `live_production`.
- **Hot Tier**: Database SQLite menyimpan data operasional 60–90 hari terakhir.
- **Warm / Archive Tier**: Data yang lebih tua dari 90 hari di-dump ke format Apache Parquet terkompresi untuk arsip permanen dan bahan retraining model.

### 6.3 Telegram Control Panel & 2 Stream Sinyal
Sistem komunikasi Telegram memanfaatkan 2 stream pesan terpisah yang membaca langsung dari tabel SQLite `trades` dan `blocked_signals` tanpa membuat pipeline data baru:

#### 1. Stream 1: Dashboard Harian (Daily Session Report)
- **Frekuensi**: Dikirim sekali di akhir sesi operasional (~12 jam) sebelum market rollover.
- **Konten Data**:
  - Net P&L harian (dalam mata uang akun dan pips).
  - Jumlah trade & rasio win/loss.
  - Max Drawdown sesi berjalan.
  - Frekuensi proteksi aktif (jumlah kejadian engine berstatus `PAUSED` atau `PRE_NEWS_WATCH` — sebagai bukti nilai jual bahwa sistem proteksi aktif melindungi modal).
  - Rata-rata spread selama sesi perdagangan.
  - Tautan verifikasi pihak ketiga Myfxbook (sebagai *source of truth* independen).

#### 2. Stream 2: History Sinyal (Per-Event Alert)
- **Frekuensi**: Dikirim seketika saat sinyal valid terbentuk dan lolos seluruh lapis risk gate.
- **Format Teks Terstruktur (Wajib Menyertakan Chart OHLCV)**:
```
⚡ SIGNAL — XAUUSD {strategy_timeframe}
━━━━━━━━━━━━━━━━━━━━━━
📈 Direction: {LONG/SHORT}
🎯 Entry Zone: {entry_low} – {entry_high}
🛑 Stop Loss: {sl} (ATR-based)
🎯 TP1: {tp1} (1:{rr1} RR) — {hit_rate_1}% historical hit rate
⚡ TP2: {tp2} (1:{rr2} RR) — {hit_rate_2}% historical hit rate
📦 Lot Size: {lot_size}
🧠 Confidence: {confidence_score}%
🔍 Regime: {regime_detected} (H4)
━━━━━━━━━━━━━━━━━━━━━━
⏰ Valid max: {X} menit (expired jika belum entry)
━━━━━━━━━━━━━━━━━━━━━━
🧠 Strategi: {strategy_selected}
📊 Setup: {ringkasan singkat dari hypothesis terstruktur}
⚠️ Invalidasi: Regime H4 berubah arah / time invalidation {N} candle M15
━━━━━━━━━━━━━━━━━━━━━━
🏷 #{trade_id}
```

#### Larangan Ketat dalam Template Telegram (§9.5)
1. **Dilarang Menyiratkan Wording "Cloud AI Provider"**: Tidak boleh memuat kata seperti `OpenAI`, `ChatGPT`, `Claude`, `GPT-4`, `DeepSeek`, dsb. Seluruh sinyal diatribusikan secara transparan ke algoritma kuantitatif native (*Kronos ONNX / Quantitative Analysis Engine*).
2. **Dilarang Menampilkan Klaim Win Rate Mentah**: Dilarang mengklaim "Win Rate 85%" atau angka probabilitas tanpa dasar. Satu-satunya statistik keberhasilan adalah `{hit_rate}% historical hit rate` per level TP yang dihitung dari data backtest tervalidasi.
3. **Dilarang Menggunakan Terminologi SMC/ICT**: Dilarang menggunakan jargon retail spekulatif seperti `CHOCH`, `BOS`, `Order Block (OB)`, `Fair Value Gap (FVG)`, `Liquidity Sweep`, atau `Judas Swing`. Semua setup wajib dijelaskan dengan terminologi kuantitatif baku (contoh: *ATR expansion breakout*, *Mean-reversion retest upper 2.0-sigma band*, *OANDA positioning extreme skew*).

#### Interface Kontrol & Validasi
- Interaksi melalui inline button keyboard dengan validasi `user_id` integer admin.
- Perintah destruktif (*Emergency Stop / Force Close All*) mewajibkan konfirmasi dua langkah dengan time-to-live 15 detik.

---

## 7. Broker Bake-Off: Exness vs HFM

Untuk mengeliminasi asumsi reliabilitas broker, evaluasi komparatif dijalankan selama **2–4 minggu** (melewati siklus NFP/CPI):
1. Sinyal yang sama di-mirroring ke akun demo Standard Exness dan HFM secara bersamaan.
2. Metrik Penilaian:
   - Realized slippage saat berita rilis (bobot 50%).
   - Stabilitas spread normal di jam padat (bobot 25%).
   - Rejection / Requote rate (bobot 15%).
   - Total biaya transaksi (spread + komisi jika ada) (bobot 10%).
3. **Pemenang Tunggal**: Broker dengan performa terburuk akan dihapus total dari codebase demi efisiensi pemeliharaan.

---

## 8. Spesifikasi Deployment Awal

- **Hardware**: Laptop Lenovo LOQ 15IRX9 (Intel Core i7-13650HX, 16GB RAM, NVIDIA RTX 4050 6GB).
- **Sistem Operasi**: Windows 11 Home (dibutuhkan untuk binding library native `MetaTrader5`).
- **Jadwal Operasional**: ~12 jam per hari (13:00 – 01:00 WIB dinamis berbasis zona waktu market).
  *Cakupan Sesi*: Menjangkau London Open (~14:00/15:00 WIB), overlap London-NY (puncak likuiditas emas), hingga pertengahan sesi NY (~01:00 WIB). Ekor sesi NY (01:00 – 05:00 WIB) **sengaja dikecualikan** untuk menghindari likuiditas tipis pasca London close dan mendekati zona *daily break* Exness.
- **Prosedur Ketahanan Fisik**:
  - Windows Sleep, Hibernate, dan Automatic Update dimatikan selama jam operasional.
  - Koneksi jaringan via kabel LAN fisik (bukan WiFi utama).
  - Dilengkapi Mini-UPS untuk melindungi router dan laptop dari pemadaman listrik singkat.
- **Target Migrasi Masa Depan**: Windows Cloud VPS (Equinix / LD4 latency-optimized) ketika portofolio telah mandiri menghasilkan profit.

---

## 9. Starting Parameters YAML (v1.0 Verbatim)

Konfigurasi berikut merupakan parameter dasar resmi yang diimpor langsung oleh engine pada fase implementasi:

```yaml
# ====================================================================
# AI Trading System - XAUUSD Starting Configuration (v1.0)
# Sumber: ai-trading-master-reference.md §14 & architecture.md §3
# ====================================================================

broker:
  account_leverage: 200            # TODO: placeholder - update after verification from own Standard account
  contract_size: 100               # 100 oz per 1.0 lot XAUUSD

scheduling:
  timezone_storage: "UTC"
  session_regions:
    london: "Europe/London"
    new_york: "America/New_York"
  rollover_buffer_minutes: 15      # Force close 15 menit sebelum daily break Exness

risk:
  risk_per_trade_pct: 0.5
  max_daily_loss_pct: 2.0
  max_drawdown_killswitch_pct: 10.0
  max_concurrent_positions: 1
  max_trades_per_day: 5

exit:
  sl_method: "atr"
  sl_atr_multiplier: 1.5
  sl_atr_period: 14
  min_reward_risk_ratio: 2.0
  trailing_start_r: 1.0
  time_invalidation_bars: 8        # 8 candle M15 = 2 jam
  atr_timeframe: "M15"
  regime_timeframe: "H4"
  strategy_timeframe: "H1"
  partial_close_ratio: 0.5         # Ambil 50% posisi pada 1R

state_machine:
  z_threshold_pause: 3.0
  z_threshold_resume: 1.5
  k_stable_reads: 12
  m_stability_minutes: 5
  pre_news_watch_minutes: 10
  ewma_alpha: 0.08

liquidity:
  low_liquidity_tick_z_threshold: -2.0
  graduated_sizing_scale: 0.5      # Potong lot 50% saat likuiditas tipis
  rollover_buffer_minutes: 15      # Force close 15 menit sebelum daily break Exness

research:
  monte_carlo_iterations: 1000
  retrain_light_cadence_days: 14
  retrain_full_cadence_days: 30
```

---

## 10. CI/CD Pipeline & Branch Protection (§12.1)

Untuk menjamin keandalan sistem otomasi multi-agent (Orca worktrees) dan mencegah regresi pada kalkulasi finansial, sistem menerapkan pipeline GitHub Actions multi-runner:

### 10.1 Trigger & Matrix Runner
- **Trigger**: Setiap Pull Request (PR) dari worktree Orca (`feat/*`, `hotfix/*`) menuju branch `main`.
- **Pemisahan Runner**:
  - **Linux Runner (`ubuntu-latest`)**: Menjalankan static analysis, security scan, Rust compilation/test, Go test, dan suite test Python murni (tanpa ketergantungan MT5 terminal).
  - **Windows Runner (`windows-latest`)**: Khusus menjalankan suite pengujian integrasi yang memerlukan package native `MetaTrader5` Python dan environment Win32.

### 10.2 Tahapan Pengujian (Pipeline Jobs)
1. **Security & Secrets Scanning**:
   - Memindai codebase menggunakan `gitleaks` untuk mendeteksi token/password yang tidak sengaja tertulis.
2. **Linting & Type-Checking**:
   - Python: `uv run pyright` atau `mypy` (strict mode).
   - Rust: `cargo clippy -- -D warnings`.
   - Go: `go vet ./...`.
3. **Financial Golden Tests (Mandatory Gate - BLOCKING)**:
   - Pengujian deterministik terhadap fungsi sizing lot (0.5% risk cap, 0.01 lot floor).
   - Verifikasi formula matematis ATR, EWMA spread Z-score, dan kalkulasi PnL.
   - Kegagalan 1 assertion pada job ini otomatis memblokir merge PR.
4. **Rust & Go Core Test**:
   - `cargo test --all` (evaluasi kecepatan dan memory safety PyO3 module).
   - `go test -v ./...` (evaluasi keandalan watchdog).
5. **MT5 Integration Suite (Windows Runner)**:
   - `uv run pytest tests/test_execution_mt5.py -v` (menguji validasi parameter order dan server-side attached SL/TP).

### 10.3 Branch Protection & CODEOWNERS
Sesuai aturan keselamatan sistem, direktori dan file konfigurasi berikut berstatus **Safety-Critical**:
```
engine/risk_gate/                          @lead-architect
engine/state_machine/                      @lead-architect
engine/analysis_engine/rust/               @lead-architect
engine/execution/                          @lead-architect
engine/telegram_bot/                       @lead-architect
instruments/xauusd/config/parameters.yaml  @lead-architect
```
PR yang menyentuh direktori/file di atas **wajib mendapatkan review dan persetujuan manual (approval)** dari Lead Architect sebelum dapat di-merge ke branch `main`. Merge otomatis (auto-merge) dilarang keras untuk seluruh area tersebut.

### 10.4 Prosedur Konfigurasi Fisik GitHub Branch Protection (Membuat Check 'BLOCKING' Nyata)
Label `(BLOCKING)` pada job CI YAML hanya nama string. Agar GitHub **secara fisik menolak merge** saat test gagal, Solo Operator wajib mengaktifkan aturan berikut di repositori GitHub (`Settings` -> `Branches` -> `Branch protection rules` untuk branch `main`):

1. **Require status checks to pass before merging**: Centang aktif.
2. **Require branches to be up to date before merging**: Centang aktif (mencegah merge branch usang yang belum diuji terhadap `main` terbaru).
3. **Pilih Status Check Wajib (Required Status Checks)**:
   - `Financial Golden Tests (Deterministic)` (Job 3 — blokir mutlak jika sizing/math salah).
   - `Lint & Typecheck` (Job 2).
   - `Secrets Scan (Gitleaks)` (Job 1).
4. **Require review from Code Owners**: Centang aktif (memaksa GitHub meminta persetujuan manual untuk path yang terdaftar di `.github/CODEOWNERS`).
5. **Do not allow bypassing the above settings**: Centang aktif (bahkan admin repositori tidak dapat mem-bypass proteksi ini tanpa sengaja).
