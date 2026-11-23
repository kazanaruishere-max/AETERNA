# PLAN-04 — Weekly News JSON Snapshot

- `plan_id`: PLAN-04
- `created_utc`: 2026-11-22
- `status`: ACCEPTED_AS_ARCHIVE_ONLY
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-ingestion`
- `evidence_status`: ENGINEERING_CHOICE / NOT_OFFICIAL_CADENCE
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Premise

Pengambilan news JSON seminggu sekali supaya sistem lebih siap.

## 2. Current Facts

- `scripts/export_calendar_snapshot.py` mengambil window `now-1 day` sampai `now+7 days`, filter USD HIGH, menulis `data/calendar_snapshot.json`.
- Runtime terverifikasi: `NEWS_SOURCE=MQL5_SNAPSHOT event_count=9`.
- Dokumentasi MQL5 resmi: nilai kalender dikirim saat publikasi dan sinkron via `change_id`. Tidak ada endpoint weekly resmi.

## 3. The Unknowns

- Event baru atau reschedule dalam seminggu.
- Timezone drift.
- Apakah blackout window tetap benar setelah 7 hari.

## 4. Options & Trade-offs

- Weekly archive + refresh harian/pre-market: praktis, risiko rendah.
- Weekly-only: paling malas, tapi buta terhadap perubahan.
- `CalendarValueLast` inkremental: paling benar, kerja lebih besar.

## 5. Direction

Weekly hanya arsip. Runtime refresh wajib harian atau sebelum market open.

## 6. Cheapest Test

Shadow test 7 hari: jalankan exporter harian, bandingkan ID/timestamp USD HIGH terhadap MQL5 `CalendarValueLast change_id`. Catat missed/rescheduled events.

## 7. Entry Criteria / Kill Switch

Weekly-only ditolak jika ada satu pun USD HIGH event yang terlewat atau rescheduled. Tidak ada public release dari `data/calendar_snapshot.json`.

## 8. Explicit Non-Authorization

File ini bukan persetujuan untuk menjadikan weekly-only sebagai satu-satunya news gate.
