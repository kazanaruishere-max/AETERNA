# Product Requirements Document (PRD) — AI Trading XAUUSD (v1.0)

Dokumen ini merupakan turunan resmi dari `ai-trading-master-reference.md` (§1–3, §13) serta keputusan klarifikasi tahap planning. Menjadi acuan ruang lingkup produk, kriteria keberhasilan, dan batasan operasional sistem trading kuantitatif XAUUSD.

---

## 1. Latar Belakang & Pernyataan Masalah

Sistem kuantitatif generasi sebelumnya menghasilkan backtest 112k pips (2 tahun) dan forward test 32k pips (~3 bulan akun demo OANDA + Exness). Namun, sistem tersebut mengalami kegagalan kritis: **drawdown -41k pips dari peak 46k (≈51% dari peak global 80k)** akibat ketiadaan filter berita berdampak tinggi (*high-impact news*) dan ketiadaan validasi multi-regime.

### Pelajaran Utama & Sikap Proyek
1. **Track record kembali ke nol**: Hasil sistem lama tidak diakui sebagai validasi arsitektur baru. Seluruh klaim performa diuji ulang dari awal.
2. **Hard risk filtering**: Masuk pasar saat rilis berita besar adalah spekulasi liar, bukan trading kuantitatif terukur.
3. **Mandatory validation gates**: Walk-forward analysis, Monte Carlo simulation, dan uji reliabilitas eksekusi multi-broker adalah prasyarat mutlak sebelum dana riil dikelola.

---

## 2. Target Pengguna & Roadmap Produk

Pengembangan produk difokuskan solo-founder pada instrumen tunggal (**all-in XAUUSD**) melalui 3 fase bertahap:

### Fase 1: Internal Validation & Solo Operator (Milestone 1–5)
- **Pengguna**: Solo Founder / Developer.
- **Tujuan**: Validasi stabilitas sistem otomasi, risk watchdog, dan eksekusi broker tanpa intervensi manual tak terjadwal.
- **Akun**: Standard Demo Exness → Standard Real Exness (modal minimal ~$1,000).

### Fase 2: Private / Trusted Circle (Milestone 6)
- **Pengguna**: Komunitas tertutup (lingkar terpercaya, non-komersial).
- **Tujuan**: Menguji transparansi sinyal, stabilitas distribusi alert Telegram, dan verifikasi tracking pihak ketiga (Myfxbook terverifikasi).
- **Monetisasi**: Bebas biaya (Rp 0), fokus pada pembentukan rekam jejak publik yang transparan dan jujur.

### Fase 3: Ekspansi Komunitas & Komersialisasi (Pasca-Milestone 7)
- **Free Tier**: Publik dashboard harian, audit metrik (win rate, max DD, catatan proteksi engine saat news/spread spike).
- **Premium Tier**: Sinyal real-time per-trade via Telegram privat, lisensi Expert Advisor (EA).
- **Portofolio MQL5 / Copy Trading**: Dijalankan setelah memiliki modal mandiri dan audit track record terbukti stabil melintasi siklus makro.
- **Ekspansi Multi-Pair**: Rencana ekspansi ke major pairs (EURUSD, GBPUSD, USDJPY, USDCHF) hanya dipertimbangkan jika XAUUSD telah konsisten stabil minimal 6 bulan.

---

## 3. Ruang Lingkup Produk (Scope)

### In-Scope (v1.0)
- **Instrumen**: XAUUSD murni (spot gold terhadap US Dollar).
- **Gaya Trading**: Intraday murni. Seluruh posisi wajib ditutup sebelum sesi *rollover* harian Exness.
- **Broker & Tipe Akun**:
  - Exness: Akun **Standard** (MT5 Python API) untuk eksekusi, forward test demo, dan live trading. Sumber penentu margin dan leverage operasional.
  - OANDA: Akun v20 REST API untuk scanning sentimen dan *Order/Position Book*.
  - **Leverage Isolation Guard**: Regulasi leverage OANDA (misal batasan 1:20 ESMA/FCA) **TIDAK RELEVAN DAN DILARANG KERAS DIGUNAKAN** dalam simulasi margin, backtesting, maupun kalkulasi sizing. OANDA murni scanning tanpa eksekusi.
- **Risk Management**:
  - Risiko maksimal per trade: `0.5%` dari equity.
  - Batas kerugian harian maksimal: `2.0%` (circuit breaker harian).
  - Batas drawdown absolut sistem: `10.0%` (*hard killswitch*).
  - Posisi terbuka serentak: Maksimal 1 posisi.
  - Transaksi per hari: Maksimal 5 trade.
- **Filter Berita & Likuiditas**:
  - Dual layer: Kalender blackout terjadwal + deteksi lonjakan spread real-time via Z-score EWMA.
  - Likuiditas *graduated scale-down* berbasis tick volume M1.
- **Operasional & Monitoring**:
  - Jam kerja sistem: ~12 jam per hari (13:00 – 01:00 WIB dinamis berbasis timezone market).
    *Catatan Cakupan Sesi*: Window ini mencakup London Open, overlap London-NY (jam likuiditas tertinggi), dan awal hingga pertengahan sesi NY. Ekor sesi NY sore (01:00 – 05:00 WIB) **sengaja dikecualikan secara sadar** karena likuiditas emas menipis drastis pasca London close dan mendekati zona bahaya rollover/daily break.
  - Timezone Standard: Seluruh data internal dan database disimpan dalam **UTC murni (ISO-8601 string, e.g. `YYYY-MM-DDTHH:MM:SSZ`)**. Konversi ke WIB/lokal HANYA dilakukan pada layer presentasi (Telegram bot, dashboard).
  - Dynamic DST-Aware Session: Boundary sesi perdagangan (London Open, NY Open, overlap) TIDAK BOLEH di-hardcode sebagai offset UTC fixed, melainkan dihitung dinamis menggunakan library timezone (`zoneinfo` dengan `Europe/London` dan `America/New_York`) guna mengantisipasi jeda transisi DST UK vs US (gap 1–2 minggu di Maret dan Oktober/November).
  - Interface kontrol: Telegram Bot khusus admin (inline button untuk konfirmasi, status, dan pause/resume).
  - Audit trail pihak ketiga: Akun tersinkronisasi publik via Myfxbook (status demo wajib dinyatakan transparan).

### Out-of-Scope (v1.0)
- Scalping frekuensi tinggi (HFT) atau penahanan posisi swing menginap akhir pekan (*weekend gap risk*).
- Akun Cent / Micro (tidak digunakan; parameter sizing diselaraskan langsung ke minimum 0.01 lot Standard).
- Reinforcement Learning (RL) otonom penuh di live environment tanpa pengawasan (*human-in-the-loop* wajib untuk persetujuan model).
- Eksekusi multi-broker simultan permanen (hanya dilakukan temporer saat fase *bake-off* Exness vs HFM).
- Otomasi pembayaran/payment gateway untuk langganan sinyal.

---

## 4. Kriteria Keberhasilan & Project Kill Criteria

### Target Operasional & Finansial
1. **Modal Minimum Operasional**: Modal akun Standard riil disyaratkan minimal **~$1,000**. Jika modal belum mencukupi saat memasuki Milestone 5, forward test **wajib bertahan di Standard Demo** hingga dana terkumpul, guna mempertahankan konsistensi parameter `risk_per_trade_pct = 0.5%` pada lot minimum `0.01 lot`.
2. **Disiplin Proteksi News**: 0 transaksi tereksekusi saat state machine berada dalam status `PRE_NEWS_WATCH`, `PAUSED`, atau `RECOVERY_CHECK`.
3. **Penyimpangan Slippage Terkendali**: Realized slippage eksekusi tidak menyimpang lebih dari 1.5x rata-rata model simulasi backtest.

### Project Kill Criteria (Evaluasi Kegagalan Proyek)
Jika salah satu kondisi di bawah terpenuhi, pengembangan strategi saat ini **wajib dihentikan total dan dirombak ulang secara fundamental** (bukan sekadar penyesuaian parameter):
1. **Max Drawdown Kumulatif Forward Test > 15%**: Sistem otomatis masuk status terminasi proyek; evaluasi ulang hipotesis inti.
2. **Profit Factor < 1.0 ATAU Expectancy Negatif**: Dievaluasi setelah memenuhi **keduanya**:
   - Telah menyelesaikan minimal **100 trade**, DAN
   - Telah berjalan minimal **6 minggu kalender** (memastikan sistem telah teruji melintasi ragam rezim pasar dan rilis NFP/CPI bulanan).

### Model Recalibration Trigger (Kriteria Kalibrasi Backtest Engine)
- Jika realized slippage pada live/forward test secara konsisten (**>60% transaksi**) mencapai **≥ 2x lebih buruk** daripada model backtest, maka engine backtest dinyatakan tidak akurat.
- Tindakan: Sistem trading di-pause sementara, engine simulasi backtest disesuaikan ulang parameternya berdasarkan data tick dan histori spread nyata Exness, tanpa merombak strategi inti.

---

## 5. Kepatuhan Hukum & Legalitas

1. **Regulasi Domestik (Bappebti)**: Penjualan sinyal atau pengelolaan dana trading tanpa izin berbenturan dengan regulasi Bappebti di Indonesia. Seluruh perangkat EA diformulasikan sebagai *software analytics / personal trading tool*.
2. **Batasan Disclaimer**: Kalimat "bukan ajakan investasi / do your own risk" bukan pelindung hukum absolut saat terjadi transaksi komersial.
3. **Prasyarat Monetisasi**: Wajib melakukan konsultasi hukum fintech independen sebelum menerima pembayaran atau membuka subscription berbayar dari publik.
4. **Keterbukaan Afiliasi**: Jika di masa mendatang model bisnis melibatkan kemitraan Introducing Broker (IB), disclosure komisi wajib dicantumkan secara terbuka kepada seluruh pengguna untuk menjaga integritas mitigasi risiko.
