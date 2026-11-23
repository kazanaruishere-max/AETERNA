# PLAN-06 — User Forward-Test Telemetry

- `plan_id`: PLAN-06
- `created_utc`: 2026-11-22
- `status`: CONDITIONAL_INTERNAL_ONLY
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-lead` + `aeterna-security` + human counsel
- `evidence_status`: LEGAL_BLOCKED
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Premise

Demo AETERNA ke orang dan sistem otomatis mendeteksi apakah forward test user win atau loss, dengan izin user.

## 2. Current Facts

- Fase aktif P1 Journal. P2 baru admin/staging.
- P3 VIP butuh sampel + audit verifier + review kepatuhan.
- Konten publik dilarang memuat lot, equity, tiket, instruksi transaksi, server, atau klaim performa.
- `active_task: null`.
- `aeterna-research` 2026-11-22 meminta pendapat OJK/Bappebti sebelum demo eksternal.
- Penulis bukan penasihat hukum.

## 3. The Unknowns

- Klasifikasi regulator untuk demo `SIGNAL_ONLY`.
- Granular consent, retention, cross-border transfer.
- Yurisdiksi user.
- Apakah connector read-only MT5 diizinkan.

## 4. Options & Trade-offs

- Opt-in manual outcome import: minim field, tanpa kredensial, friction lebih tinggi.
- Connector read-only MT5: otomatis, tapi security review berat.
- Leaderboard/klaim performa publik: ditolak.

## 5. Direction

Manual opt-in dulu, internal P1/P2. Izin per user eksplisit dan bisa dicabut. Output publik hanya agregat anonim. Jangan minta kredensial MT5.

## 6. Cheapest Test

Mock consent form + 20 synthetic outcome rows. Verifier memastikan output hanya berisi `outcome_label`, `r_multiple`, `invalidated`, dan count. Tidak boleh ada account ID, lot, equity, tiket, server, atau klaim performa.

Sebelum user nyata: pendapat hukum tertulis harus tersimpan.

## 7. Entry Criteria / Kill Switch

STOP jika counsel opinion belum ada. STOP jika consent tidak eksplisit. STOP jika output mengandung lot/equity/ticket/server/performance claim.

## 8. Explicit Non-Authorization

File ini bukan izin demo publik, bukan izin pengumpulan data pribadi, bukan izin pengelolaan dana, dan bukan klaim performa.
