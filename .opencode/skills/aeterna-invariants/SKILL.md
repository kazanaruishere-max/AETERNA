---
name: aeterna-invariants
description: Operasional checklist konstanta absolut, batas risiko, rumus state machine, dan arsitektur ZERO LLM sistem AI Trading XAUUSD.
license: Proprietary
compatibility: opencode
metadata:
  domain: quant-trading
  instrument: XAUUSD
---

# Purpose
Menyediakan checklist validasi deterministik untuk seluruh angka mati, batas risiko keuangan, rumus matematis, dan batasan arsitektur sistem XAUUSD v1.0. Menghindari deviasi parameter pada tahap desain maupun verifikasi kode.

# When to use
- Gunakan saat merancang modul kalkulasi risiko, sizing, strategi, backtest, dan eksekusi MT5.
- Gunakan sebelum task packet dikirim ke OMP untuk memastikan tidak ada angka yang melenceng.
- Gunakan saat `aeterna-verifier` mengaudit kode hasil kerja OMP.

# Hard rules
1. Modal riil minimum $1,000 USD (wajib Standard Demo jika belum tercapai).
2. `risk_per_trade_pct = 0.5%` tanpa toleransi toleransi floating.
3. `max_daily_loss_pct = 2.0%` (circuit breaker harian).
4. `max_drawdown_killswitch_pct = 10.0%` (hard shutdown sistem).
5. Maksimal 1 posisi aktif dan 5 transaksi per hari.
6. Exit 5 lapis wajib: Fixed SL/TP server-side, trailing stop +1R server-side, scale-out 50% di +1R, time invalidation 8 candle M15 (2 jam), regime invalidation H4.
7. Force close seluruh posisi 15 menit sebelum rollover harian bank.
8. ZERO LLM di jalur inferensi/eksekusi produksi.
9. Dilarang mematikan proses 9router (port 20128).
10. Outbound-only networking: 100% inbound ports BLOCKED.

# Required inputs
- Potongan kode, parameter konfigurasi YAML, atau desain arsitektur yang hendak divalidasi terhadap batas invariant.

# Procedure
1. Cocokkan nilai parameter input dengan tabel di `docs/aeterna/invariant-cheatsheet.md`.
2. Validasi keterpenuhan batas toleransi (0.00% deviasi pada parameter kritis).
3. Periksa apakah ada pemanggilan API LLM eksternal pada jalur produksi.
4. Periksa apakah mekanisme SL/TP dipasang *server-side* langsung ke broker Exness.
5. Keluarkan status kelulusan evaluasi invariant: `PASS` atau `FAIL` dengan rincian deviasi.

# Output contract
```markdown
### Invariant Verification Report
- Status: PASS | FAIL
- Parameter Checked:
  - risk_per_trade_pct: [0.5% -> VALID]
  - max_daily_loss_pct: [2.0% -> VALID]
  - max_drawdown_killswitch_pct: [10.0% -> VALID]
  - max_concurrent_positions: [1 -> VALID]
  - exit_logic_5_layers: [VERIFIED]
  - zero_llm_prod_boundary: [VERIFIED]
- Violations: []
- Recommendation: [PROCEED | REJECT]
```

# Self-check
1. [ ] Apakah semua angka dicocokkan langsung ke `docs/aeterna/invariant-cheatsheet.md`?
2. [ ] Apakah ada angka yang dibulatkan tanpa dasar?
3. [ ] Apakah parameter server-side SL/TP telah diverifikasi?

# Failure modes
- **Gejala**: Parameter lot size melebihi formula 0.5% risk.
- **Tindakan**: Tolak kode seketika (`status: FAIL`), instruksikan perbaikan perhitungan lot berbasis equity aktual.
