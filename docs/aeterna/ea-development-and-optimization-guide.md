# Panduan Teknis Pengembangan & Optimasi Expert Advisor (EA) MQL5
## AETERNA Quant Institutional Engineering Guide (MQL5 & Multi-Agent Architecture)

**Dokumen**: `docs/aeterna/ea-development-and-optimization-guide.md`  
**Target Pembaca**: AI Agents (`aeterna-*`), Principal Engineers, dan Human Operators  
**Standar Rekayasa**: *Zero-LLM Execution Core*, *0.00% Risk Invariant Tolerance*, *Strict Evidence-Backed Optimization*  

---

## 1. Pendahuluan & Prinsip Utama

Dokumen ini adalah **Standar Operasional Prosedur (SOP) Resmi dan Panduan Teknis** untuk pengembangan, pengujian, audit, dan optimasi Expert Advisor (EA) MQL5 di lingkungan AETERNA Quant.

### Prinsip Mutlak:
1. **Pemisahan Jalur Eksekusi & Laboratorium**:
   - **MQL5 EA** (`ea/AeternaEA/`) adalah **mesin tunggal eksekusi live & Strategy Tester**. Mengapa MQL5? Karena MetaTrader 5 Strategy Tester dengan data tick riil (*Every tick based on real ticks*) broker Exness adalah satu-satunya validator yang memodelkan spread dinamis, slippage, dan aturan penolakan broker secara 100% nyata.
   - **Python / Rust PyO3** adalah **laboratorium riset**: penarikan data historis makro, analisis time-series Kronos, dan simulasi permutasi Monte Carlo.
2. **Kepatuhan Invarian Risiko Tanpa Toleransi (0.00% Tolerance)**:
   - Risiko per transaksi: Tepat **`0.5%`** dari ekuitas akun saat entry.
   - Batas kerugian harian: Maksimal **`2.0%`** dari ekuitas pembukaan hari.
   - Hard Killswitch penarikan modal: Maksimal **`10.0%`** dari puncak ekuitas (*Peak Equity*).
   - Maksimal posisi terbuka serentak: Tepat **`1 posisi`** (Zero hedging, zero averaging, zero martingale).
   - Maksimal transaksi per hari: Tepat **`5 trade`**.
   - Rasio Reward-to-Risk terpasang: Minimal **$\ge 2.0$**.
3. **Protokol Perlindungan Baseline Beku (ADR-009)**:
   - File di dalam `ea/AeternaEA/` berstatus **GOLDEN BASELINE (FROZEN)**.
   - Dilarang keras mengedit file baseline secara langsung. Setiap optimasi atau eksperimen baru **WAJIB dibuatkan klon di `ea/experiments/<nama_eksperimen>/`**.

---

## 2. Arsitektur Modular MQL5 (`ea/AeternaEA/`)

Struktur kode EA dirancang dengan modularitas berorientasi objek C++ tingkat institusi:

```text
ea/AeternaEA/
├── AeternaEA.mq5                  # Entry point (OnInit, OnTick, OnDeinit, Trading Loop)
├── README.md                      # Dokumentasi baseline v1.0 & deklarasi pembekuan
├── Presets/
│   ├── DayTrading_M15.set         # Preset resmi M15 (Donchian 20 + Pullback T2)
│   └── SessionMomentum_M5.set     # Preset M5 (Session Momentum Burst)
└── Include/
    ├── Invariants.mqh             # Single Source of Truth konstanta & parameter risiko
    ├── RiskManager.mqh            # Dynamic Fractional Sizing, Scale-Before-Floor, Drawdown Guard
    ├── StateMachine.mqh           # EWMA Spread Baseline & Real-Time Z-Score Gate
    ├── CalendarFilter.mqh         # Jadwal Blackout Berita Makro (T-10m Pre-News Guard)
    ├── ExitManager.mqh            # Manajemen Exit 5-Lapis, True Ratchet Trailing, Partial Close
    ├── RegimeDetector.mqh         # Klasifikasi Rezim H4 (ADX14 + EMA20/50)
    ├── StrategyBreakout.mqh       # Strategi 1: Breakout Retest + EMA Pullback Turnaround
    ├── StrategyMomentum.mqh       # Strategi 2: M5 London/NY Session Momentum Burst
    └── StrategyAsianRange.mqh     # Strategi 3: Post-Rollover Asian Range Scalper
```

### Tanggung Jawab Modul Header (`Include/*.mqh`):

| File Modul | Tanggung Jawab Tunggal | Fungsi Kunci |
| :--- | :--- | :--- |
| **`Invariants.mqh`** | Wadah konstanta absolut finansial dan parameter mikrostruktur XAUUSD. | Definisi `#define RISK_PER_TRADE_PCT`, `MAX_DRAWDOWN_KILLSWITCH`, `MIN_SL_DISTANCE_DOLLARS`. |
| **`RiskManager.mqh`** | Pengawas gerbang pra-order, kalkulasi ukuran lot, dan pelacak ekuitas harian/puncak. | `CanOpenNewPosition()`, `CalculateLotSize()`, `CheckDayRollover()`. |
| **`StateMachine.mqh`** | Filter volatilitas berbasis pelebaran spread EWMA ($\alpha=0.08$) dan Z-Score ($Z \ge 3.0$). | `Update(spread, time, in_news)`, `GetState()`, `GetZScore()`. |
| **`CalendarFilter.mqh`** | Pencegah order di jendela berita berdampak tinggi ($T-10$m s/d $T+15$m). | `IsInPreNewsWindow()`, `IsInNewsBlackout()`. |
| **`ExitManager.mqh`** | Eksekusi Lapis 2 Trailing Ratchet, Lapis 3 Partial Close, Lapis 4 Time Invalidation, Lapis 5 Force Close. | `MonitorActivePositions()`, `CanModifyPosition()`, `CloseAllPositions()`. |
| **`RegimeDetector.mqh`**| Filter makro H4 penentu arah transaksi (Trending Bullish, Bearish, Ranging, Ambiguous). | `ClassifyCurrentRegime()`. |
| **`StrategyBreakout.mqh`**| Evaluasi setup M15: Penembusan Donchian 20 (T1) & Pantulan EMA 20/50 Pullback (T2). | `Evaluate(time, regime, sl_pts, tp_pts, reason)`. |
| **`StrategyMomentum.mqh`**| Evaluasi momentum lonjakan volume tick M5 saat sesi overlap London/NY. | `Evaluate(time, regime, sl_pts, tp_pts, reason)`. |
| **`StrategyAsianRange.mqh`**| Evaluasi pantulan Bollinger Band M15/M5 pasca-rollover malam hari (01:15–03:45). | `Evaluate(time, spread, regime, sl_pts, tp_pts, reason)`. |

---

## 3. Protokol Alur Kerja Optimasi Multi-Agent (Siapa & Kapan Dipanggil)

Ketika hasil backtest EA belum mencapai target (misal: Net Profit tertahan, Profit Factor $< 1.5$, atau Max Drawdown mendekati $10\%$), operator **DILARANG mengutak-atik kode secara acak**. 

Panggil sub-agent spesialis sesuai urutan siklus 7 langkah berikut:

```
[1. aeterna-research]    ──► Bedah mikrostruktur, MFE empiris, anomali sesi & literatur SSRN
         │
         ▼
[2. aeterna-strategy]    ──► Rumuskan geometri SL/TP, trailing ratchet, dan konfluensi entry
         │
         ▼
[3. aeterna-risk]        ──► Hitung matematika lot compounding, DD throttling & circuit breaker
         │
         ▼
[4. aeterna-execution]   ──► Validasi rate limit broker (deadband/cooldown) & filing IOC Exness
         │
         ▼
[5. aeterna-backtest]    ──► Sintesis aljabar payoff, uji Monte Carlo 1,000 run & eksekusi batch
         │
         ▼
[6. aeterna-verifier]    ──► Audit kepatuhan invariant, clean code MQL5, dan verifikasi log
         │
         ▼
[7. aeterna-lead]        ──► Evaluasi keputusan akhir, persetujuan ADR & pembaruan handoff
```

### Rincian Peran & Prompt Delegasi per Sub-Agent:

#### Langkah 1: `aeterna-research` (Mikrostruktur & Bukti Empiris)
*   **Tugas**: Menganalisis sifat alami instrumen (misal: XAUUSD di sesi London/NY), batas Maximum Favorable Excursion (MFE), rata-rata kedalaman retrace, dan mencari jurnal/paper kuantitatif (SSRN/arXiv 2020–2026).
*   **Pertanyaan Kunci**: *"Berapa MFE normal 1 gelombang impuls di sesi ini? Apakah trailing stop berjarak X poin mencekik trade pemenang?"*
*   **Keluaran Wajib**: Dokumen `.handoff/research/BRIEF-<topik>.md` bertaksonomi `[EVIDENCE]`, `[HYPOTHESIS]`, dan `[CONTRADICTED]`.

#### Langkah 2: `aeterna-strategy` (Geometri Strategi & Rule Formalism)
*   **Tugas**: Mengubah temuan riset menjadi formula matematis deterministik di `StrategyBreakout.mqh` dan `ExitManager.mqh`.
*   **Pertanyaan Kunci**: *"Berapa target Take Profit nominal (2.5R vs 3.0R)? Di level MFE berapa SL digeser ke Break-Even? Bagaimana menyaring false breakout?"*
*   **Keluaran Wajib**: Formula MQL5 eksplisit, tabel perbandingan realized R, dan penetapan role (`ENTRY_ENGINE` vs `FILTER`).

#### Langkah 3: `aeterna-risk` (Manajemen Risiko & Matematika Compounding)
*   **Tugas**: Mengaudit fungsi `CalculateLotSize()`, membuktikan threshold ekuitas untuk kenaikan lot, dan merancang benteng anti-drawdown bertingkat di `RiskManager.mqh`.
*   **Pertanyaan Kunci**: *"Mengapa lot size terkunci di 0.02 lot? Pada ekuitas berapa lot naik ke 0.03 lot dengan SL $3.20? Bagaimana memastikan Max DD tidak pernah menyentuh 10.0%?"*
*   **Keluaran Wajib**: Pembuktian aljabar scale-before-floor, ambang de-risking dinamis (misal: potong 50% risk saat DD $\ge 5\%$), dan pembuktian Risk of Ruin = 0.000%.

#### Langkah 4: `aeterna-execution` (Realitas Broker & Anti-Flooding)
*   **Tugas**: Menjamin EA mematuhi spesifikasi teknis trade server broker Exness Standard.
*   **Pertanyaan Kunci**: *"Apakah PositionModify memicu error 10018 (Rate Limit)? Apakah filling mode ORDER_FILLING_IOC terpasang? Apakah ada risiko naked position jika broker menolak order?"*
*   **Keluaran Wajib**: Desain Dual-Constraint Rate Limiter (Spatial deadband $\ge 30$ pts + Temporal cooldown $\ge 5$ detik) dan Post-Execution Verification Gate.

#### Langkah 5: `aeterna-backtest` (Sintesis Payoff & Eksekusi Batch)
*   **Tugas**: Menghubungkan Win Rate dan Payoff Ratio ($E_R = W \cdot B - (1 - W)$), menjalankan simulasi permutasi Monte Carlo 1,000 iterasi, dan menyusun file konfigurasi `.ini` untuk Strategy Tester.
*   **Pertanyaan Kunci**: *"Berapa Average Win yang dibutuhkan agar Net Profit mencapai $600+? Berapa p95/p99 Max Drawdown dari 1,000 run acak?"*
*   **Keluaran Wajib**: Tabel sensitivitas payoff, matriks perbandingan skenario, dan otomatisasi eksekusi via `run_batch_backtest.ps1`.

#### Langkah 6: `aeterna-verifier` (Audit Independen)
*   **Tugas**: Memverifikasi bahwa tidak ada kode rahasia/hardcoded magic numbers, memastikan kompilasi menghasilkan 0 errors / 0 warnings, dan mencocokkan log MT5 dengan klaim performa.

#### Langkah 7: `aeterna-lead` (Direktur Kuantitatif & Handoff)
*   **Tugas**: Mengevaluasi apakah hasil akhir memenuhi kriteria kelulusan (Gate), menerbitkan nomor ADR baru, dan memperbarui berkas handoff (`.handoff/latest.md`).

---

## 4. Sistem Otomatisasi Strategy Tester Batch Runner

Untuk melakukan backtest ribuan trade secara cepat di satu laptop tanpa menyentuh mouse, gunakan skrip resmi:
📂 **`ea/Scripts/run_batch_backtest.ps1`**

### Perintah CLI Resmi:

```powershell
# 1. Menjalankan pengujian DayTrading M15 pada rentang penuh 2022 - 2024 (Deposit $4,000)
powershell -ExecutionPolicy Bypass -File ea\Scripts\run_batch_backtest.ps1 `
    -Expert "AeternaEA\AeternaEA.ex5" `
    -Profile DayTrading `
    -FromDate "2022.01.01" `
    -ToDate "2024.11.01" `
    -Deposit 4000 `
    -Model 1

# 2. Menjalankan pengujian versi eksperimen di folder clone (AeternaEA_v1_1_Opt)
powershell -ExecutionPolicy Bypass -File ea\Scripts\run_batch_backtest.ps1 `
    -Expert "AeternaEA_v1_1_Opt\AeternaEA.ex5" `
    -Profile DayTrading `
    -FromDate "2020.01.01" `
    -ToDate "2026.11.13" `
    -Deposit 2000 `
    -Model 1
```

### Parameter Skrip:
*   `-Expert`: Lokasi biner `.ex5` di dalam folder `MQL5\Experts\` (contoh: `"AeternaEA\AeternaEA.ex5"`).
*   `-Profile`: Pilihan strategi: `DayTrading`, `SessionMomentum`, `AsianRange`, atau `All`.
*   `-FromDate` & `-ToDate`: Format tanggal `YYYY.MM.DD`.
*   `-Deposit`: Modal awal simulasi dalam USD (contoh: `2000`, `3000`, `4000`).
*   `-Model`: Model simulasi: `1` (M1 OHLC — cepat & akurat untuk evaluasi M15), `0` (Every tick), `4` (Real ticks Exness).

### Alur Kerja Otomatis Skrip:
1. Menghentikan instance terminal MT5 yang masih menggantung di latar belakang.
2. Membaca kredensial login akun Exness Standard dari file `.env`.
3. Menghasilkan file konfigurasi `.ini` deterministik di `ea/Config/`.
4. Menjalankan terminal MT5 secara *headless* (tanpa GUI) via CLI `/config:tester.ini`.
5. Mengarsipkan laporan interaktif HTML, grafik PNG kurva ekuitas, histogram PnL, dan sebaran MFE/MAE ke `ea/Reports/<ScenarioName>/`.
6. Mengekstrak metrik kunci secara instan ke `ea/Reports/batch_summary.csv`.

---

## 5. Panduan Diagnosis & Solusi Masalah Performa (Troubleshooting Matrix)

Gunakan matriks ini saat hasil backtest menunjukkan gejala anomali:

| Gejala Masalah | Penyebab Mekanis (Root Cause) | Solusi Rekayasa yang Terbukti |
| :--- | :--- | :--- |
| **Net Profit tertahan kecil padahal Win Rate $>55\%$** | **Payoff Terbalik ($B < 1.0$)**: Average Win lebih kecil dari Average Loss akibat trailing stop memotong posisi di $+0.5\text{R}$ terlalu dini. | 1. Naikkan target TP nominal ke $2.5\text{R} - 3.0\text{R}$.<br>2. Undur aktivasi trailing ratchet ke $+1.8\text{R} - +2.0\text{R}$ dengan buffer $1.0\text{R}$ di belakang MFE.<br>3. Pertahankan Break-Even di $+1.5\text{R}$ (+0.1R buffer). |
| **Lot size tidak pernah membesar (Compounding Mati)** | **Kuantisasi `MathFloor`**: Jarak Stop Loss terlalu lebar ($>\$4.50$) sehingga kenaikan ekuitas tidak pernah menembus step $0.01$ lot broker. | 1. Gunakan setup pullback presisi dengan SL $\$3.00 - \$3.50$. Pada SL $\$3.20$, lot $0.03$ langsung aktif di modal $\$2,000$.<br>2. Atau naikkan basis modal pengujian ke tier yang sesuai ($3,000$ atau $4,000$ USD). |
| **Drawdown melonjak mendekati 10.0% Killswitch** | **Loss Clustering saat Sesi Choppy**: Terjadi deret kekalahan 8–10 trade berurutan saat pasar berkonsolidasi tanpa arah. | 1. Terapkan *Intraday Cooling-Off*: Kunci trading 4 jam jika terjadi 2 loss berturut-turut di hari yang sama.<br>2. Terapkan *Dynamic Throttling*: Potong alokasi risiko menjadi $0.25\%$ saat drawdown akun mencapai $5.0\%$. |
| **Jumlah trade terlalu sedikit ($<100$ trade dalam 2 tahun)** | **Filter Terlalu Kaku**: Hanya menunggu breakout Donchian murni pada jendela waktu yang terlalu sempit. | 1. Aktifkan mesin ganda: Donchian Retest (T1) + EMA 20/50 Pullback Turnaround (T2).<br>2. Perluas jendela ke koridor aktif London & New York (07:00 – 17:00 UTC). |
| **Terminal log penuh pesan Error 10018 / 10031** | **Tick-by-Tick Flooding**: `PositionModify` dipanggil setiap kali harga bergerak 1–2 poin tanpa batas waktu. | Terapkan Dual-Constraint Rate Limiter di `ExitManager.mqh`: Deadband pergeseran minimal 30 points ($0.30) DAN cooldown jeda minimal 5.0 detik. |
| **Hasil backtest tampak fantastis di Asia tapi hancur di live** | **Spread Rollover Neglect**: Backtest tidak memodelkan lonjakan spread malam Exness (150–350 points saat rollover 23:50–00:25). | Tolak strategi scalping malam hari. Terapkan *Hard Rollover Rule*: Tutup paksa seluruh posisi 15 menit sebelum daily break Exness (20:44 UTC). |

---

## 6. Protokol Kloning & Eksperimen Aman (Enforcing ADR-009)

Untuk menjaga agar kode baseline tetap murni dan terlindungi:

### Prosedur Membuat Eksperimen Baru:
1. **Salin Folder Baseline ke Folder Eksperimen**:
   ```powershell
   $src = "ea\AeternaEA_v1_Baseline"
   $dst = "ea\experiments\AeternaEA_v1_2_Test"
   Copy-Item -Path $src -Destination $dst -Recurse -Force
   ```
2. **Buat Junction ke Terminal MT5**:
   ```powershell
   $mt5Experts = "C:\Users\Lenovo\AppData\Roaming\MetaQuotes\Terminal\67E58C3BE56BAC51882B5F36F45E170E\MQL5\Experts"
   $targetLink = Join-Path $mt5Experts "AeternaEA_v1_2_Test"
   cmd /c mklink /J "$targetLink" (Resolve-Path $dst).Path
   ```
3. **Lakukan Modifikasi di Dalam Folder Eksperimen Tersebut**.
4. **Kompilasi via MetaEditor**:
   ```powershell
   $metaeditor = "C:\Program Files\MetaTrader 5\metaeditor64.exe"
   & $metaeditor /compile:"ea\experiments\AeternaEA_v1_2_Test\AeternaEA.mq5" /log:"ea\experiments\AeternaEA_v1_2_Test\compile.log"
   ```
5. **Jalankan Batch Test & Bandingkan dengan Baseline**:
   Gunakan skrip `run_batch_backtest.ps1` dengan parameter `-Expert "AeternaEA_v1_2_Test\AeternaEA.ex5"`.

### Syarat Kelulusan Promosi Eksperimen Menjadi Baseline Baru:
Versi eksperimen baru **HANYA BOLEH DIPERTIMBANGKAN MENGGANTIKAN BASELINE** jika pada periode pengujian 2020–2026 membuktikan:
- Net Profit melampaui baseline ($> +\$436.67$ USD pada modal $2,000, atau $> +\$983.07$ USD pada modal $4,000$).
- Total Transaksi representatif: $\ge 400$ trades.
- Win Rate stabil: $\ge 55.0\%$.
- Profit Factor: $\ge 1.25$.
- Max Drawdown: Terbukti tetap $< 8.0\% – 10.0\%$.

---

## 7. Checklist Pra-Forward Test & Live Staging

Sebelum EA dipasang pada akun demo live yang berjalan 24 jam:

- [ ] **Kompilasi Bersih**: Binary `.ex5` dihasilkan dengan 0 errors dan 0 warnings pada build MetaTrader 5 terbaru.
- [ ] **Koneksi Akun Broker**: Terverifikasi terhubung ke server demo Exness Standard (`Exness-MT5<SERVER>`) dengan simbol `XAUUSDm`.
- [ ] **Verifikasi Server-Side SL/TP**: Jalankan dry-run order pertama, buka tab *Trade* di MT5, pastikan kolom *S / L* dan *T / P* terisi angka fisik (bukan 0.000).
- [ ] **State Machine Active**: Log terminal mencetak status `[STATE] Transitioned to NORMAL / PAUSED` saat terjadi anomali spread.
- [ ] **Disaster Recovery Siap**: Operator telah menginstal aplikasi *Exness Trade Mobile App* di ponsel cerdas untuk intervensi darurat jika laptop mengalami gangguan daya atau internet.
- [ ] **Audit Handoff Selesai**: Seluruh parameter dan hash commit git tercatat di `.handoff/latest.md`.
