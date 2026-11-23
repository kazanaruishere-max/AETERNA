# PLAN REGISTER — 2026-11-22

- `created_utc`: 2026-11-22
- `phase`: P1 Journal
- `canonical_state`: `docs/aeterna/agent-state.md`
- `source_handoff`: `.handoff/2026-11-22.md`
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `scope`: operator proposals filtered by invariant fit, evidence status, and phase readiness

File ini adalah indeks. File plan individual berada di folder yang sama. Tidak ada plan di sini yang boleh diimplementasikan tanpa task packet builder-agnostic terpisah dan gate yang ditentukan.

| ID | File | Status | Owner | Gate / kill switch |
| --- | --- | --- | --- | --- |
| PLAN-01 | `PLAN-01-PSAR-SCALPING.md` | DEFERRED_CANDIDATE | `aeterna-strategy` + `aeterna-backtest` | No EA before falsification PASS |
| PLAN-02 | `PLAN-02-MONTHLY-MAINTENANCE.md` | ACCEPTED_WITH_GUARD | `aeterna-verifier` | No auto-fix; no frozen-param change |
| PLAN-03 | `PLAN-03-KUBERNETES-DOCKER.md` | REJECTED_FOR_NOW | `aeterna-architect` (later) | Reopen only for multi-host/multi-broker |
| PLAN-04 | `PLAN-04-WEEKLY-NEWS-SNAPSHOT.md` | ACCEPTED_AS_ARCHIVE_ONLY | `aeterna-ingestion` | Reject weekly-only on any missed/rescheduled event |
| PLAN-05 | `PLAN-05-MARGIN-SPIKE-DEFENSE.md` | ACCEPTED_PHASED_DEFENSE | `aeterna-risk` | Never raise leverage; no uncited threshold |
| PLAN-06 | `PLAN-06-USER-FORWARD-TELEMETRY.md` | CONDITIONAL_INTERNAL_ONLY | `aeterna-lead` + `aeterna-security` + counsel | LEGAL_BLOCKED before external demo |
| PLAN-07 | `PLAN-07-INSTRUMENT-ADAPTER-WORKFLOW.md` | ACCEPTED_AS_WORKFLOW_ONLY | `aeterna-architect` + `aeterna-strategy` + `aeterna-ingestion` + `aeterna-risk` | XAUUSD focus locked; no runtime adapter before M5 + virtual journal + contract PR + portability audit |
| PLAN-08 | `PLAN-08-RESTART-GAP-REPLAY.md` | PROPOSED_NOT_APPROVED | `aeterna-architect` + `aeterna-verifier` + `aeterna-risk` | Contract PR + replay tests before runtime; no live-state mutation |

## Execution Order

1. Live P1 E2E at market open — existing gate, not a new plan.
2. PLAN-07 instrument adapter workflow — weekend contract spec + portability audit docs only; XAUUSD runtime stays focused, no runtime adapter.
3. PLAN-08 restart gap replay — design first; schema Contract PR + tests before runtime.
4. PLAN-02 monthly maintenance checklist.
5. PLAN-04 news refresh discipline.
6. PLAN-05 margin/spike defense telemetry.
7. PLAN-01 PSAR falsification.
8. PLAN-06 conditional telemetry, after legal/security clearance.
- PLAN-03 stays out of scope.

## Explicit Non-Authorization

File ini bukan task packet, bukan ADR final, bukan persetujuan produksi, bukan izin publikasi, dan bukan izin order live.
