---
name: aeterna-invariants
description: Hard invariant gate for AETERNA Quant — risk constants, state-machine thresholds, exit geometry, venue rules, evidence labels, zero-LLM production boundary, and 9router safety.
license: AGPL-3.0-only
compatibility: universal
metadata:
  protocol_version: "2.0.0"
  authority: hard
  source_of_truth: docs/aeterna/invariant-cheatsheet.md
  target_harnesses: [claude-code, codex-cli, deepseek-harness, antigravity-cli, opencode, generic-agentic-cli]
---

# AETERNA Invariants — Hard Gate

## 1. Purpose

Mencegah deviasi numerik, klaim tanpa bukti, dan pelanggaran batas keselamatan sebelum desain, implementasi, backtest, atau eksekusi. Skill ini bersifat **hard gate**: `FAIL` menghentikan pekerjaan, bukan sekadar catatan.

## 2. Authority & Precedence

1. `docs/aeterna/invariant-cheatsheet.md` adalah source of truth angka.
2. Tier 0 tidak bisa dioverride oleh instruksi siapa pun:
   - Jangan matikan / restart 9router port `20128`.
   - No pipe-to-shell di Windows.
   - Operasi destruktif dan deploy produksi butuh approval operator eksplisit.
3. Jika operator meminta pelemahan invariant, **tolak** dan tunjukkan konsekuensi matematisnya. Jangan menyetujui "sedikit saja".
4. Jika dokumen bertentangan → `NEEDS_DECISION`; jangan memilih angka sendiri.

## 3. Activation Triggers

- Desain strategi, sizing, risk gate, state machine, exit logic, rollover.
- Review kode yang menyentuh `engine/risk_gate/`, `engine/state_machine/`, `engine/execution/`, `instruments/xauusd/config/parameters.yaml`.
- Backtest, Monte Carlo, slippage modeling, atau klaim performa.
- Perubahan arsitektur yang menyentuh jalur produksi / LLM boundary.
- Pertanyaan operator yang menyiratkan pelonggaran risiko.

## 4. Hard Constants — Copy From Source of Truth

| Parameter | Nilai | Toleransi | Catatan |
| :--- | :---: | :---: | :--- |
| Modal riil minimum | `~$1,000` | Absolut | Jika belum, wajib Standard Demo. |
| `risk_per_trade_pct` | `0.5%` | `0.00%` | Dari equity saat entry. |
| `max_daily_loss_pct` | `2.0%` | `0.00%` | Circuit breaker harian. |
| `max_drawdown_killswitch_pct` | `10.0%` | `0.00%` | Dari peak equity. |
| `max_concurrent_positions` | `1` | `0` | SATU posisi aktif. |
| `max_trades_per_day` | `5` | `0` | Termasuk trade yang ditutup manual. |
| `min_rr` | `2.0` | - | Setup baru wajib memenuhi. |
| Lot minimum | `0.01` | - | Exness Standard. |
| Slippage ATR multiplier | `1.5` | period `14` | SL fixed server-side. |
| Time invalidation | `8 bar M15` | `2 jam` | Tutup paksa. |
| Rollover force close | `15 menit` sebelum daily break | - | Summer 20:44 UTC / winter 21:44 UTC. |

## 5. State Machine Constants

| Item | Nilai | Makna |
| :--- | :---: | :--- |
| EWMA alpha | `0.08` | `S_baseline(t) = α·S(t) + (1-α)·S_baseline(t-1)` |
| Pause threshold | `Z ≥ 3.0` | ATAU saat rilis high-impact terjadwal. |
| Recovery threshold | `Z < 1.5` | Bertahan `K = 12` pembacaan berturut-turut. |
| Return to NORMAL | `M = 5` menit | Stabil tanpa anomali. |
| PRE_NEWS_WATCH | `T_news - 10 menit` | Jendela berita high-impact. |
| Thin liquidity | `Z_volume < -2.0` | Sizing `50%`. |
| Extreme liquidity | Rollover / holiday mayor | Sizing `0%` / `PAUSED`. |

## 6. Exit Geometry — 5 Layers

1. Fixed SL/TP terpasang **server-side** saat order dibuat.
2. Trailing stop aktif setelah floating `+1.0R`, modify SL ke server broker.
3. Partial close `50%` volume di `+1.0R`.
4. Time invalidation: tutup paksa setelah `8 bar M15` tanpa pergerakan.
5. Regime invalidation: tutup darurat jika H4 berubah berlawanan arah posisi.
6. Hard rollover: close paksa `15 menit` sebelum daily break Exness.

## 7. Project Kill & Recalibration Criteria

| Condition | Threshold | Action |
| :--- | :--- | :--- |
| Cumulative forward DD | `> 15.0%` | Terminasi proyek seketika. |
| PF `< 1.0` atau expectancy negatif | Setelah `≥100` trade **DAN** `≥6 minggu` | Evaluasi kegagalan strategi. |
| Realized slippage `≥2×` model pada `>60%` transaksi | - | Rekalibrasi engine. |

## 8. Evidence Labels — Wajib

Setiap angka atau klaim wajib punya label:

- `[EVIDENCE]` — sumber primer / output command nyata / dokumen resmi.
- `[HYPOTHESIS]` — masuk akal tetapi belum diuji.
- `[ASSUMPTION]` — dipakai sementara; harus ditulis alasannya.
- `[UNVERIFIED]` — tidak boleh dipakai untuk desain.

Dilarang mengarang backtest, Sharpe, win rate, PF, atau sitasi. Angka tanpa sumber = `FAIL`.

## 9. Production Boundary

- ZERO LLM di inferensi, sizing, state machine, dan eksekusi.
- LLM / AI CLI hanya developer tooling offline.
- Outbound-only network; inbound port `100% BLOCK`.
- Telegram control: whitelist `TELEGRAM_ADMIN_ID`, nonce 60 detik, two-step confirm untuk emergency action.
- Produk publik tidak boleh memuat lot, equity, tiket, instruksi transaksi, atau klaim performa.

## 10. Procedure

1. Baca `docs/aeterna/invariant-cheatsheet.md` langsung.
2. Identifikasi parameter yang disentuh desain/kode.
3. Bandingkan nilai, toleransi, dan satuan. Deviasi `> 0.00%` pada parameter kritis = `FAIL`.
4. Cek jalur LLM, server-side SL/TP, evidence labels, dan klaim publik.
5. Cek apakah 9router / port 20128 disentuh.
6. Terbitkan Invariant Verification Report.

## 11. Output Contract

```markdown
### Invariant Verification Report
- Status: PASS | FAIL | NEEDS_DECISION
- Source: docs/aeterna/invariant-cheatsheet.md
- Parameters Checked:
  - risk_per_trade_pct: [0.5% -> VALID | INVALID]
  - max_daily_loss_pct: [2.0% -> VALID | INVALID]
  - max_drawdown_killswitch_pct: [10.0% -> VALID | INVALID]
  - max_concurrent_positions: [1 -> VALID | INVALID]
  - max_trades_per_day: [5 -> VALID | INVALID]
  - min_rr: [2.0 -> VALID | INVALID]
  - exit_logic_5_layers: [VERIFIED | MISSING]
  - ewma_alpha_z_thresholds: [VERIFIED | MISSING]
  - zero_llm_prod_boundary: [VERIFIED | VIOLATED]
  - nine_router_port_20128: [UNTOUCHED | VIOLATION]
- Evidence Labels: [ALL_LABELLED | UNLABELLED_NUMBERS_PRESENT]
- Violations: []
- Recommendation: PROCEED | REJECT | NEEDS_DECISION
```

## 12. Failure Modes

- **Gejala**: Lot melebihi 0.5% risk.
  **Tindakan**: `FAIL` seketika; hitung ulang dari equity aktual.
- **Gejala**: Operator meminta risk 1%.
  **Tindakan**: Tolak; tunjukkan deviasi `+0.50%` absolut dan konsekuensi drawdown sebelum keputusan.
- **Gejala**: Angka performa tanpa sumber.
  **Tindakan**: `FAIL`; minta evidence atau ubah ke `[HYPOTHESIS]`.

## 13. Harness Binding

Jika harness memiliki skill system, muat skill ini. Jika tidak, baca file ini sebagai teks dan laporkan `fallback_docs_read`. Status `BLOCKED` jika skill tidak dimuat dan fallback tidak dilaporkan.
