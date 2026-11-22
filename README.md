# AETERNA Quant

[![License: AGPL-3.0-only](https://img.shields.io/badge/License-AGPL--3.0--only-blue.svg)](LICENSE)
[![Status: P1 Journal](https://img.shields.io/badge/Status-P1%20Journal-yellow.svg)](docs/aeterna/VERIFIED_TRACKRECORD.md)
[![Mode: SIGNAL_ONLY](https://img.shields.io/badge/Mode-SIGNAL__ONLY-blue.svg)](VERIFY.md)

AETERNA Quant is an experimental, deterministic research engine for XAUUSD. It combines a multi-timeframe runtime, online spread/news state machine, virtual journal, independent Go risk watchdog, and an admin-only Telegram control surface.

> This is research software, not financial advice and not a trading signal service. See [DISCLAIMER.md](DISCLAIMER.md).

## Status

- Phase: `P1 Journal`
- Runtime mode: `SIGNAL_ONLY`, `LIVE_ORDER=DISABLED`
- Gate: `GATE-M4 PASSED`
- Pending: `GATE-M5`, `GATE-VIRTUAL-JOURNAL`
- No performance claims are made. "Verified" means deterministic tests and engineering gates, not profitability.

See the [Verified Track Record](docs/aeterna/VERIFIED_TRACKRECORD.md).

## Architecture

- **Python 3.12+**: tri-loop runtime, strategy adapters, virtual tracker, DPAPI secret isolation, Telegram admin controls.
- **Rust/PyO3**: backtest PnL, slippage modeling, Monte Carlo verification.
- **Go**: independent local watchdog and pre-entry risk gate.
- **SQLite WAL**: canonical schema, bar cursors, signal observations, news telemetry.
- **ONNX Runtime CPU**: deterministic regime inference. No LLM in the production path.

## Quick Start

```powershell
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
uv sync --frozen --all-groups
uv run maturin develop --locked --manifest-path engine/analysis_engine/rust/Cargo.toml
```

Build the Go watchdog from `engine/watchdog`. Broker credentials are supplied locally via `scripts/setup_secrets.py`; no credentials are included in this repository.

## Verification

Exact commands, expected outputs, gate mapping, and known unverified items are in [VERIFY.md](VERIFY.md).

## Data and Reproducibility

No broker database, tick export, live log, broker report, account identifier, or unlicensed model weight is published. Reproduce results from your own data sources and compare structural invariants, not PnL.

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately via the repository Security tab.

## Legal

- Source: [AGPL-3.0-only](LICENSE)
- [DISCLAIMER.md](DISCLAIMER.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [CHANGELOG.md](CHANGELOG.md)

## Non-Goals

- No public/VIP signal broadcasting in this release.
- No autonomous live order placement by AI agents.
- No investment, legal, or tax advice.
- No unverifiable performance or profitability claims.
