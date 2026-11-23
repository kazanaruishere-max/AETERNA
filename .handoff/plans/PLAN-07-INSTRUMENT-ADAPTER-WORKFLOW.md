# PLAN-07 — Instrument Adapter Workflow (Workflow-Only)

- `plan_id`: PLAN-07
- `created_utc`: 2026-11-22
- `status`: ACCEPTED_AS_WORKFLOW_ONLY
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-architect` + `aeterna-strategy` + `aeterna-ingestion` + `aeterna-risk`
- `evidence_status`: ARCHITECTURAL_WORKFLOW / NO_NEW_CLAIMS
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Premise

Bangun **workflow onboarding instrumen** dulu — bukan software multi-instrumen, bukan adapter baru, bukan strategi baru — supaya XAUUSD tidak terkunci permanen di core engine.

## 2. Current Facts

- Core runtime masih banyak default `XAUUSDm`: `engine/main.py:176,256`, `engine/runtime/bootstrap.py:282`, `engine/runtime/loop_a.py:38`, `engine/runtime/runtime_service.py:35`, `engine/runtime/virtual_tracker.py:49`, `engine/runtime/loop_b.py:61`, `engine/execution/emergency_handler.py:51`.
- Sizing default `contract_size=100.0` di `engine/risk_gate/sizing.py:43`; config XAUUSD `contract_size: 100` di `instruments/xauusd/config/parameters.yaml:8`.
- Pip/XAUUSD assumptions tertanam di `engine/ingestion/python/exness_client.py:206`.
- UI/telegram masih hardcoded: `engine/runtime/chart_snapshot.py:29,250,253`, `engine/runtime/dashboard.py:40`, `engine/telegram_bot/templates.py:144,177`, `engine/telegram_bot/client.py:608`.
- Fase aktif P1 Journal; `GATE-M5` dan `GATE-VIRTUAL-JOURNAL` belum lulus.
- Existing `AETERNA-EXPANSION-BACKLOG.md` sudah mencatat multi-asset sebagai ide `DEFERRED`, bukan task aktif.

## 3. The Unknowns

- Field mana yang benar-benar per-instrumen vs invariant global.
- Venue rules per asset class: leverage, margin, stop level, swap/funding, contract roll, corporate action.
- Macro calendar per instrumen; tidak boleh dipakai sebelum `aeterna-research` memberi source.
- Strategi per instrumen: edge tidak bisa ditransfer dari XAUUSD tanpa uji.
- Apakah risk gate tetap global atau per-instrumen. Jawaban yang sah saat ini: **global**.

## 4. Options & Trade-offs

| Opsi | Dampak | Verdict |
| :--- | :--- | :--- |
| Workflow-only adapters + portability audit | Murah, auditabel, tidak menyentuh runtime; menyiapkan jalur ekspansi. | PILIH |
| Implement EURUSD / commodity adapter sekarang | Menguji workflow lebih nyata, tapi menambah surface area sebelum P1 selesai. | TIDAK SEKARANG |
| Build public software / multi-asset dashboard sekarang | Produk belum punya sampel, legal review, dan gate. | TOLAK |

## 5. Direction

Bangun workflow dulu. Satu core pipeline, banyak adapter. Jangan membuat engine kembar per instrumen.

Hierarchy kanonik:

```text
AssetClass
  -> Instrument
    -> Venue
      -> AdapterConfig
        -> MacroCalendar
          -> StrategyFamily
            -> RiskProfile
              -> Journal
                -> Audit
```

"Satu faktor" yang dimaksud: **satu core invariant + satu risk ledger**. Instrumen dipisah sebagai adapter, bukan sebagai mesin baru.

Urutan ekspansi yang direkomendasikan:

```text
XAUUSD (current)
-> FX pairs (closest venue/session mechanics)
-> commodities (contract roll + seasonality)
-> stocks (halts + earnings + borrow)
-> altcoin (24/7 + funding + liquidation + custody)
```

## 6. Cheapest Test

Portability audit + dry-run adapter spec, tanpa kode runtime:

1. Tulis `InstrumentAdapterContract` sebagai doc/schema: identity, venue, contract_size, tick_size, pip_value, session/timezone, rollover/swap, margin rules, macro sources, blackout, strategy family, risk overrides.
2. Isi adapter spec untuk XAUUSD dari file/config yang sudah ada.
3. Isi adapter spec untuk EURUSD hanya dengan field berlabel `[EVIDENCE]` atau `[UNVERIFIED]`; jangan mengarang angka.
4. Scan hardcoded instrument literals di `engine/` dan `instruments/`.
5. Klasifikasi setiap hardcode:
   - `ADAPTER_MOVABLE` → harus pindah ke adapter.
   - `CORE_INVARIANT` → tetap di core dengan alasan.
6. PASS hanya jika tidak ada hardcode `XAUUSD`/`XAUUSDm`/`100 oz`/jam rollover yang **unclassified** di core.

## 7. Weekday / Weekend Cadence

- Senin–Jumat: testing, bug fix, polish, live P1 E2E, 50–100 sample internal.
- Sabtu–Minggu: dokumentasi, workflow, adapter contract, research brief review, plan refinement.
- Weekend tidak boleh menambah runtime code, strategi baru, atau instrumen baru sebelum gate.

## 8. Entry Criteria / Kill Switch

- Stop jika workflow mulai mengubah risk global: `max_concurrent_positions`, `max_trades_per_day`, `risk_per_trade_pct`, daily loss, atau drawdown killswitch.
- Stop jika adapter spec berisi angka venue tanpa sumber.
- Stop jika `aeterna-research` belum memberi brief untuk klaim makro/venue baru.
- Stop jika `GATE-M5` dan `GATE-VIRTUAL-JOURNAL` belum lulus untuk eksekusi adapter apa pun.

## 9. Maturity Assessment — Architect Audit 2026-11-22

Status total: `READY_FOR_CONTRACT_WORK / NOT_READY_FOR_IMPLEMENTATION`. `[EVIDENCE]` dari audit read-only `aeterna-architect` (19 file dibaca; 29 literal XAUUSD terkonfirmasi di `engine/`).

| Asset class | Status | Reason |
| :--- | :--- | :--- |
| XAUUSD | `READY — P1 signal-only` | Satu-satunya yang punya config, strategi, macro, ownership, RTM, dan test. Live tetap `BLOCKED` oleh `GATE-M5`. |
| FX pairs | `NOT_READY` | `contract_size=100.0` masih oz XAUUSD di `engine/risk_gate/sizing.py:43`; belum ada adapter, research brief, RTM, atau test. |
| Commodities | `NOT_READY` | Contract roll, seasonality, dan venue rules belum punya sumber. |
| Stocks | `BLOCKED` | Halts, earnings, borrow, dan corporate action belum dimodelkan. |
| Altcoin | `BLOCKED / REJECTED_FOR_NOW` | 24/7 bertabrakan dengan invariant force-close harian 15 menit sebelum daily break. Memaksanya = pelonggaran invariant. |

Gap yang masih wajib ditutup sebelum branch adapter mana pun:

1. `InstrumentAdapterContract` doc/schema belum ada.
2. Adapter spec XAUUSD + EURUSD berlabel `[EVIDENCE]` / `[UNVERIFIED]` belum ada.
3. Tabel klasifikasi 29 literal `ADAPTER_MOVABLE` vs `CORE_INVARIANT` belum ada.
4. Contract PR belum ada.
5. `system_state` masih singleton `id=1` di `db/schema.sql:104-116`; penamaan `pair` vs `symbol` tidak konsisten.
6. Ownership adapter baru belum ada di `code-ownership.md` / `CODEOWNERS`.
7. REQ ID adapter di `requirements.md` belum ada.
8. Task packet builder-agnostik belum ada (`active_task: null`).
9. Research brief venue/makro non-XAUUSD belum ada.
10. Test kontrak instrumen-kedua belum ada.

## 10. Freeze Policy — Contract, Not XAUUSD Runtime

- **Jangan freeze runtime XAUUSD.** Weekday tetap testing, bug fix, polish, live P1 E2E, dan 50–100 sampel internal.
- **Freeze surface kontrak**, yaitu: `db/schema.sql`, `engine/analysis_engine/python/interfaces.py`, `instruments/xauusd/config/parameters.yaml`, envelope/RTM, 6 angka risk invariant, exit 5 lapis, rollover 15 menit, zero-LLM, dan satu global risk ledger.
- Artinya: agent yang mengerjakan adapter hanya boleh mengisi adapter di atas kontrak yang sudah dikunci.
- Fokus aktif tetap XAUUSD. Pairs/commodities/stocks/altcoin hanya boleh berupa spec docs dan research brief.

## 11. Branch Strategy

```text
1. feat/m7-instrument-adapter-contract
   → kunci kontrak + portability audit + minimal hard-import cleanup
     dengan characterization test

2. docs/plan-07-adapter-eurusd-spec
   → spec-only, berlabel bukti, tanpa runtime code

3. feat/m7-adapter-eurusd
   → hanya setelah GATE-M5 + GATE-VIRTUAL-JOURNAL PASSED
```

Dilarang membuat branch `feat/xauusd-*` terpisah. XAUUSD tetap trunk/core. Bridge / Kafka / ZeroMQ untuk MVP ditolak; SQLite WAL + polling sudah memadai untuk M15–H4.

## 12. Build From Zero vs Branch

| Opsi | Verdict | Alasan |
| :--- | :--- | :--- |
| Build from zero | `REJECT` | Duplikasi pipeline P1 terverifikasi, audit surface dua kali, risiko risk ledger ganda. |
| Branch adapter sekarang | `BLOCKED` | 29 hardcode + schema singleton menambah coupling baru. |
| Contract-first hardening → adapter tipis | `ADOPT` | Satu titik kegagalan terukur: portability audit. |

## 13. README Adequacy

README saat ini **tidak cukup** sebagai kontrak lintas-aset. `[EVIDENCE]`: `README.md:24` menyatakan purpose-built untuk spot gold; diagram memakai FRED US TIPS/DXY, OANDA retail skew, 512 H4 gold candles; directory map hanya `instruments/xauusd/`.

Rekomendasi: jangan membengkakkan README. Buat satu file kontrak terkunci, lalu README cukup pointer satu paragraf. Config loader generik dan adapter generator ditunda sampai adapter kedua lulus gate.

## 14. Recorded Operator Questions & Answers

| Pertanyaan operator | Jawaban resmi |
| :--- | :--- |
| Apakah rencana ekspansi sudah matang? | Belum. Baru matang untuk contract work, bukan implementasi. |
| Apakah workflow sudah solid? | Solid sebagai arah, belum sebagai kontrak eksekusi. |
| Apakah XAUUSD harus dikunci? | Ya, kontraknya. Bukan runtime XAUUSD-nya. |
| Bangun dari 0 atau buka cabang? | Keduanya ditunda. Contract-first dulu, lalu adapter tipis. |
| Apakah README sudah cocok untuk lintas-aset? | Tidak. README kuat untuk XAUUSD, tapi bukan asset-agnostic contract. |
| Apakah kita fokus XAUUSD dulu? | Ya. Adapter lain hanya docs/research sampai gate P1 selesai. |

## 15. Proposed ADR — Pending Operator Approval

- `ADR-001`: Freeze kontrak, bukan XAUUSD runtime.
- `ADR-002`: Satu core + adapter tipis; engine per aset ditolak.
- `ADR-003`: Tolak broker antrian berat (Kafka/ZeroMQ) untuk MVP; SQLite WAL + polling mencukupi.

## 16. Refined Cheapest Test

PASS hanya jika:

1. Spec XAUUSD diisi dari config existing.
2. Spec EURUSD hanya berisi `[EVIDENCE]` atau `[UNVERIFIED]`.
3. Semua 29 literal diklasifikasikan `ADAPTER_MOVABLE` atau `CORE_INVARIANT`.
4. Nol literal `XAUUSD` / `XAUUSDm` / `100 oz` / jam rollover yang `unclassified` di `engine/`.
5. Adapter FX tidak mensyaratkan perubahan risk global, 1 posisi, atau force-close harian.

Jika syarat 5 gagal → `REJECT`, bukan perbaikan invariant.

## 17. Explicit Non-Authorization

File ini bukan task packet, bukan ADR final, bukan izin multi-instrumen live, bukan izin software publik, dan bukan klaim bahwa strategi XAUUSD transferable ke aset lain. Plan ini hanya menyiapkan draft kontrak dan mengunci fokus XAUUSD.
