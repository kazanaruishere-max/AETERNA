---
name: aeterna-milestone-gate
description: Panduan audit pemenuhan verification gates Milestone M1-M7, 3 audit manusia wajib, dan evaluasi project kill criteria.
license: Proprietary
compatibility: opencode
metadata:
  workflow: quality-gate
  milestones: M1-M7
---

# Purpose
Mengatur pengawasan ketat terhadap transisi milestone pengembangan. Mencegah lompatan tahap sebelum modul dasar terbukti deterministik dan memenuhi syarat keselamatan dana riil.

# When to use
- Gunakan saat menyelesaikan seluruh task dalam suatu milestone sebelum berpindah ke milestone berikutnya.
- Gunakan saat melakukan audit berkala terhadap Project Kill Criteria dan Recalibration Trigger.
- Gunakan saat mempersiapkan sesi Human Review wajib (🔴).

# Hard rules
1. Dilarang keras melompati urutan milestone (M1 -> M2 -> M3 -> M4 -> M5 -> M6 -> M7).
2. Tiga Milestone Gate wajib mendapatkan approval manual tertulis dari Human Operator:
   - 🔴 **GATE-M2**: Audit manual perhitungan PnL Rust, spread penalty, dan slippage vs hitungan tangan.
   - 🔴 **GATE-M4**: Audit baris demi baris logika sizing lot, batas drawdown, dan emergency killswitch Go.
   - 🔴 **GATE-M5**: Uji eksekusi demo, pastikan SL/TP terverifikasi ada di server broker MT5.
3. Forward test resmi HANYA boleh dimulai setelah Milestone 5 selesai dan lolos verifikasi.
4. Jika modal riil belum mencapai ~$1,000, forward test wajib berjalan di akun Standard Demo.

# Required inputs
- Bukti eksekusi test suite milestone dari `aeterna-verifier`.
- Dokumen RTM `docs/aeterna/requirements.md` dengan status task terkait.
- Catatan audit log transaksi / simulasi.

# Procedure
1. Periksa apakah seluruh REQ pada milestone target berstatus `VERIFIED` di RTM.
2. Jalankan test suite terintegrasi menggunakan perintah resmi.
3. Jika milestone memiliki flag 🔴 Human Review, susun lembar audit ringkas untuk operator.
4. Periksa metrik terhadap Project Kill Criteria:
   - Max Drawdown Kumulatif > 15% -> TERMINASI PROYEK.
   - Profit Factor < 1.0 setelah 100 trade & 6 minggu -> TERMINASI STRATEGI.
   - Realized slippage > 2x model pada > 60% trade -> REKALIBRASI ENGINE.
5. Terbitkan sertifikat kelulusan gate: `GATE-M<X>: PASSED`.

# Output contract
```markdown
### Milestone Gate Audit: GATE-M<X>
- Target Milestone: M<1-7> (<Nama>)
- All REQs Verified: [YES | NO]
- Automated Tests: <command> -> <N passed, 0 failed>
- Human Review Required: [YES (Approved by Operator) | NO]
- Kill Criteria Check: [ALL CLEAR]
- Gate Status: PASSED | REJECTED
```

# Self-check
1. [ ] Apakah milestone sebelumnya sudah berstatus PASSED?
2. [ ] Apakah Human Review Gate (M2, M4, M5) sudah disetujui manusia secara eksplisit?
3. [ ] Apakah tidak ada assertion-less test?

# Failure modes
- **Gejala**: Kode mencoba membuka order live sebelum Milestone 5 diverifikasi.
- **Tindakan**: Trigger Killswitch darurat, set status sistem ke `NO-ENTRY`.
