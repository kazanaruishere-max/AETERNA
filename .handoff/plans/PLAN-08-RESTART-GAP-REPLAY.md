# PLAN-08 — Automatic Restart Gap Detection & Replay

- `plan_id`: PLAN-08
- `created_utc`: 2026-11-23
- `status`: PROPOSED_NOT_APPROVED
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-architect` + `aeterna-verifier` + `aeterna-risk` + human operator
- `evidence_status`: ARCHITECTURAL_DESIGN / NO_RUNTIME_CHANGE
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Problem

Saat engine berhenti, `bar_cursors` menyimpan bar terakhir yang dievaluasi. Saat restart, Loop A menginisialisasi `last_bar_m15_ts` dari bar saat ini, lalu Loop B hanya mengevaluasi **satu bar close berikutnya**. Bar M15 yang terlewat selama downtime tidak dievaluasi ulang.

Bukti kode:

- `engine/runtime/loop_a.py:113-119` — `last_bar_m15_ts` diinisialisasi dari tick pertama.
- `engine/runtime/loop_b.py:131-163` — hanya `closed_bar_ts` saat event M15, tanpa loop backfill.
- `engine/runtime/loop_b.py:337-351` — cursor anti-duplikasi sudah ada, tapi hanya untuk satu bar.
- `db/schema.sql:121-127` — `bar_cursors` hanya menyimpan `last_closed_bar_ts`.

Contoh nyata 2026-11-23:

```text
last cursor before stop : 04:15 UTC
last tick before stop   : 04:43:55 UTC
restart                 : 05:26:48 UTC
missed M15 bars         : 04:30, 04:45, 05:00
```

## 2. Goal

Pada startup, engine mendeteksi gap dan mereplay bar M15 yang terlewat secara otomatis, berurutan, idempoten, dan auditabel — tanpa mengubah data live atau mengirim alert palsu.

## 3. Non-Goals

- Tidak mengirim order.
- Tidak mengubah strategi atau parameter saat replay.
- Tidak menghitung replay sebagai sampel live.
- Tidak melakukan backtest seluruh sejarah.
- Tidak mengubah `system_state` live dengan state historis.
- Tidak menyentuh multi-instrumen; tetap XAUUSD.

## 4. Hard Invariants

- `SIGNAL_ONLY`, `LIVE_ORDER=DISABLED`.
- Zero LLM di jalur runtime.
- Tidak ada `order_send`, `PositionModify`, `gh pr merge`.
- Do not kill 9router port `20128`.
- Replay harus zero lookahead: M15 hanya sampai `bar_ts`; H4 hanya candle yang sudah close pada `bar_ts`.
- Satu bar M15 dievaluasi maksimal sekali per `(symbol, timeframe, bar_ts, strategy_id)`.
- Replay tidak boleh menulis ke `signal_observations` sebagai `LIVE`.

## 5. Proposed Architecture

```text
Startup
  -> DB init
  -> read bar_cursor + last known state
  -> compute current_closed_bar_ts
  -> detect gap
  -> if gap:
       create replay_run (PENDING)
       replay oldest -> newest
       write REPLAY observations/blocked audit
       advance cursor only after successful bar
       write summary
     else:
       skip
  -> start Loop A / Loop B live
```

Replay berjalan **sebelum** Loop B live menyala. Loop A boleh menyala untuk memanaskan tick/state, tetapi Loop B live harus ditahan sampai replay selesai atau `REPLAY_BLOCKED`.

## 6. Data Model Additions — Requires Contract PR

Tabel baru:

```sql
CREATE TABLE replay_runs (
    replay_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    last_cursor_ts INTEGER NOT NULL,
    first_missed_bar_ts INTEGER NOT NULL,
    last_missed_bar_ts INTEGER NOT NULL,
    missed_count INTEGER NOT NULL,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    status TEXT NOT NULL CHECK (status IN ('PENDING','RUNNING','COMPLETED','BLOCKED','INTERRUPTED')),
    replay_mode TEXT NOT NULL CHECK (replay_mode IN ('STRATEGY_ONLY','NEWS_BLOCK_ONLY')),
    config_hash TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    observations_created INTEGER NOT NULL DEFAULT 0,
    blocked_created INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
) STRICT;
```

Kolom baru:

```text
signal_observations.origin     TEXT NOT NULL DEFAULT 'LIVE' CHECK (origin IN ('LIVE','REPLAY'))
signal_observations.replay_id  TEXT
blocked_signals.origin         TEXT NOT NULL DEFAULT 'LIVE' CHECK (origin IN ('LIVE','REPLAY'))
blocked_signals.replay_id      TEXT
bar_cursors.config_hash        TEXT
```

Aturan query:

```text
Live sample:  WHERE origin='LIVE'
Replay audit: WHERE origin='REPLAY'
```

Replay observations **tidak boleh** masuk hitungan 50–100 sampel live tanpa keputusan operator baru.

## 7. Gap Detection Formula

```python
M15 = 900
current_closed = (floor(now_utc / M15) * M15) - M15
last_cursor = db.get_bar_cursor(symbol, "M15")

if last_cursor is None:
    status = "NO_BASELINE"   # jangan replay buta
elif current_closed <= last_cursor.last_closed_bar_ts:
    status = "NO_GAP"
else:
    first_missed = last_cursor.last_closed_bar_ts + M15
    last_missed = current_closed
    missed_count = ((last_missed - first_missed) // M15) + 1
```

Contoh restart `05:26:48 UTC`:

```text
current_closed = 05:00 UTC
last_cursor    = 04:15 UTC
first_missed   = 04:30 UTC
last_missed    = 05:00 UTC
missed_count   = 3
```

Bar `05:15` belum close saat restart, jadi bukan bagian replay; nanti ditangani Loop B live pada `05:30`.

## 8. Replay Algorithm

1. Startup mencatat `restart_at_utc` dan `last_tick_utc` dari `system_state`.
2. Hitung gap dengan formula §7.
3. Jika `NO_BASELINE` atau `NO_GAP`, lanjut live.
4. Jika `missed_count > max_replay_bars`, set `GAP_TOO_LARGE`, jangan advance cursor, jangan mulai Loop B live.
5. Jika config hash berbeda dari cursor checkpoint, set `CONFIG_DRIFT`, jangan replay, minta operator.
6. Untuk setiap `bar_ts` dari `first_missed` sampai `last_missed`:
   - Cek `_is_processed(bar_ts)`; skip jika sudah.
   - Fetch context dengan cutoff `bar_ts` (M15) dan H4 cutoff yang sudah close.
   - Jalankan regime inference pada historical context.
   - Jalankan strategy evaluation dalam replay mode.
   - Insert `origin='REPLAY'`, `replay_id`.
   - Insert blocked audit dengan `origin='REPLAY'` bila kena gate.
   - Advance cursor **hanya setelah bar sukses**.
7. Jika satu bar gagal: status `BLOCKED`/`INTERRUPTED`, cursor berhenti di bar sukses terakhir, Loop B live tidak mulai.
8. Setelah selesai: status `COMPLETED`, kirim satu ringkasan admin Telegram.
9. Baru mulai Loop B live.

## 9. Historical State Problem

Ini bagian paling kritis. `run_once()` saat ini memakai `state_machine.state` **live** (`loop_b.py:258-265`). State spread historis per M15 tidak tersimpan lengkap; `news_telemetry` hanya menyimpan peak/max, bukan seluruh deret spread.

Maka replay tidak boleh mengklaim ekuivalen dengan live.

Keputusan desain:

```text
Replay mode phase 1 = STRATEGY_ONLY
- regime + strategy dievaluasi dari candle historis
- state machine live TIDAK dipakai
- observation ditandai origin=REPLAY
- tidak dikirim sebagai OBSERVATION live
- tidak dihitung sebagai sampel live
```

Mode `FULL_STATE_REPLAY` ditolak untuk sekarang karena butuh telemetry per-bar yang belum ada. Jika operator ingin full state replay, itu PLAN baru + schema telemetry baru.

## 10. Crash / Restart / Duplicate Safety

- `signal_observations` sudah punya `UNIQUE(symbol, bar_ts, strategy_id)`; replay idempoten untuk observation.
- `blocked_signals` belum punya unique constraint; perlu migration atau dedupe key di `details`.
- Cursor hanya maju setelah bar sukses; crash mid-replay akan resume dari bar terakhir yang sukses.
- Jika replay run terputus, startup berikutnya membuat `INTERRUPTED` record dan melanjutkan dari cursor.
- Jangan pernah menghapus/menimpa replay history.

## 11. Configuration

Usulan field baru di config runtime (bukan `parameters.yaml` strategi):

```text
RESTART_REPLAY_MODE=auto|off|dry_run
RESTART_REPLAY_MAX_BARS=<operator decision>
RESTART_REPLAY_STATE_MODE=STRATEGY_ONLY
```

`max_replay_bars` **belum ditetapkan**. Ini open decision operator; jangan mengarang default. Jika tidak diisi, engine wajib `BLOCKED`.

## 12. Notifications

Replay tidak boleh mengirim satu pesan per bar. Kirim satu ringkasan admin:

```text
REPLAY SUMMARY — XAUUSDm
gap: 04:43:55Z → 05:26:48Z
missed: 3 bars
replayed: 3
observations: 0
blocked: 0
status: COMPLETED
```

Tidak ada pesan ke channel publik/VIP.

## 13. Acceptance Tests

Wajib ada sebelum implementasi dianggap selesai:

1. `test_no_gap_when_cursor_current`
2. `test_gap_math_exact_three_bars`
3. `test_no_baseline_does_not_replay_blindly`
4. `test_gap_too_large_blocks`
5. `test_config_drift_blocks`
6. `test_replay_oldest_to_newest`
7. `test_replay_idempotent_on_second_restart`
8. `test_crash_mid_replay_resumes_at_last_success`
9. `test_replay_does_not_mutate_live_system_state`
10. `test_replay_marks_origin_replay`
11. `test_replay_does_not_send_live_observation_alert`
12. `test_zero_lookahead_h4_cutoff`
13. `test_missing_candles_blocks_not_skips`
14. `test_blocked_signals_deduped`
15. `test_replay_summary_counts`

Manual drill:

```text
stop after cursor
wait 3 M15 bars
restart
verify 3 replay rows
restart again
verify no duplicates
verify live state untouched
```

## 14. Acceptance Commands

```powershell
uv run pytest tests/runtime/test_restart_replay.py -q
uv run pytest tests/ -q
uv run ruff check .
uv run pyright
git diff --check
```

## 15. Rollout

```text
Phase 0: design + schema contract PR (docs only)
Phase 1: gap detection + dry-run report (no replay)
Phase 2: STRATEGY_ONLY replay + audit tables
Phase 3: crash-resume + Telegram summary
Phase 4: optional FULL_STATE_REPLAY only with new telemetry
```

## 16. Kill Switch

Stop feature if:

- replay mengubah `system_state` live,
- replay menulis `origin=LIVE`,
- replay mengirim alert publik,
- replay memakai data setelah `bar_ts`,
- replay membuat duplicate observations/blocked rows,
- replay berjalan saat `CONFIG_DRIFT` atau `NO_BASELINE`.

## 17. Open Decisions

1. `RESTART_REPLAY_MAX_BARS` — operator harus menetapkan.
2. Apakah replay observations boleh dipakai untuk research statistik? Rekomendasi: boleh, tapi terpisah dari live sample.
3. Apakah engine boleh start live jika replay `BLOCKED`? Rekomendasi: tidak; fail closed.
4. Apakah `blocked_signals` perlu unique constraint baru?
5. Siapa owner implementasi dan gate reviewer?

## 18. Cheapest Falsification Test

Sebelum implementasi:

1. Copy `data/trading.db` ke temp.
2. Jalankan query gap murni terhadap `bar_cursors` + `system_state`.
3. Pastikan 3 bar yang terlewat teridentifikasi.
4. Pastikan candle M15/H4 untuk rentang itu tersedia dari MT5.
5. Jika candle tidak lengkap, workflow replay sudah gagal sebelum kode ditulis.

## 19. Prompt / Task Pointers

- Contract prompt (execute first):
  `.handoff/tasks/TASK-M7-RESTART-GAP-REPLAY-CONTRACT.md`
- Implementation prompt (BLOCKED until contract):
  `.handoff/tasks/TASK-M7-RESTART-GAP-REPLAY-IMPLEMENT.md`

The contract prompt is the only authorized next step. Implementation prompt must remain untouched until contract PR is merged and operator approves `REQ-RUNTIME-011`.

## 20. Explicit Non-Authorization

File ini bukan task packet, bukan ADR final, bukan izin implementasi, dan bukan izin mengubah schema. Semua perubahan schema wajib Contract PR + operator approval.
