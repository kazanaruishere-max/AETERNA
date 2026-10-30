# AI Trading Startup — Master Reference (Final)

Dokumen ini menggantikan `ai-trading-project-reference.md` dan `ai-trading-dev-kickoff-brief.md` — satu sumber kebenaran lengkap dari seluruh sesi brainstorming. Fokus saat ini: **all-in XAUUSD**, uji ke komunitas kecil/private dulu, baru expand kalau sudah terbukti stabil.

---

## 0. Status Kematangan Planning (jujur, bukan basa-basi)

**Matang untuk mulai CODING. Belum matang untuk mulai FORWARD TEST/LIVE dengan uang real.** Enam hal berikut wajib dijawab sebelum Milestone 5 (lihat §14):

1. **Ukuran modal/capital belum ditentukan** — parameter risk berbasis persentase (0.5% per trade) bisa jadi teoretis doang kalau modal terlalu kecil buat unit lot minimum XAUUSD (0.01 lot).
2. ~~Timeframe eksekusi belum resmi diputuskan~~ — **SELESAI**, lihat §7.5: regime H4, strategi H1, entry M15.
3. **Tidak ada prosedur disaster recovery** untuk laptop-as-server — apa langkah konkret kalau laptop crash saat ada posisi terbuka (manual intervensi via app Exness di HP?).
4. **Tidak ada "kill criteria" level proyek** — aturan kapan pendekatan dianggap perlu dirombak total (bukan cuma tweak parameter) setelah periode forward test tertentu, untuk hindari sunk-cost fallacy.
5. **Entitlement OANDA Order/Position Book API belum dicek** — apakah tier akun otomatis dapat akses.
6. **Angka pasti Exness (rentang bebas slippage, stop level EA) masih estimasi \~300**, belum ditarik langsung dari Spesifikasi Kontrak akun.

---

## 1. Latar Belakang & Pelajaran Penting

- Sistem lama: backtest 112k pips (data 2 tahun), forward test 32k pips (\~3 bulan, demo, OANDA+Exness).
- Insiden kritis: drawdown -41k pips dari peak 46k (≈51% dari peak global 80k), dipicu news tanpa filter. Setelah fix, equity pulih ke 80k — tapi fix dari satu insiden **belum divalidasi ulang** lewat siklus news baru.
- Belum pernah dilakukan di sistem lama: walk-forward analysis, Monte Carlo, multi-broker robustness test — jadi prasyarat wajib di sistem baru.
- **Sistem baru ini = track record kembali ke nol.** Klaim performa lama tidak relevan untuk arsitektur yang benar-benar baru ini.

## 2. Roadmap & Fokus

- All-in XAUUSD dulu. Expand ke pair lain (EURUSD, GBPUSD, USDJPY, USDCHF) atau aset lain hanya setelah XAUUSD terbukti stabil dan komunitas mulai ramai.
- Model bisnis: signal gratis → bangun trust/track record → EA/signal premium → porto MQL5 kalau sudah ada modal.

## 3. Legal & Compliance

- Berjualan sinyal/EA forex di Indonesia bersinggungan dengan Bappebti. EA diframe sebagai "software tool".
- Disclaimer "bukan ajakan investasi" mengurangi risiko tapi **bukan legal shield penuh** sekali mulai ada transaksi uang. Konsultasi hukum fintech wajib sebelum monetisasi real (belum dilakukan — masih action item).

## 4. Arsitektur Sistem — 4 Fase

```
Ingestion & Filtering → Analysis Engine → Risk & Execution → Monitoring & Feedback
                                                                      │
                                                    (retraining periodik, loop balik ke Analysis Engine)
```

Prinsip: modular, fail-safe default (error → jangan entry), semua keputusan di-log termasuk yang di-block, config sebagai data.

## 5. Tech Stack

| Layer | Tech | Catatan |
| --- | --- | --- |
| Trigger & scheduling | Go |  |
| Data ingestion | Python |  |
| Feature engineering & backtest | Rust (PyO3 extension) | Profiling dulu sebelum rewrite; jangan asumsi bottleneck |
| Model training | Python + PyTorch | Fine-tune Kronos |
| Model inference produksi | ONNX Runtime | Ringan di CPU |
| Risk gate watchdog | Go | Proses independen |
| Eksekusi & distribusi | Go/Python | `MetaTrader5` Python package (Exness), Telegram bot |
| Monitoring | SQLite → Postgres/TimescaleDB |  |
| Komunikasi antar service | Shared DB + polling (MVP) | Kafka tidak perlu — bukan HFT |

## 6. Fase 1 — Ingestion & Filtering

### 6.1 Dual Broker

- **OANDA = scanning only.** Tidak pernah eksekusi. v20 REST/streaming API langsung (bukan lewat MT5). Order/Position Book **bukan DOM pasar sungguhan** (forex OTC, tidak ada order book universal) — cuma posisi klien OANDA sendiri, refresh 15–30 menit. Cocok untuk sentiment/regime feature jangka menengah, **tidak** cocok untuk trigger real-time detik-ke-detik.
- **Exness = eksekusi, forward test, akun real.** Via `MetaTrader5` Python package resmi.
- Bridge: tidak perlu ZeroMQ sekarang (semua di satu laptop Windows). Baru relevan kalau infra dipecah multi-mesin.

### 6.2 News & Volatility State Machine

```
NORMAL → (news terjadwal masuk window) → PRE_NEWS_WATCH
PRE_NEWS_WATCH → (waktu rilis / Z>threshold) → PAUSED
PAUSED → (Z<threshold_resume, K bacaan berturut-turut) → RECOVERY_CHECK
RECOVERY_CHECK → (stabil M menit) → NORMAL
RECOVERY_CHECK → (Z naik lagi) → PAUSED
```

- Keputusan final: **tidak memaksa entry saat news.** Engine istirahat (PAUSED), jalan lagi setelah stabil.
- Matematika: EWMA baseline spread (`S_baseline(t) = α·S(t)+(1-α)·S_baseline(t-1)`), dipisah per sesi trading; `Z(t) = (S(t)-S_baseline(t))/σ_S(t)`; hysteresis antara threshold masuk vs resume.
- Dua layer: blackout kalender deterministik (terjadwal) + deteksi Z-score real-time (breaking news tak terjadwal).

### 6.3 Aturan Eksekusi Exness (dari dokumentasi resmi)

- Slippage rule: selisih ≥ rentang bebas slippage → eksekusi di harga pasar (tanpa proteksi). Rentang ini **adaptif**, dipengaruhi kondisi market DAN aktivitas trading akun sendiri.
- Stop level mungkin **berbeda untuk EA** — cek manual di Spesifikasi Kontrak, jangan asumsi dari tabel umum.
- Gap rule: jaminan nyaris-tanpa-slippage hanya untuk order ≥3 jam setelah market dibuka.
- Backtest engine **wajib** simulasikan mekanisme ini eksplisit, bukan asumsi entry ideal.

### 6.4 Likuiditas

- Spread normal ≠ likuiditas tebal — proxy terbaik untuk forex OTC adalah **tick volume/frekuensi tick**, bukan depth resmi (yang tidak ada di forex).
- Low-liquidity calendar (Layer 1, statis): rollover harian, gap NY close→Asia open, akhir pekan, libur mayor.
- Deteksi real-time (Layer 2): EWMA+Z-score pada tick count, sama metodenya dengan spread detection.
- Treatment **graduated, bukan biner**: likuiditas menipis → scale down lot size; kondisi ekstrem (libur mayor) → full block.

## 7. Fase 2 — Analysis Engine (Dua Mesin Terpisah)

### 7.1 Mesin 1: Offline Research & Validation (periodik)

```
Quant Feature Engineering (Rust) → Strategy Library → Regime-based Backtest → Monte Carlo/Walk-forward Gate → Validated Strategy Pool
```

- Quant features: order flow/positioning (OANDA book), intermarket correlation (DXY, US real yield), time series stats (GARCH, autocorrelation).
- **4 kategori strategi XAUUSD**: volatility breakout (ATR expansion), positioning-based contrarian (OANDA order book), intermarket/correlation-driven (DXY, US10Y real yield), mean-reversion di regime ranging (volatility band adaptif).
- Monte Carlo = gate validasi di AKHIR seleksi, bukan generator strategi.
- Cadence: re-kalibrasi ringan tiap 2 minggu, re-validasi penuh bulanan.

### 7.2 Mesin 2: Live Inference (per siklus)

```
Live Feature Engineering (Rust) → Regime Detection (Kronos fine-tuned, ONNX) → Strategy Matching → Signal Output (kandidat trade + confidence score)
```

- Mesin 2 tetap jalan pakai pool lama saat Mesin 1 re-run — tidak ada downtime.
- Regime dua lapis: teknikal (Kronos) + makro (§7.4).

### 7.3 Model: Kronos

- Foundation model K-line, PyTorch, MIT license, AAAI 2026. Varian mini/small/base (4.1M–102.3M param).
- Caveat: context length cuma 512 (**belum dicek** cukup/tidak untuk lookback strategi — action item). Pretraining minim data forex/OTC → fine-tuning harus intensif.
- Export ke ONNX Runtime untuk produksi.

### 7.4 Macro Economics per Pair (framework riset, fokus XAUUSD dulu)

| Pair | Driver utama |
| --- | --- |
| XAUUSD | US real yield (TIPS), DXY, risk sentiment, pembelian emas bank sentral EM |
| EURUSD | Selisih ECB vs Fed, data makro EZ vs US |
| GBPUSD | Kebijakan BOE, data/politik UK |
| USDJPY | Selisih BOJ vs Fed (carry trade, dinamika bergeser sejak BOJ keluar suku bunga negatif), risk sentiment |
| USDCHF | Kebijakan SNB, safe-haven (sering bareng XAUUSD & JPY) |

Metodologi: kumpulkan kandidat variabel → uji korelasi/Granger causality → validasi per rezim waktu (hubungan bisa berubah) → variabel lolos masuk feature per pair (tidak digeneralisir).

### 7.5 Kerangka Multi-Timeframe (terkonfirmasi)

| Layer | Timeframe | Fungsi |
| --- | --- | --- |
| Regime detection (Kronos) | H4 | Konteks besar, stabil, tidak gampang flip-flop. 512 candle H4 ≈ 3.5–4 bulan lookback (gold \~5.5 hari/minggu × 6 candle/hari) — cukup untuk pergeseran regime menengah, sekaligus pas dengan keterbatasan context length Kronos |
| Strategy/setup evaluation | H1 | Breakout level, band mean-reversion, sinyal positioning (OANDA Order/Position Book, yang refresh 15–30 menit, secara natural lebih cocok di sini — di M15 datanya akan terlihat stale beberapa candle berturut-turut) |
| Entry/eksekusi | M15 | Timing presisi masuk, basis ATR(14) dan time-invalidation (8 candle = 2 jam) |

Ini starting point yang perlu divalidasi lewat backtest (Milestone 3) — bukan final, bisa direvisi per strategi kalau hasil data menunjukkan kombinasi lain lebih pas.

## 8. Fase 3 — Risk & Execution

### 8.1 Risk Gate Watchdog

- Proses independen, cek equity/drawdown tiap interval pendek. Approve entry hanya jika: sizing OK, SL/TP terpasang, circuit breaker belum kena, **DAN** state machine = NORMAL.

### 8.2 Exit Logic — Wajib 4+1 Lapis

1. Fixed SL/TP (baseline)
2. Trailing stop (setelah profit 1R)
3. Partial close/scale-out
4. Time-based invalidation (N candle)
5. **Regime invalidation** — tutup lebih awal kalau regime berubah di tengah posisi, independen dari SL/TP/waktu.

### 8.3 Gaya Trading: Intraday

- Bukan scalping (terlalu rentan ke mekanisme slippage Exness yang sudah dibedah di §6.3) dan bukan swing (risiko gap weekend, swap belum dirancang).
- Posisi **wajib ditutup sebelum rollover harian** — perlu aturan eksekusi eksplisit (force close sebelum jam rollover).
- Strategi intermarket/correlation-driven berpotensi perlu diposisikan sebagai filter regime (bukan trigger entry langsung) karena hubungan makro biasanya main out di timeframe lebih panjang dari intraday.

### 8.4 Eksekusi & Distribusi

- Exness via `MetaTrader5` Python (resmi, butuh Windows + terminal lokal).
- Distribusi sinyal via Telegram.

## 9. Fase 4 — Monitoring & Feedback

### 9.1 Skema Database (3 tabel minimum)

- **`trades`**: trade_id, timestamp, pair, data_tag, state_machine_state, regime_detected, strategy_selected, confidence_score, hypothesis (terstruktur), entry/exit price, sl, tp, lot_size, exit_reason, pnl, spread_at_entry, slippage_realized, model_version_id
- **`blocked_signals`**: timestamp, pair, reason_blocked, confidence_at_time, would_be_entry_price
- **`model_registry`**: model_version, training_date, data_range, hyperparameters, backtest/forward_test metrics, deployed_at, status

### 9.2 Data Tagging — 4 Tingkat Ketat

`training` → `validation` (rawan kontaminasi kalau reused berulang) → `forward_test` (belum pernah dilihat) → `live_production` (paling murni).

### 9.3 Data Retention — Archive, Bukan Hapus

Hot tier (DB cepat): 60–90 hari. Warm/archive (Parquet terkompresi): selamanya — dibutuhkan untuk retraining rolling window & audit.

### 9.4 Filosofi Retraining — Human-in-the-Loop

Kumpulkan data baru → fine-tune (rolling window) → validasi di forward_test fresh → bandingkan metrik vs model production → **approval manual** → model lama tetap di registry untuk rollback. **Bukan** self-learning/RL otonom penuh (risiko selection bias & feedback loop berbahaya).

### 9.5 Telegram: Control Panel & Reporting

- **Scope saat ini**: khusus fase forward test (private/trusted circle), belum pembagian free/premium.
- Kontrol via **inline keyboard** (klik tombol), bukan command teks — tapi backend tetap validasi `user_id`, bukan hanya asumsi "chat ini privat". Aksi destruktif (emergency stop) wajib ada konfirmasi dua langkah.
- Command ini secara teknis = override manual ke state machine (`MANUAL_OVERRIDE`), bukan jalur kontrol terpisah dari risk gate.
- Laporan harian otomatis (akhir sesi \~12 jam): P&L, jumlah trade & win/loss, max DD hari itu, berapa kali engine PAUSED (nilai jual trust — bukti sistem proteksi aktif), spread rata-rata sesi, link ke myfxbook (source of truth, bukan klaim sendiri).
- **Rencana nanti** (setelah live ke komunitas): dashboard harian = free tier (transparansi publik), sinyal real-time per-trade = premium.

## 10. Broker Eksekusi: Bake-off Exness vs HFM

- Prinsip: likuiditas broker tidak bisa dinilai dari reputasi/kata orang — **kedua broker sama-sama punya bukti insiden slippage ekstrem saat news** (Exness lewat ToS gap rule, HFM lewat insiden nyata 6000+ pips slippage saat NFP Sept 2026). Tidak ada broker retail yang "kebal" — pertahanan utama tetap di sistem (state machine, graduated sizing), bukan "nemuin broker ajaib".
- HFM beroperasi di banyak entitas regulasi (ACPR, BaFIN, FCA, FSC, FSCA, MFSA) — tapi entitas yang menangani komplain riil adalah **HF Markets (SV) Ltd** (St. Vincent & Grenadines, regulasi longgar). Entitas yang akan menerima klien dari Indonesia perlu dicek eksplisit.
- Cent/micro account HFM punya value legit untuk testing live modal kecil — tapi ini terpisah dari soal "kualitas eksekusi saat volatil".
- **Metodologi bake-off** (tujuan: pilih satu pemenang, bukan jalan paralel permanen — jaga fokus):
  1. Kriteria ditentukan DI AWAL: slippage realized saat news (bobot terbesar), stabilitas spread normal, rejection/requote rate, biaya eksekusi total
  2. Apple-to-apple: sinyal sama di-mirror ke dua broker di waktu yang sama persis
  3. Batas waktu jelas: 2–4 minggu, cukup lewati beberapa siklus NFP/CPI
  4. Broker yang kalah di-drop total dari codebase setelah keputusan

## 11. Deployment

- Saat ini: laptop sendiri (Lenovo LOQ 15IRX9, i7, RTX 4050) — hardware lebih dari cukup untuk beban kerja ini.
- Operasional \~12 jam/hari (ikut sesi aktif), bukan 24/7.
- Mitigasi: disable sleep & auto-update Windows saat jam operasional, kabel LAN, UPS kecil.
- **Belum ada**: prosedur disaster recovery eksplisit (lihat §0 poin 3).
- Nanti: migrasi ke VPS **Windows** (bukan Linux, karena dependency `MetaTrader5`), atau refactor ke ZeroMQ bridge kalau multi-mesin.

## 12. AI Agent untuk Development

- **Orca** (onorca.dev, open source MIT, didukung YC) — Agent Development Environment, jalankan banyak coding agent paralel di git worktree terpisah.
- Setup: **OpenCode sebagai lead**, agent kedua (OMP) sebagai development/eksekusi. Akses model lewat **9Router**, dibatasi ke **OpenCode Free tier + OpenRouter saja** (hindari fitur subscription-interception/MITM Bridge 9Router yang berisiko ToS).
- **Boundary tegas**: LLM ini HANYA dev-tooling personal, **tidak pernah** masuk production pipeline. "Team researcher" produksi = evaluation pipeline kuantitatif murni (Sharpe, max DD, stabilitas OOS) + optimasi klasik non-LLM (genetic algorithm, Bayesian optimization) — production pipeline 100% self-contained.
- **Catatan penting**: paralelisme agent mempercepat *coding*, **tidak** mempercepat *validasi pasar* — forward test tetap butuh waktu kalender real (siklus NFP/CPI). Bottleneck proyek bergeser dari "nulis kode" ke "ngumpulin data valid" + "review manusia di modul safety-critical".

## 13. Marketing

- Platform: Telegram saja untuk v1.
- Trust: Myfxbook (verified, **harus transparan kalau masih demo**) + TikTok + Instagram.
- Pricing: free-first (bangun audience) → monetisasi setelah ramai.
- Konten: branding-driven, bukan ala IB generik. Kalau nanti jadi IB (modal lanjutan) — **wajib disclosure terbuka** soal komisi (konflik kepentingan struktural dengan risk management disiplin).
- Legal: disclaimer "bukan ajakan investasi" bukan legal shield penuh begitu mulai jual produk.

## 14. Urutan Build & Starting Parameters

### Starting Parameters (v1, konservatif — wajib dikalibrasi ulang dengan data real)

```yaml
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
  time_invalidation_bars: 8   # M15 terkonfirmasi => 2 jam (lihat §7.5)
  atr_timeframe: "M15"
  regime_timeframe: "H4"
  strategy_timeframe: "H1"

state_machine:
  z_threshold_pause: 3.0
  z_threshold_resume: 1.5
  k_stable_reads: 12
  m_stability_minutes: 5
  pre_news_watch_minutes: 10
  ewma_alpha: 0.08

research:
  monte_carlo_iterations: 1000
  retrain_light_cadence_days: 14
  retrain_full_cadence_days: 30
```

### Urutan Build (jangan lompat urutan)

| Milestone | Isi | Review manusia wajib? |
| --- | --- | --- |
| 1. Data Foundation | Skema DB, ingestion Exness + OANDA | - |
| 2. Backtest Engine | Rust extension, simulasi slippage eksplisit | 🔴 Ya — validasi manual terhadap hitungan tangan |
| 3. Satu Strategi + Regime Filter Sederhana | Volatility breakout, regime rule-based (ADX/ATR), **belum** Kronos | - |
| 4. Risk Gate & State Machine Sederhana | Starting parameters di atas, blackout kalender dulu (belum Z-score adaptif) | 🔴 Ya — baca logic sizing & kill-switch baris per baris |
| 5. Eksekusi Exness + Logging | **→ MULAI forward test sistem baru di sini** | - |
| 6. Notifikasi Telegram Minimal | Alert dasar + kontrol pause/resume | - |
| 7+. Layer In Sophistication | Kronos, macro feature, strategi ke-2/3/4, Z-score adaptif, liquidity detection, dashboard lengkap, bake-off broker | - |

**Definition of Done tiap milestone**: unit test untuk kalkulasi numerik, config tidak di-hardcode, logging cukup untuk divalidasi ulang, dan untuk modul 🔴 — review manual sebelum dianggap selesai (bukan cuma lolos test otomatis).

---

## 15. Action Items / Backlog Terbuka (gabungan seluruh sesi)

- [ ] **Tentukan ukuran modal awal** — cek apakah 0.5% risk per trade masih bisa dieksekusi di atas lot minimum 0.01 XAUUSD
- [x] ~~Konfirmasi resmi timeframe eksekusi~~ — selesai, lihat §7.5 (regime H4, strategi H1, entry M15)
- [ ] **Susun prosedur disaster recovery** untuk laptop-as-server (termasuk rencana manual intervention via app)
- [ ] **Tentukan kill criteria level proyek** (kapan dianggap perlu rombak total, bukan cuma tweak)
- [ ] Cek entitlement API Order/Position Book OANDA di tier akun
- [ ] Tarik angka pasti rentang bebas slippage & stop level XAUUSD dari Spesifikasi Kontrak Exness
- [ ] Baca General Business Terms & halaman ECN pending orders resmi Exness
- [ ] Cek kecukupan context length Kronos (512) untuk lookback strategi
- [ ] Riset empiris macro driver XAUUSD (korelasi/Granger causality)
- [ ] Konsultasi hukum fintech sebelum monetisasi real
- [ ] Cek entitas HFM spesifik yang akan menerima klien dari Indonesia (kalau bake-off jadi dilakukan)