# PLAN-05 — Floating / Spike / Leverage / Margin Defense

- `plan_id`: PLAN-05
- `created_utc`: 2026-11-22
- `status`: ACCEPTED_PHASED_DEFENSE
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-risk`
- `evidence_status`: VENUE_RULES_ADOPTED
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Premise

Apakah AETERNA bisa memperbaiki masalah floating, spike, leverage, dan margin?

## 2. Current Facts

Research brief `aeterna-research` 2026-11-22, sumber dokumentasi resmi Exness:

- `Equity = Balance ± Floating P/L + Swaps`.
- `Margin Level = Equity / Margin × 100`.
- Standard: margin call `60%`, stop out `0%`.
- HMR aktif 15 menit sebelum high-impact news sampai 90 detik setelahnya.
- Spread melebar saat news, market open/close.
- Leverage lebih tinggi menurunkan margin tetapi menaikkan sensitivitas stop-out.

AETERNA sudah punya: `Z≥3 → PAUSED`, `Z_volume<-2 → sizing 50%`, rollover/extreme → `0%`, risk `0.5%`, daily `2%`, DD `10%`.

## 3. The Unknowns

- Entity/akun dan leverage aktual.
- Currency akun.
- Apakah telemetry sudah menyimpan equity/margin snapshot.
- Margin level saat 1R adverse.

## 4. Options & Trade-offs

- Prevention-only: state machine + spread Z + sizing + HMR blackout.
- Projected margin-level gate: lebih kuat, tapi butuh data akun dan kalibrasi.
- Naikkan leverage: ditolak; dokumen Exness sendiri menyatakan sensitivitas stop-out naik.

## 5. Direction

AETERNA tidak memperbaiki mekanika broker. AETERNA hanya mendeteksi, menunda, mengecilkan, atau memblokir paparan.

## 6. Cheapest Test

Phase A: replay candle + `news_telemetry`, inject spread spike historis, assert PAUSED sebelum HMR dan sizing turun ke 50%/0%.

Phase B: tambahkan telemetry equity/margin read-only, hitung projected margin level saat 1R adverse. Kalibrasi buffer dari data teramati, bukan angka sembarangan.

## 7. Entry Criteria / Kill Switch

Blokir desain jika memakai threshold tanpa situs source atau memerlukan `order_send`. Tidak ada kenaikan leverage sebagai solusi.

## 8. Explicit Non-Authorization

File ini bukan izin mengubah margin broker, bukan nasihat broker, dan bukan izin order live.
