# Verification Guide

## Purpose

This document records reproducible engineering verification only. It is not a performance claim. See `DISCLAIMER.md`.

## Pinned Toolchain

- Python `>=3.12`, managed with `uv`
- Rust stable with `maturin`
- Go `1.22+`
- Windows DTAPI-capable runtime for secret bootstrap only

## Exact Commands

```powershell
uv sync --frozen --all-groups
uv run maturin develop --locked --manifest-path engine/analysis_engine/rust/Cargo.toml
uv run pytest tests/ -q
uv run ruff check .
uv run pyright
uv run python scripts/verify_ecosystem.py --safety
cargo test --locked --manifest-path engine/analysis_engine/rust/Cargo.toml --all
cd engine/watchdog && go test ./... -count=1 && go vet ./... && cd ../..
uv run python scripts/verify_runtime_readiness.py --out "$env:TEMP\aeterna-readiness.md"
```

## Expected Outputs

| Check | Expected |
| :--- | :--- |
| Python tests | `354 passed` at tag baseline `v0.1.0` |
| Ruff | `All checks passed!` |
| Pyright | `0 errors, 0 warnings, 0 informations` |
| Go watchdog | `ok aeterna-watchdog` |
| Runtime readiness | `AUTO_READINESS_PASS` with no fabricated drawdown |
| MQL5 exporter | MetaEditor compile: `0 errors, 0 warnings` |

Exact counts may increase after the tagged baseline. A decrease is a regression unless documented in `CHANGELOG.md`.

## Gate Map

| Gate | Status at `v0.1.0` | Evidence |
| :--- | :--- | :--- |
| `GATE-RUNTIME-LOOP-B` | PASSED | deterministic M15 closed-bar tests |
| `GATE-RUNTIME-VIRTUAL-TRACKER` | PASSED | 5-layer virtual exit tests |
| `GATE-NEWS-CALENDAR` | PASSED | source-contract + UTC golden tests |
| `GATE-E2E-RUNTIME` | PASSED | runtime bootstrap E2E |
| `GATE-M4` | PASSED | human-approved audit report, commit `3561b95` |
| `GATE-M5` | PENDING | demo SL/TP evidence required |
| `GATE-VIRTUAL-JOURNAL` | QUEUED | 50–100 internal samples required |

## Determinism and Seeds

- No random market data is generated for financial golden tests.
- Monte Carlo tests use fixed seeds and reproducibility assertions.
- Normalization is window-local with `max(timestamp(X)) < timestamp(y)`.

## Known Unverified Items

- Live P1 observation publication with fresh market data.
- M5 demo execution with server-side SL/TP and partial close.
- 50–100 Virtual Journal samples.
- Exness/Kronos redistribution rights for any future data or weight artifact.

## Reproduce a Tag

```powershell
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
git checkout v0.1.0
git verify-tag v0.1.0
```

Then run the exact commands above. Record UTC timestamp, tag, commit SHA, command, exit code, and artifact SHA256 in your own evidence log.

## Evidence and History

See `docs/aeterna/VERIFIED_TRACKRECORD.md` for the curated engineering evidence index. Internal handoff artifacts are not part of public releases.
