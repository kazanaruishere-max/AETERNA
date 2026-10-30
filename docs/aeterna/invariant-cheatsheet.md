# Invariant Cheatsheet — AETERNA Quant Project (docs/aeterna/invariant-cheatsheet.md)

Dokumen ini adalah *Single Source of Truth* untuk seluruh konstanta numerik, formula matematis, dan batasan operasional sistem trading XAUUSD v1.0. Agen dilarang mengubah atau memodifikasi angka-angka di bawah ini tanpa izin tertulis dari Lead Architect.

---

## 1. Parameter Finansial & Manajemen Risiko

| Parameter | Nilai Resmi | Toleransi | Catatan / Rujukan |
| :--- | :---: | :---: | :--- |
| **Modal Minimum Riil** | `~$1,000` USD | Absolut | PRD §4 (Jika belum terpenuhi, wajib Standard Demo) |
| **Risiko Per Trade (`risk_per_trade_pct`)** | `0.5%` | 0.00% | Dari total equity akun saat entry |
| **Batas Kerugian Harian (`max_daily_loss_pct`)** | `2.0%` | 0.00% | Circuit breaker: stop trading untuk hari berjalan |
| **Hard Drawdown Killswitch (`max_drawdown_killswitch_pct`)** | `10.0%` | 0.00% | Dari peak equity: shutdown total mesin |
| **Maksimal Posisi Terbuka Serentak** | `1` posisi | 0 | PRD §3 (`max_concurrent_positions = 1`) |
| **Maksimal Transaksi Per Hari** | `5` trade | 0 | PRD §3 (`max_trades_per_day = 5`) |
| **Ukuran Lot Minimum Broker** | `0.01` lot | - | Standar Exness Standard Account |
| **Minimum Reward-to-Risk Ratio** | `2.0` | - | R:R minimal untuk setiap setup entry baru |

---

## 2. Multi-Timeframe Hierarchy

| Layer | Timeframe | Indikator / Model | Fungsi Utama |
| :--- | :---: | :--- | :--- |
| **Regime Detection** | **H4** | Kronos ONNX Runtime CPU (Context 512 candle ≈ 3.5–4 bulan) | Filter makro, penentu bias arah utama |
| **Strategy Setup** | **H1** | ATR(14), OANDA Book (refresh 15–30 menit), Key Levels | Identifikasi pola breakout atau mean reversion |
| **Execution & Entry** | **M15** | Presisi entry, perhitungan SL ATR(14), Time Invalidation | Timing eksekusi, trailing SL, scale-out |

---

## 3. Rumus & Threshold State Machine Berita

### 3.1 Formula Matematis
1. **Spread Baseline (EWMA)**:
   $$S_{baseline}(t) = \alpha \cdot S(t) + (1 - \alpha) \cdot S_{baseline}(t - 1)$$
   dengan $\alpha = 0.08$.
2. **Spread Z-Score**:
   $$Z(t) = \frac{S(t) - S_{baseline}(t)}{\sigma_S(t)}$$

### 3.2 Threshold Transisi State
- **Masuk `PRE_NEWS_WATCH`**: $T_{news} - 10$ menit (jendela berita *high-impact* terjadwal).
- **Masuk `PAUSED`**: $Z(t) \ge 3.0$ ATAU berada dalam rilis berita terjadwal.
- **Masuk `RECOVERY_CHECK`**: $Z(t) < 1.5$ bertahan selama minimal $K = 12$ pembacaan berturut-turut.
- **Kembali ke `NORMAL`**: Kondisi stabil bertahan selama $M = 5$ menit berturut-turut tanpa anomali.

---

## 4. Exit Logic 5 Lapis & Aturan Waktu

1. **Lapis 1 (Fixed SL & TP)**: Wajib terpasang *server-side* langsung di broker Exness saat order dibuat (`sl_method: "atr"`, `sl_atr_multiplier: 1.5`, period 14).
2. **Lapis 2 (Dynamic Trailing Stop)**: Aktif setelah floating profit mencapai $+1.0\text{R}$. Kirim order modify SL ke server broker.
3. **Lapis 3 (Partial Close / Scale-Out)**: Likuidasi otomatis $50\%$ volume posisi saat mencapai target $+1.0\text{R}$.
4. **Lapis 4 (Time-Based Invalidation)**: Tutup paksa posisi jika pasar diam selama $8$ bar M15 (tepat $2$ jam).
5. **Lapis 5 (Regime Invalidation)**: Tutup darurat seketika jika deteksi regime H4 berubah berlawanan arah dengan posisi aktif.
6. **Hard Rollover Rule**: Seluruh posisi **WAJIB ditutup paksa 15 menit sebelum daily break Exness** (Summer: 20:44 UTC / 03:44 WIB; Winter: 21:44 UTC / 04:44 WIB; rujukan resmi: [Exness Help Center: Instrument trading hours #4405235684498](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours)).

---

## 5. Deteksi Likuiditas & Graduated Sizing

- **Likuiditas Normal**: Alokasi lot $100\%$ (basis 0.5% risk).
- **Likuiditas Menipis ($Z_{volume} < -2.0$)**: Pangkas ukuran lot menjadi **50%** dari sizing normal.
- **Likuiditas Ekstrem (Rollover / Bank Holiday Mayor)**: **0% sizing** (Sistem otomatis masuk status `PAUSED`).

---

## 6. Project Kill Criteria & Ambang Kalibrasi

- **Terminasi Proyek Seketika**: Max Drawdown Kumulatif forward test menyentuh $> 15.0\%$.
- **Evaluasi Kegagalan Strategi**: Profit Factor $< 1.0$ ATAU Expectancy negatif setelah **keduanya** terpenuhi:
  - $\ge 100$ trade selesai, DAN
  - Berjalan $\ge 6$ minggu kalender.
- **Model Recalibration Trigger**: Realized slippage pada $>60\%$ transaksi mencapai $\ge 2\times$ lebih buruk dari simulasi backtest.

---

## 7. Arsitektur & Keamanan Mutlak

- **Zero Inbound Port**: Port firewall inbound 100% BLOCK. Semua traffic keluar (outbound-only).
- **Telegram Bot Control**: Whitelist hanya ke `TELEGRAM_ADMIN_ID` (integer). Nonce kedaluwarsa 60 detik. Two-step confirmation untuk emergency actions.
- **Do Not Kill Port 20128**: Proses 9router TIDAK PERNAH boleh dihentikan.
- **Zero LLM di Live Trading**: Model produksi 100% deterministik native CPU runtime.
