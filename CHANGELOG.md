# Changelog

All notable changes are documented here. Format follows Keep a Changelog. Entries cite engineering gates and commits; no PnL, equity, tickets, or performance claims are included.

This is the **AETERNA beta development changelog**. Public release notes are tracked separately in `docs/aeterna/BETA_CHANGELOG.md` and published through `OpenAeterna` only for official release tags.

## [Unreleased]

### Added

- Public-release documentation set: `SECURITY.md`, `DISCLAIMER.md`, `THIRD_PARTY_NOTICES.md`, `VERIFY.md`, verified track record, and public README files.
- AGPL-3.0-only release licensing and `.gitattributes` export hygiene.
- Public tag release workflow draft with forbidden-path checks and source archive generation.
- Autonomous builder contract (`AUTONOMOUS_BUILDER.md`) and CLI-agnostic task packet template supporting Claude Code, Codex CLI, OpenCode, Antigravity CLI, and other agents.
- `CLAUDE.md` entrypoint and skill fallback policy for non-OpenCode builders.
- `scripts/export_calendar_snapshot.py` using MQL5 web calendar content endpoint.
- Beta changelog at `docs/aeterna/BETA_CHANGELOG.md`.

### Changed

- `.env.example` placeholders replace any live-looking values.
- CodeQL Go uses an explicit watchdog build with Go installed before CodeQL init.
- Dependabot allows patch security updates.
- Repository boundary pinned: `AETERNA` is beta development source of truth; `OpenAeterna` is release/public artifact.
- `README.md` and `README.id.md` restored as detailed beta development READMEs; `OpenAeterna` keeps a concise release-safe README.

### Security

- Release process now blocks secrets, runtime databases, logs, broker reports, and internal handoff artifacts from source archives.
- Skill frontmatter license changed from `Proprietary` to `AGPL-3.0-only` for public release consistency.

## [0.1.0] - 2026-11-21

### Added

- Runtime tri-loop architecture, virtual tracker, SQLite WAL schema, news source contract, chart snapshot renderer, admin-only publisher, readiness harness.
- PositionManager `bar_closed` wiring for M5 prerequisite (`TASK-RUNTIME-22`).
- Production news snapshot path and credential-source logging (`TASK-RUNTIME-23`).

### Changed

- Emergency killswitch hardened to lockfile-first fail-closed behavior.
- Drawdown payload rejects `UNAVAILABLE` equity with fabricated values.
- MQL5 exporter fixed to use `InpCurrency` instead of an invalid MQL5 field.

### Fixed

- Multiple financial-safety defects found in M4 pre-audit were closed before human approval.
- Stale audit references and code-ownership gap corrected.

### Verification

- `GATE-M4` PASSED by human operator at commit `3561b95`.
- 354 full Python tests passing at baseline.
- 27 news tests passing after exporter source fix.
- Go watchdog, Ruff, Pyright, and `git diff --check` clean.

[Unreleased]: https://github.com/kazanaruishere-max/AETERNA/compare/3561b95...HEAD
[0.1.0]: https://github.com/kazanaruishere-max/AETERNA/releases/tag/v0.1.0
[OpenAeterna release]: https://github.com/kazanaruishere-max/OpenAeterna/releases
