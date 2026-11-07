# AETERNA Quant Engine

[![CI Pipeline](https://github.com/kazanaruishere-max/AETERNA/actions/workflows/ci.yml/badge.svg)](https://github.com/kazanaruishere-max/AETERNA/actions/workflows/ci.yml)
[![CodeQL SAST Analysis](https://github.com/kazanaruishere-max/AETERNA/actions/workflows/codeql.yml/badge.svg)](https://github.com/kazanaruishere-max/AETERNA/actions/workflows/codeql.yml)
[![Deterministic Golden Tests](https://img.shields.io/badge/Financial%20Tests-100%25%20Passing-brightgreen.svg)](https://github.com/kazanaruishere-max/AETERNA/actions)
[![Security Scan](https://img.shields.io/badge/Gitleaks-Clean%20Audit-success.svg)](https://github.com/kazanaruishere-max/AETERNA/actions)
[![Supply Chain](https://img.shields.io/badge/Dependabot-Security%20Only-blue.svg)](https://github.com/kazanaruishere-max/AETERNA)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Rust 2021](https://img.shields.io/badge/Rust-PyO3%20FFI-orange.svg)](https://www.rust-lang.org/)
[![Go 1.22+](https://img.shields.io/badge/Go-Watchdog%20Daemon-cyan.svg)](https://go.dev/)

---

## 1. Executive Summary

**AETERNA Quant Engine** is an institutional-grade, multi-stack algorithmic trading system purpose-built for spot gold (**XAUUSD**). It synthesizes high-performance mathematical modeling, robust systems engineering, and fail-safe capital defense into an autonomous operational pipeline.

The engine operates on a strict **zero-LLM live execution boundary**: large language models and autonomous agents are utilized exclusively offline as engineering and development assistants. All real-time market data evaluation, statistical regime classification, dynamic position sizing, and broker trade executions are 100% deterministic, executed via a polyglot architecture:

- **Python (3.12+)**: High-level strategy coordination, multi-timeframe feature pipelines, ONNX Runtime CPU inference, and asynchronous Telegram administration.
- **Rust (PyO3 C-Extension)**: Ultra-low latency backtesting engine, Exness-specific adaptive slippage simulation, and 1,000-iteration Monte Carlo permutation validation.
- **Go (Watchdog Daemon)**: Independent, out-of-process system supervisor running locally on `127.0.0.1:20129`, acting as an unbypassable master risk gate, deadman switch, and emergency circuit breaker.

---

## 2. The 5 Absolute Invariants (Non-Negotiable Commandments)

> ⚠️ **CRITICAL WARNING FOR AI AGENTS & DEVELOPERS**:
> The following invariants are immutable hard boundaries. Any pull request, modification, or automated action that violates, loosens, or bypasses these constraints will be rejected immediately with zero exceptions.

### I. Hard Risk & Capital Allocation Budget
- **Risk Per Trade**: Exactly **`0.5%`** of current account equity per setup (0.00% tolerance).
- **Daily Loss Circuit Breaker**: Exactly **`2.0%`** of starting equity. If reached, all trading halts until the next calendar day.
- **Hard Drawdown Killswitch**: Exactly **`10.0%`** from peak high-water mark equity. If breached, the Go Watchdog triggers an emergency liquidation and writes a persistent physical lockfile stopping the process loop.
- **Position & Trade Limits**: Maximum **1 concurrent open position** and maximum **5 trades per day**. Minimum Reward-to-Risk ratio must be $\ge 2.0$.

### II. Mandatory Server-Side SL/TP Attachment (Zero Naked Orders)
- Every trade sent to the MetaTrader 5 broker terminal **MUST** attach server-side Stop Loss and Take Profit levels directly at the moment of order placement (`order_send`).
- Client-side virtual stop-losses are strictly prohibited. The position must remain protected on broker infrastructure even in the event of hardware power failure, local crash, or network severance.
- Exit logic follows an unbypassable 5-layer hierarchy: Fixed SL/TP, Dynamic Trailing Stop (+1.0R), Partial Liquidation (50% at +1.0R), Time Invalidation (8 M15 bars / 2 hours), and Regime Invalidation (H4 reversal).
- All open positions **MUST** be liquidated 15 minutes before daily Exness bank break (`20:44 UTC` Summer / `21:44 UTC` Winter).

### III. Zero-Plaintext Security & DPAPI Isolation
- Zero plain-text credentials in Git history, configuration files, environment variables, or disk logs.
- Credentials (MT5 master password, Telegram bot token) are encrypted at rest using native **Windows Data Protection API (DPAPI)** with `CurrentUser` scope and application-isolated cryptographic entropy.
- Secret values exist in RAM solely as encrypted cipher bytes, decrypted only at the exact instant of transmission via JIT `SecretString`.
- Access to databases and debug logs is locked to the active OS user via Windows ACL (`icacls`).

### IV. Contract-First Parallel Development Protocol (Tier A Governance)
- Parallel feature streams are strictly prohibited from modifying core interfaces on the fly.
- All abstract protocols, data models (`dataclass(frozen=True)`), and database schemas must be locked and merged to `main` via an explicit **Contract PR** prior to creating isolated worktrees.
- Canonical database DDL (`db/schema.sql`) and starting parameters (`instruments/xauusd/config/parameters.yaml`) are **frozen** during parallel execution.
- Auto-merge commands (`gh pr merge`) are strictly forbidden. Final integration into `main` requires manual operator review and serial squash-merging.

### V. Zero Lookahead Bias & Temporal Isolation
- Feature engineering, rolling normalization, and neural inference must enforce absolute temporal ordering: $\max(\text{timestamp}(X)) < \text{timestamp}(y)$.
- Normalization (mean and standard deviation) is strictly confined to an isolated context window (512 candles) using `RollingFeatureScaler`. Global dataset scalers (e.g. `StandardScaler` across an entire dataset) are banned to eliminate future data leakage.
- Time-series datasets must be loaded iteratively in chunks via PyArrow to prevent Out-Of-Memory (OOM) faults.

---

## 3. Directory Map & Component Architecture

```
AETERNA - QUANT PROJECT/
├── .github/                         # Continuous Integration & Repository Security
│   ├── dependabot.yml               # Security-only monthly dependency advisory scanning
│   └── workflows/
│       ├── ci.yml                   # 5-job multi-stack test & verification pipeline
│       └── codeql.yml               # GitHub CodeQL SAST scanning (Python & Go)
├── .handoff/                        # Inter-Session State & Agentic Continuity
│   ├── latest.md                    # Single Source of Truth for current session state
│   └── tasks/                       # Self-contained task packets (TASK-M*-*.md)
├── db/
│   └── schema.sql                   # Canonical SQLite WAL schema (v1.0 DDL - 5 core tables)
├── docs/                            # Architectural & Operational Documentation
│   ├── PRD.md                       # Product Requirements Document
│   ├── architecture.md              # End-to-end technical architecture & mathematical specs
│   ├── security.md                  # Security posture, DPAPI specs, and incident response
│   └── aeterna/
│       ├── agent-contract.md        # Strict operational rules for autonomous agents
│       ├── code-ownership.md        # Ownership matrix and Single Responsibility mapping
│       ├── invariant-cheatsheet.md  # Single Source of Truth for numerical constants
│       └── requirements.md          # Requirement Traceability Matrix (RTM M1-M7)
├── engine/                          # Core Algorithmic & Execution Engines
│   ├── analysis_engine/             # Mathematical modeling, indicator pipelines, PyO3 FFI
│   │   ├── python/                  # Python facade, Wilder 1978 indicators, interfaces, types
│   │   └── rust/                    # PyO3 C-Extension (PnL, Exness slippage, Monte Carlo)
│   ├── execution/                   # Broker bridge, server-side SL/TP, trailing & scale-out
│   ├── ingestion/                   # Data pipelines (MT5 M1/M15/H1/H4 rates, OANDA v20 REST)
│   ├── models/
│   │   └── kronos/                  # Kronos H4 ONNX Runtime CPU inference & feature scaler
│   ├── monitoring/                  # Daily session metrics, SQLite audit ledger, reporting
│   ├── risk_gate/                   # Graduated liquidity sizing (Z_vol) and pre-rollover guard
│   ├── security/                    # Windows DPAPI encryption, log sanitization, and ACL lockdown
│   ├── state_machine/               # Online EWMA spread baseline (α=0.08) & Z-score news gate
│   ├── telegram_bot/                # Admin control panel, 2-step confirmation, signal templates
│   └── watchdog/                    # Standalone Go daemon (127.0.0.1:20129) & risk circuit breaker
├── instruments/
│   └── xauusd/                      # XAUUSD-Specific Strategy Implementations
│       ├── config/                  # Validated parameters.yaml & Pydantic invariant loader
│       ├── macro_features/          # FRED API provider (US TIPS 10Y & DXY) with 24h SQLite cache
│       └── strategies/              # Strategy pool (Volatility Breakout, Contrarian, Mean-Reversion)
├── scripts/                         # Operational & Verification Tooling
│   ├── audit_security.py            # Local unified SCA vulnerability auditor (pip, cargo, go)
│   ├── setup_secrets.py             # Offline interactive DPAPI secret bootstrapping
│   └── verify_ecosystem.py          # 5-Pillar automated safety & invariant audit runner
└── tests/                           # Complete Verification Test Suite (186+ deterministic tests)
    ├── analysis/                    # Backtest runner, indicators, PyO3 parity, Kronos, Macro tests
    └── strategies/                  # Strategy execution, bracket bounds, and regime filter tests
```

---

## 4. Local Environment Setup

### Prerequisites
- **Operating System**: Windows 11 (64-bit) native environment.
- **Python**: Version `3.12+` managed via `uv`.
- **Rust**: Stable toolchain (`cargo`, `clippy`, `rustfmt`) with MSVC compiler.
- **Go**: Version `1.22+`.
- **Broker**: Local desktop installation of MetaTrader 5 (Exness terminal).

### Step-by-Step Initialization

```powershell
# 1. Clone the repository
git clone https://github.com/kazanaruishere-max/AETERNA.git
cd "AETERNA - QUANT PROJECT"

# 2. Synchronize Python virtual environment in locked mode
uv sync --frozen --all-groups

# 3. Build and compile the Rust PyO3 Extension in locked mode
uv run maturin develop --locked --manifest-path engine/analysis_engine/rust/Cargo.toml

# 4. Compile the Go Watchdog Daemon
cd engine/watchdog
go build -o watchdog.exe .
cd ../..

# 5. Bootstrap Encrypted Credentials via Windows DPAPI (One-time setup)
uv run python scripts/setup_secrets.py
# -> Prompts for MT5 Login ID, Server, Password, Telegram Token, and Admin ID.
# -> Saves encrypted ciphertext strictly to data/.secrets.enc.
```

---

## 5. Agentic Workflow (Tier A Parallel Protocol)

To ensure high-velocity development without introducing architectural drift, merge conflicts, or financial regressions, engineering tasks are managed through the **Tier A Parallel Protocol**:

```
                         [Human Operator / Solo Reviewer]
                                        │ (Review & Manual Merge)
                                        ▼
                             [main / Production Trunk]
                                        │ (Contract-First PR)
                   ┌────────────────────┴────────────────────┐
                   ▼                                         ▼
         [API Lock Merged]                         [Schema & Config Freeze]
                   │                                         │
     ┌─────────────┴─────────────┐                           │
     ▼                           ▼                           ▼
[.worktrees/stream-a]   [.worktrees/stream-b]       [.worktrees/stream-c]
   OMP Builder 1           OMP Builder 2               OMP Builder 3
 (Isolated Worktree)     (Isolated Worktree)         (Isolated Worktree)
     │                           │                           │
     └─────────────┬─────────────┘                           │
                   ▼                                         │
      [Serial Integration Queue] ◄───────────────────────────┘
      1. Review PR 1 -> Manual Merge to main
      2. Rebase PR 2 on main -> Verify -> Manual Merge
      3. Rebase PR 3 on main -> Verify -> Manual Merge
```

### The 5 Rules of Tier A Parallelism:
1. **Contract-First Development**: Data types, protocol signatures, and return schemas must be locked on `main` before opening worker branches.
2. **Schema & Config Freeze**: `db/schema.sql` and `parameters.yaml` are strictly read-only while parallel branches are active.
3. **Strict Mock Boundaries**: Builders must rely on interface protocols and mocks for dependencies outside their explicit task scope.
4. **Git Worktree Isolation**: Autonomous builders (`omp.exe`) work exclusively within dedicated `.worktrees/<slug>` directories to prevent cross-stream contamination.
5. **Serial Integration & Human Gate**: Merges into `main` are executed one at a time with mandatory rebases. Autonomous agents are forbidden from executing `gh pr merge`.

---

## 6. Verification & Audit Commands

Never assume correctness without verifiable mechanical proof. All pull requests must pass the following multi-stack audit gates locally prior to submission:

```powershell
# 1. Python Unit, Contract, & Financial Golden Tests (186 tests)
uv run pytest tests/ -v

# 2. Python Code Quality, Formatting, & Strict Typing
uv run ruff check .
uv run pyright

# 3. Rust Engine Tests & Clippy Linter
uv run cargo test --locked --manifest-path engine/analysis_engine/rust/Cargo.toml --all --verbose
uv run cargo clippy --locked --manifest-path engine/analysis_engine/rust/Cargo.toml --all-targets --all-features -- -D warnings

# 4. Go Watchdog Race Detection & Static Analysis
cd engine/watchdog
go vet ./...
go test -v -race ./...
cd ../..

# 5. Local Supply-Chain Vulnerability Audit (SCA)
uv run python scripts/audit_security.py

# 6. Comprehensive 5-Pillar Ecosystem Safety & Invariant Audit
uv run python scripts/verify_ecosystem.py
```

Expected output for an approved, production-grade build:
```
================================================================================
AETERNA QUANT — 5-PILLAR ECOSYSTEM SAFETY AUDIT
================================================================================
PILAR                          | PEMERIKSAAN                            | STATUS
--------------------------------------------------------------------------------
Pilar 2: Financial Safety      | Fail-Fast Fault-Out (No Swallowing)   | PASS
Pilar 3: Runtime Safety        | Zero-LLM Production Boundary           | PASS
Pilar 3: Runtime Safety        | 9router (Port 20128) Immunity          | PASS
Pilar 2: Financial Safety      | Numerical Invariants Conformance       | PASS
Pilar 1: Test Authenticity     | Python Ruff Lint                       | PASS
Pilar 1: Test Authenticity     | Python Pyright Strict                  | PASS
Pilar 1: Test Authenticity     | Python Unit & Golden Tests             | PASS
Pilar 3: Runtime Safety        | Rust Clippy                            | PASS
Pilar 2: Financial Safety      | Rust Backtest Simulation Tests         | PASS
Pilar 3: Runtime Safety        | Go Vet                                 | PASS
================================================================================
VERDICT: ECOSYSTEM SAFE (Lolos Seluruh Pemeriksaan)
```

---

## 7. License & Operational Governance

Proprietary quantitative software. Confidential and privileged. Unauthorized distribution, reproduction, or execution on live trading capital without verified safety gates is strictly prohibited.
