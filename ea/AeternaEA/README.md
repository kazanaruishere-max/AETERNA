# AETERNA EA — GOLDEN BASELINE v2.1 (REAL-TICK CERTIFIED & ATH CALIBRATED)

> ⚠️ **STATUS DOKUMEN: IMMUTABLE GOLDEN BASELINE v2.1 (FROZEN)**:
> Direktori ini memuat **Expert Advisor Baseline v2.1 Resmi** yang telah lolos seluruh 6 tahap sertifikasi institusional (Tahap L-01 s/d L-06) di MetaTrader 5 Strategy Tester.
>
> Baseline v2.1 dipromosikan menggantikan v2.0 per aturan ADR-016 dan ADR-017 setelah membuktikan keunggulan di data 198+ juta centang riil Exness (Real Ticks Model=4 dengan 200 ms delay) tanpa manipulasi kurva.

---

## 1. Verifikasi Kinerja Golden Baseline v2.1 (SSoT)
* **Instrumen**: `XAUUSDm` (Broker Exness Standard)
* **Periode Pengujian**: 2022.01.01 s/d 2026.11.13 (4.9 Tahun Kalender / Era Modern All-Time High $2,700+)
* **Deposit Awal**: $4,000.00 USD (Risiko 0.5% per trade, Leverage 1:2000)
* **Model Eksekusi**: **Model=4 (Every tick based on real ticks broker Exness, 200 ms latency delay)**
* **Total Ticks Diproses**: **197.957.013 Ticks Nyata**
* **Total Transaksi**: **755 Trades** (~3.0 trade/minggu)
* **Tingkat Kemenangan (Win Rate)**: **57.62%** (435 Win / 320 Loss)
* **Total Net Profit**: **+$732.07 USD** (+18.30% Net Return pada data centang riil Exness)
* **Profit Factor (PF)**: **1.12**
* **Expected Payoff**: **+$0.97 USD / trade**
* **Maximum Equity Drawdown**: **6.35%** ($317.74 USD) — *Jauh di bawah Hard Killswitch 10.0%*
* **Zero Order Rejection**: Error 10018 = 0 kali sepanjang 198 juta centang riil.
* **Audit Visual L-01**: Lolos verifikasi visual chart (126.592 ticks, 2.116 bars, final balance $4.018.56 USD).

---

## 2. Inovasi Kunci Baseline v2.1 vs v2.0
1. **Desensitisasi State Machine (ADR-016)**: Menghapus fenomena *collapse of variance* pada frekuensi centang riil dengan *Volatility Floor* (`sigma_floor = max(5.0 pts, 0.20 * baseline)`) dan filter persistensi 5 centang. Menyelamatkan 455 transaksi valid yang sebelumnya terblokir false alarm.
2. **Pure Structural Breathing Exit (ADR-017)**: Menghapus trailing ratchet prematur +1.2R yang mencekik posisi akibat *micro-wicks* intrabar emas $2,700. Menerapkan Partial Close 50% di +1.5R, penguncian Breakeven +0.10R buffer, dan membiarkan runner melesat ke TP penuh +2.6R (atau wide ratchet di +2.0R dengan 1.0R buffer).
3. **100% Dynamic ATR Scaling**: Stop Loss beradaptasi penuh terhadap fluktuasi harga emas mahal.
4. **Multi-Tier Dynamic Drawdown Throttling**: Memotong alokasi risiko menjadi 0.25% saat Drawdown >= 5.0%, menggandakan runway ketahanan modal hingga 32 loss beruntun sebelum menyentuh killswitch 10.0%.

---

## 3. Aturan Pengembangan Lanjutan (ADR-009 Clone Protocol)
Setiap eksperimen baru di masa depan **WAJIB dibuatkan klon di `ea/experiments/<nama_eksperimen>/`**. Dilarang mengubah file di direktori ini tanpa tiket promosi resmi. Baseline v1.0 lama tetap terarsip aman di `ea/AeternaEA_v1_Baseline/`.
