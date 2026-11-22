# AETERNA Beta Changelog

This file records beta-facing updates for the public `OpenAeterna` release. Development continues in GitHub `AETERNA`; this file is the beta-facing mirror and must not include secrets, broker identifiers, equity, tickets, lot sizes, PnL, or performance claims.

## Release Model

- Development source of truth: `github.com/kazanaruishere-max/AETERNA`
- Beta/public artifact: `github.com/kazanaruishere-max/OpenAeterna`
- Rule: normal development updates go to `AETERNA` only. `OpenAeterna` is updated only for official beta tags.
- Verification language: "verified" means deterministic tests, invariant checks, and engineering gates — never profitability.

## [beta/v0.1.0] - 2026-11-21

### Added

- Initial clean public source tree under AGPL-3.0-only.
- Public documentation set: `README.md`, `README.id.md`, `SECURITY.md`, `DISCLAIMER.md`, `THIRD_PARTY_NOTICES.md`, `VERIFY.md`, `CHANGELOG.md`.
- Verified engineering track record with gate status and exact commands.
- CI for multi-stack verification, CodeQL SAST, secret scanning, and tag-triggered release workflow.
- Deterministic runtime foundation:
  - Loop A/B tri-loop runtime
  - Virtual Signal Tracker
  - SQLite WAL schema and repositories
  - News source contract and UTC golden tests
  - Chart snapshot and admin-only observation publication
  - Readiness harness
- M5 prerequisite wiring:
  - `PositionManager` `bar_closed` path
  - Production calendar snapshot path
  - Credential source logging

### Changed

- Emergency killswitch hardened to lockfile-first fail-closed behavior.
- Fabricated drawdown payload rejected when equity is unavailable.
- MQL5 exporter fixed to use the filtered currency value instead of an invalid field.
- CodeQL Go configured with an explicit watchdog build.
- Autonomous builder contract made CLI-agnostic.

### Security

- Secret and forbidden-path checks added to the public release workflow.
- Internal handoff artifacts, runtime databases, logs, reports, and credentials excluded from public archives.
- No account IDs, broker server names, tokens, tickets, equity, or PnL included in the public release.

### Verification

- `GATE-M4` PASSED by human operator at development commit `3561b95`.
- Full Python suite: 354 tests passing at baseline.
- Go watchdog, Ruff, Pyright, and `git diff --check` clean.
- CodeQL Go and Python success after explicit Go build fix.
- Public release workflow created, verified on tag `v0.1.0`.

### Known Beta Limitations

- `GATE-M5` demo execution proof still pending.
- `GATE-VIRTUAL-JOURNAL` 50–100 sample target still queued.
- Beta is signal-only/admin-only; no public/VIP signal distribution.
- No verified forward-test performance is claimed.

## Beta Update Template

Use this template for every new beta tag:

```markdown
## [beta/vX.Y.Z] - YYYY-MM-DD

### Added
-

### Changed
-

### Fixed
-

### Security
-

### Verification
- command -> result
- gate status

### Known Limitations
-
```

## Non-Claims

No PnL, return, Sharpe, win rate, lot size, equity, ticket, broker server, or account identifier is published here. Trading performance claims are outside the scope of this changelog.
