# PLAN-01 — Parabolic SAR Scalping EA

- `plan_id`: PLAN-01
- `created_utc`: 2026-11-22
- `status`: DEFERRED_CANDIDATE
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-strategy` + `aeterna-backtest`
- `evidence_status`: HYPOTHESIS / TEST_FIRST
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Premise

Menambah EA Parabolic SAR scalping cepat untuk XAUUSD.

## 2. Current Facts

- Strategi yang ada: `VolatilityBreakoutStrategy`, `MeanReversionRangingStrategy`, `PositioningContrarianStrategy`.
- Tidak ada implementasi PSAR di `instruments/xauusd/strategies/`.
- `aeterna-research` 2026-11-22: tidak ditemukan bukti terverifikasi PSAR edge net-of-cost di XAUUSD M1–M15. Satu preprint Bitcoin 2025 tidak dapat ditransfer; abstraknya 403.
- Invariant tetap: `min_rr=2.0`, `max_trades_per_day=5`, `max_concurrent_positions=1`.

## 3. The Unknowns

- Edge setelah spread dan commission.
- Stabilitas parameter PSAR.
- Fill latency di M15 close.
- Apakah “cepet” manusia menabrak batas 5 trade/hari atau R:R 2.0.

## 4. Options & Trade-offs

- PSAR sebagai filter strategi existing: murah, exit 5 lapis tetap utuh.
- EA PSAR penuh: perlu backtest + M5 demo ulang, surface area bug lebih besar.

## 5. Direction

Belum layak dibangun sebagai EA. PSAR hanya kandidat setelah uji net-of-spread lolos.

## 6. Cheapest Test

Pre-register satu parameter tetap. Fill di next completed bar open. Haircut biaya dari `news_telemetry.peak_spread_pts` dan baseline spread. Gagal jika:

1. net points after haircut `<= 0`; atau
2. median gross edge `<=` median spread pada flip bar; atau
3. tanda P&L berubah saat jendela news dihapus.

Ulangi pada holdout yang disjoint. Tanpa parameter search pada sample yang sama.

## 7. Entry Criteria / Kill Switch

Task packet OMP harus dibuat dulu. Tidak ada `order_send`, tidak ada EA live, tidak ada klaim performa sebelum test PASS dan gate strategi terpenuhi.

## 8. Explicit Non-Authorization

File ini bukan persetujuan implementasi, bukan hasil backtest, dan bukan klaim bahwa PSAR memiliki edge.
