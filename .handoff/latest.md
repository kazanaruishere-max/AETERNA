# HANDOFF 2026-11-22 — PLAN SELECTION (P1 JOURNAL)

## 1. Snapshot
- Milestone: P1 Journal; M5 prereq not passed
- Active branch: `main`
- Latest commit: `a6acf3b docs: split beta dev and release repository roles`
- Rigor Tier: C
- Phase/mode: `SIGNAL_ONLY`, `LIVE_ORDER=DISABLED`
- Repo boundary: `AETERNA` = beta development source of truth; `OpenAeterna` = release/public artifact.
- Active task: none (`active_task: null`). No builder may edit code until an OMP task packet is issued.

## 2. Gate Ledger
- `GATE-M4`: PASSED — `.handoff/audits/GATE-M4-AUDIT-REPORT-2026-11-21.md`, operator approval 2026-11-21.
- `GATE-M5`: PENDING_HUMAN_AUDIT — no demo SL/TP server-side proof yet.
- `GATE-VIRTUAL-JOURNAL`: QUEUED — 0 internal samples collected.
- `GATE-P1-E2E-OBSERVER_WRITE` / `GATE-P1-E2E-PUBLISHER_ADMIN` / `GATE-P1-E2E-SPREAD_ZSCORE`: CODE_PASS_LIVE_BLOCKED — need fresh market tick.
- `GATE-PROD-NEWS-SNAPSHOT`: SNAPSHOT_ACTIVE_WEB_ADAPTER — `scripts/export_calendar_snapshot.py` produced 9 USD HIGH events; runtime logged `NEWS_SOURCE=MQL5_SNAPSHOT event_count=9`.
- Evidence commands already run: `uv run pytest tests/ -q -> 354 passed`; `uv run ruff check . -> clean`; `uv run pyright -> 0 errors`; `git diff --check -> clean` (before docs-only `a6acf3b`).
- Latest command: `git log -1 --oneline -> a6acf3b docs: split beta dev and release repository roles`.

## 3. Decision Log
- DECISION-2026-11-22-PLAN-FILTER: six operator proposals filtered by invariant fit, evidence status, and phase readiness. Result: 3 accepted with guards, 2 deferred/conditional, 1 rejected for now.
- DECISION-2026-11-22-EVIDENCE: `aeterna-research` brief 2026-11-22 — PSAR verdict `TEST_FIRST`; Exness/MQL5 rule facts `ADOPT`; weekly-as-official-cadence `REJECT`.
- DECISION-2026-11-22-BOUNDARY: development plans belong in `AETERNA`; release artifacts remain in `OpenAeterna`.

## 4. Active OMP Tasks
- None. `active_task: null`, `allowed_paths: []`.

## 5. Plan Ledger

| ID | Operator proposal | Decision | Entry criteria | Owner | Gate / kill switch |
| --- | --- | --- | --- | --- | --- |
| PLAN-01 | EA Parabolic SAR scalping cepat | DEFERRED_CANDIDATE | Pre-register one fixed PSAR parameter set; fill at next completed bar open; haircut with observed spread; fail if net <= 0, median edge <= median spread, or sign flips when news windows removed; holdout required. | `aeterna-strategy` + `aeterna-backtest` | `GATE-PSAR-FALSIFICATION` not created until test script exists. No EA before PASS. |
| PLAN-02 | Monthly maintenance check | ACCEPTED_WITH_GUARD | Dry-run checklist only: pytest, ruff, pyright, golden tests, go test, kill-criteria query, report file. No auto-fix, no auto-merge, no frozen-parameter change during sample collection. | `aeterna-verifier` | Stop if `instruments/xauusd/config/parameters.yaml` changes during 50-100 sample window. |
| PLAN-03 | Kubernetes / Docker preparation | REJECTED_FOR_NOW | Reopen only if multi-host / multi-broker deployment or non-Windows runtime becomes a hard requirement. | `aeterna-architect` (later) | Never touch 9router port 20128. No Dockerfile/k8s now. |
| PLAN-04 | News JSON fetched once per week | ACCEPTED_AS_ARCHIVE_ONLY | Weekly snapshot may be archive; runtime refresh must be daily or pre-market-open. Shadow-compare against MQL5 `CalendarValueLast` `change_id` for 7 days before allowing weekly-only. | `aeterna-ingestion` | Reject weekly-only if any USD HIGH event is missed/rescheduled. |
| PLAN-05 | Floating / spike / leverage / margin | ACCEPTED_PHASED_DEFENSE | Phase A: replay stored candles + `news_telemetry`, assert PAUSED before HMR and sizing 50%/0%. Phase B: add read-only equity/margin telemetry and projected margin-level gate. Never raise leverage as a fix. | `aeterna-risk` | Block if projected margin level uses an uncited number or requires order placement. |
| PLAN-06 | Beta demo + auto-detect user forward-test win/loss | CONDITIONAL_INTERNAL_ONLY | P1/P2 whitelist only; explicit per-user opt-in with revocation; minimal fields (`outcome_label`, `r_multiple`, `invalidated`); no lot/equity/ticket/server/account ID; no public performance claims; written OJK/Bappebti counsel before external demo. | `aeterna-lead` + `aeterna-security` + human counsel | LEGAL_BLOCKED until counsel opinion stored. External demo STOP if missing. |

## 6. Execution Order
1. Live P1 E2E at market open — existing gate, not a new plan.
2. PLAN-02 monthly maintenance checklist.
3. PLAN-04 news refresh discipline.
4. PLAN-05 margin/spike defense telemetry.
5. PLAN-01 PSAR falsification.
6. PLAN-06 conditional telemetry, only after legal/security clearance.
- PLAN-03 stays out of scope.

## 7. Critical Risks (P0/P1) & Detection
- P1: PSAR built before falsification | Deteksi: no pre-registered test script / no spread haircut assert.
- P1: Monthly maintenance mutates frozen parameters | Deteksi: `git diff instruments/xauusd/config/parameters.yaml` during sample window.
- P1: Weekly-only calendar misses rescheduled HMR | Deteksi: shadow diff vs MQL5 `CalendarValueLast`.
- P1: Leverage treated as margin fix | Deteksi: any design raising leverage without Exness rule citation.
- P1: External demo classified as regulated activity | Deteksi: written counsel opinion absent.
- P1: Telemetry leaks lot/equity/ticket | Deteksi: verifier content scan on report output.
- P0: 9router port 20128 touched | Deteksi: `verify_ecosystem.py` kill-violation scan.

## 8. Next 3 Actions
1. [ ] Operator + `aeterna-lead`: wait market open, run `uv run python -m engine.main`, confirm `bar_cursors > 0`, `signal_observations > 0`, and Telegram admin `OBSERVATION — XAUUSDm`. Entry: fresh tick; no new code.
2. [ ] `aeterna-lead`: issue OMP task packet for PLAN-02 checklist after operator approval. Entry: `active_task` assigned; allowed paths restricted to docs/scripts; no auto-fix.
3. [ ] `aeterna-lead`: commission read-only PSAR falsification brief and OJK/Bappebti question list. Entry: no code, no account access, no public claim.

## 9. Handoff Notes
- Do not commit these plan notes unless operator explicitly requests commit/push.
- Do not push plans to `OpenAeterna`; plans are development context for `AETERNA`.
- Previous history remains in `.handoff/2026-11-21.md`.

## 10. Plan Files
- Register: `.handoff/plans/PLAN-REGISTER-2026-11-22.md`
- `.handoff/plans/PLAN-01-PSAR-SCALPING.md`
- `.handoff/plans/PLAN-02-MONTHLY-MAINTENANCE.md`
- `.handoff/plans/PLAN-03-KUBERNETES-DOCKER.md`
- `.handoff/plans/PLAN-04-WEEKLY-NEWS-SNAPSHOT.md`
- `.handoff/plans/PLAN-05-MARGIN-SPIKE-DEFENSE.md`
- `.handoff/plans/PLAN-06-USER-FORWARD-TELEMETRY.md`
- `.handoff/plans/PLAN-07-INSTRUMENT-ADAPTER-WORKFLOW.md`

## 11. PLAN-07 INSTRUMENT ADAPTER WORKFLOW
- Decision: ACCEPTED_AS_WORKFLOW_ONLY.
- Weekday: testing, bug fix, polish, live P1 E2E, 50–100 internal samples.
- Weekend: docs, adapter contract, portability audit, research brief review only.
- Direction: one core engine + many instrument adapters; global risk ledger unchanged.
- Hierarchy: AssetClass -> Instrument -> Venue -> AdapterConfig -> MacroCalendar -> StrategyFamily -> RiskProfile -> Journal -> Audit.
- Expansion order: XAUUSD -> FX pairs -> commodities -> stocks -> altcoin.
- Kill switch: no runtime adapter before GATE-M5 + GATE-VIRTUAL-JOURNAL + portability audit; no uncited venue/macro numbers.

## 12. PLAN-07 MATURITY RECORD
- Audit by `aeterna-architect` 2026-11-22: workflow READY_FOR_CONTRACT_WORK, NOT_READY_FOR_IMPLEMENTATION.
- Asset readiness: XAUUSD P1 signal-only READY; FX NOT_READY; commodities NOT_READY; stocks BLOCKED; altcoin BLOCKED/REJECTED_FOR_NOW.
- Freeze policy: freeze contract surface (schema, interfaces, parameters.yaml, risk invariants), NOT XAUUSD runtime. Weekday stays testing/fix/polish.
- Branch order: `feat/m7-instrument-adapter-contract` → `docs/plan-07-adapter-eurusd-spec` → `feat/m7-adapter-eurusd` only after M5 + virtual journal.
- Build-from-zero REJECT; adapter branch now BLOCKED; contract-first thin adapter ADOPT.
- README adequacy: NOT enough as cross-asset contract; needs one locked contract doc + README pointer.
- Operator Q&A recorded in `.handoff/plans/PLAN-07-INSTRUMENT-ADAPTER-WORKFLOW.md §14`.
- Proposed ADR-001..003 pending operator approval in PLAN-07 §15.

## 13. PLAN-08 RESTART GAP REPLAY
- Status: PROPOSED_NOT_APPROVED, design-only.
- Problem: restart resumes at current bar; missed M15 bars are not replayed.
- Proposed: gap detection at startup, sequential replay oldest→newest, cursor advances only after success.
- Critical constraint: phase 1 is `STRATEGY_ONLY`; live state machine cannot be reconstructed from current telemetry. No false live-equivalent claim.
- Schema additions require Contract PR: `replay_runs`, `origin` columns, `config_hash`.
- Replay observations must not count as live sample and must not trigger public/live alerts.
- Open decision: `RESTART_REPLAY_MAX_BARS` and whether live starts if replay is BLOCKED.
- File: `.handoff/plans/PLAN-08-RESTART-GAP-REPLAY.md`.

## 14. PLAN-08 PROMPTS
- Contract prompt (execute first): `.handoff/tasks/TASK-M7-RESTART-GAP-REPLAY-CONTRACT.md`
- Implementation prompt (BLOCKED): `.handoff/tasks/TASK-M7-RESTART-GAP-REPLAY-IMPLEMENT.md`
- Contract prompt scope: docs only; no schema/runtime change; stop after PR.
- Implementation prompt requires contract merge + `REQ-RUNTIME-011` approval + active task packet.
- `RESTART_REPLAY_MAX_BARS` remains an operator decision.
