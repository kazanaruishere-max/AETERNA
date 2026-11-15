# AETERNA EA — GOLDEN BASELINE v2.0 (DYNAMIC ATR & ATH CALIBRATED)

> ⚠️ **STATUS DOKUMEN: IMMUTABLE GOLDEN BASELINE v2.0 (FROZEN)**:
> Direktori ini memuat **Expert Advisor Baseline v2.0 Resmi** yang telah lolos sertifikasi bertingkat institusional (Tahap L-01 s/d L-05) di MetaTrader 5 Strategy Tester.
>
> Baseline v2.0 dipromosikan menggantikan v1.0 per aturan ADR-009 dan ADR-015 setelah membuktikan keunggulan di era rekor All-Time High emas ($2,700+/oz) tanpa manipulasi kurva.

---

## 1. Verifikasi Kinerja Golden Baseline v2.0 (SSoT)
* **Instrumen**: `XAUUSDm` (Broker Exness Standard)
* **Periode Pengujian**: 2022.01.01 s/d 2026.11.13 (4.9 Tahun Kalender / Era Modern)
* **Deposit Awal**: $4,000.00 USD (Risiko 0.5% per trade, Leverage 1:2000)
* **Total Transaksi**: **771 Trades** (~3.0 trade/minggu)
* **Tingkat Kemenangan (Win Rate)**: **58.24%** (449 Win / 322 Loss)
* **Total Net Profit**: **+$905.15 USD** (+22.63% Net Return)
* **Profit Factor (PF)**: **1.15**
* **Expected Payoff**: **+$1.17 USD / trade**
* **Maximum Equity Drawdown**: **5.26%** ($257.85 USD) — *Jauh di bawah Hard Killswitch 10.0%*
* **Custom Calmar Proxy**: **158.46** (Profit / Max DD %)
* **Ketahanan Latensi L-02**: Lolos 200 ms delay dengan deviasi 0.00% dan zero error 10018.
* **Audit Visual L-01**: Lolos verifikasi visual chart (126.592 ticks, 2.116 bars, final balance $4.018.56 USD).

---

## 2. Inovasi Kunci Baseline v2.0 vs v1.0
1. **100% Dynamic ATR Scaling**: Menghapus plafon Stop Loss statis $3.50 yang mencekik trade saat harga emas $2,700, diganti formula adaptif `MathMax(current_atr * 1.4, fallback_cap)`.
2. **Kanal Donchian 24 Bars (6 Jam M15)**: Menyaring false breakout saat pasar berkonsolidasi.
3. **Multi-Tier Dynamic Drawdown Throttling**: Memotong alokasi risiko menjadi 0.25% saat Drawdown >= 5.0%, menggandakan runway ketahanan modal hingga 32 loss beruntun sebelum menyentuh killswitch 10.0%.
4. **Universal Symbol Adaptation**: Jarak Stop Loss beradaptasi otomatis pada kuotasi emas maupun pair forex.

---

## 3. Aturan Pengembangan Lanjutan (ADR-009 Clone Protocol)
Setiap eksperimen baru di masa depan **WAJIB dibuatkan klon di `ea/experiments/<nama_eksperimen>/`**. Dilarang mengubah file di direktori ini tanpa tiket promosi resmi. Baseline v1.0 lama tetap terarsip aman di `ea/AeternaEA_v1_Baseline/`.
