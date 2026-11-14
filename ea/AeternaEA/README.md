# AETERNA EA — GOLDEN BASELINE v1.0 (FROZEN & PROTECTED)

> ⚠️ **PERINGATAN KERAS & ATURAN MUTLAK (IMMUTABLE BASELINE)**:
> Direktori ini memuat **Expert Advisor Baseline v1.0** resmi yang telah terverifikasi secara matematis dan empiris di MetaTrader 5 Strategy Tester.
>
> **DILARANG KERAS MENGUBAH, MENGEDIT, ATAU MEREFACTOR FILE DI DALAM DIREKTORI INI SECARA LANGSUNG.**

---

## 1. Verifikasi Kinerja Baseline v1.0 (SSoT)
* **Instrumen**: `XAUUSDm` (Broker Exness Standard)
* **Periode Pengujian**: 2020.01.01 s/d 2024.11.01 (4.8 Tahun / 51.941 Bar M15)
* **Deposit Awal**: $2,000.00 USD (Risiko 0.5% per trade)
* **Total Transaksi**: **813 Trades**
* **Win Rate**: **58.67%** (477 Win / 336 Loss)
* **Net Profit**: **+$436.67 USD** (+21.83% Net Return)
* **Gross Profit / Loss**: $3,214.56 USD / -$2,777.89 USD
* **Profit Factor**: **1.16**
* **Max Drawdown**: **8.16%** ($166.96 USD) — Lolos di bawah *Hard Killswitch* 10.0%

---

## 2. Aturan Pengembangan Lanjutan (Experimentation & Clone Protocol)

Jika di masa depan developer, sub-agent (`aeterna-*`), atau operator ingin melakukan eksperimen baru (seperti indikator tambahan, penyesuaian parameter, atau adaptasi pair lain):

1. **WAJIB MEMBUAT CLONE / SALINAN BARU**:
   * Buat folder terpisah di bawah `ea/experiments/<nama_eksperimen>/` (contoh: `ea/experiments/AeternaEA_v1_1_Opt/`).
   * Jangan pernah menyentuh file di dalam `ea/AeternaEA/`.
2. **Kompilasi & Benchmark Terhadap Baseline**:
   * Setiap versi eksperimen wajib diuji pada periode dan instrumen yang sama (2020–2024 `XAUUSDm`).
   * Versi eksperimen baru **HANYA BOLEH DIANGGAP SEBAGAI PENGGANTI BASELINE** jika mampu melampaui metrik v1.0:
     - Net Profit $> +\$436.67\text{ USD}$
     - Win Rate $\ge 58.0\%$
     - Profit Factor $> 1.16$
     - Max Drawdown tetap $< 10.0\%$
3. **Backup Beku (Frozen Backup)**:
   * Salinan identik dari baseline ini disimpan secara independen di `ea/AeternaEA_v1_Baseline/` sebagai arsip pemulihan bencana (*disaster recovery*).
