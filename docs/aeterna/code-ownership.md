# Code Ownership & Responsibility Matrix — AETERNA Quant Project (docs/aeterna/code-ownership.md)

Matriks kepemilikan kode untuk memastikan setiap direktori dan file memiliki **tanggung jawab tunggal (*Single Responsibility*)**, pemilik sub-agent yang jelas, dan kriteria verifikasi yang terukur. Dilarang membuat kode tanpa mendaftarkannya pada dokumen ini.

---

## 1. Peta Kepemilikan Modul (Module Ownership Map)

| Path Modul | Tanggung Jawab Tunggal | Owner Agent (OpenCode) | Builder (OMP) | Tier | Verification Gate |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `engine/ingestion/python/` | Ingestion data M1 OHLCV dari MT5 & scanning OANDA Book | `aeterna-ingestion` | OMP | B | `TEST-ING-*` |
| `engine/ingestion/go/` | Ingestion/scheduler berkecepatan tinggi & polling state | `aeterna-ingestion` | OMP | B | `go test ./engine/ingestion/go/...` |
| `engine/state_machine/` | Evaluasi status trading berbasis EWMA spread & jadwal news | `aeterna-risk` | OMP | A | `TEST-RSK-001`, `TEST-RSK-002` |
| `engine/risk_gate/` | Logika kalkulasi sizing risiko, graduated liquidity & rollover | `aeterna-risk` | OMP | A | `test_liquidity_sizing.py` |
| `engine/watchdog/` | Watchdog independen Go: evaluasi limit risiko pra-entry & killswitch | `aeterna-risk` | OMP | A | `GATE-M4-HUMAN` (`watchdog_test.go`) |
| `engine/analysis_engine/rust/` | Engine backtest & kalkulasi kuantitatif performa tinggi | `aeterna-backtest` | OMP | B | `cargo test --all` |
| `engine/analysis_engine/rust/src/py_bindings.rs` | PyO3 C-Extension FFI bindings & type converters | `aeterna-backtest` | OMP | B | `pytest tests/analysis/` |
| `engine/analysis_engine/python/loader.py` | SQLite candle loader (M1 time-series query via `pair`) | `aeterna-backtest` | OMP | B | `pytest tests/analysis/` |
| `engine/analysis_engine/python/runner.py` | Python backtest orchestrator facade & report builder | `aeterna-backtest` | OMP | B | `pytest tests/analysis/` |
| `engine/analysis_engine/python/types.py` | TypedDict & dataclass definitions for Python backtest | `aeterna-backtest` | OMP | B | `pyright` strict pass |
| `engine/analysis_engine/python/interfaces.py` | Protocol interfaces & dataset contracts M7 (Kronos, Macro, Sentiment) | `aeterna-architect` | OMP | B | `pyright` strict pass |
| `engine/analysis_engine/python/` | Wrapper PyO3, regime Kronos ONNX runtime, strategy pool | `aeterna-strategy` | OMP | B | `pytest tests/analysis/` |
| `engine/main.py` | Bootstraps live runtime, credentials, MT5 connection, Telegram bot, and service orchestration | `aeterna-lead` | OMP | A | `GATE-E2E-RUNTIME` |
| `engine/execution/` | Bridge MT5 Exness, server-side SL/TP, order lifecycle | `aeterna-execution` | OMP | A | `GATE-M5-HUMAN` |
| `engine/execution/emergency_handler.py` | Implementor konkret penanganan darurat (force-close, lockfile killswitch, repository state) | `aeterna-execution` | OMP | A | `tests/test_emergency_handler.py` |
| `engine/telegram_bot/` | Interface admin, notifikasi alert, inline control 2-step | `aeterna-execution` | OMP | A | `TEST-TEL-*` |
| `engine/shared/db/` | Shared SQLite WAL connection & repository IPC layer | `aeterna-architect` | OMP | A | `TEST-DB-*` |
| `engine/runtime/loop_a.py` | Fast-tick 2s polling, spread guard, state IPC, dan event penutup M15 | `aeterna-risk` | OMP | A | `tests/runtime/test_loop_a.py` |
| `engine/runtime/loop_b.py` | Evaluasi bar M15 tertutup menjadi observasi sinyal virtual deterministik | `aeterna-strategy` | OMP | A | `tests/runtime/test_loop_b.py` |
| `engine/runtime/virtual_tracker.py` | Penilaian outcome virtual 5 lapis exit tanpa eksekusi dana riil | `aeterna-backtest` | OMP | A | `tests/runtime/test_virtual_tracker.py` |
| `engine/runtime/dashboard.py` | Formatter observasi internal admin-only yang patuh batas publikasi | `aeterna-architect` | OMP | A | `tests/runtime/test_runtime_service.py` |
| `engine/runtime/bootstrap.py` | Komposisi dependensi runtime signal-only dan factory bundle immutable | `aeterna-architect` | OMP | A | `uv run pytest tests/e2e/test_runtime_bootstrap_e2e.py -v` |
| `engine/runtime/runtime_service.py` | Orkestrasi siklus hidup tri-loop dan tracker tanpa order riil | `aeterna-lead` | OMP | A | `tests/runtime/test_runtime_service.py` |
| `engine/runtime/news_sources.py` | Loader snapshot kalender MQL5 UTC untuk news blackout deterministik | `aeterna-architect` | OMP | A | `tests/runtime/test_news_sources.py` |
| `engine/runtime/chart_snapshot.py` | Renderer snapshot chart OHLC PNG deterministik admin-only | `aeterna-architect` | OMP | A | `tests/runtime/test_chart_snapshot.py` |
| `tests/runtime/` | Golden test deterministik untuk runtime tri-loop dan virtual journal | `aeterna-verifier` | OMP | A | `uv run pytest tests/runtime/ -v` |
| `tests/e2e/` | Smoke test integrasi end-to-end tri-loop runtime deterministik | `aeterna-verifier` | OMP | A | `uv run pytest tests/e2e/ -v` |
| `engine/monitoring/` | Daily reporting metrics, audit trail, dump Parquet | `aeterna-architect` | OMP | B | `TEST-DB-*` |
| `db/` | Canonical DDL SQLite WAL schema (SSoT untuk Python & Go) | `aeterna-architect` | Lead / OMP | A | `test_canonical_schema_file_on_disk` |
| `instruments/xauusd/config/` | Starting parameters YAML XAUUSD v1.0 (read-only config) | `aeterna-strategy` | OMP | A | Schema validation test |
| `instruments/xauusd/strategies/` | Logika 4 strategi spesifik XAUUSD (ATR Breakout, dll) | `aeterna-strategy` | OMP | B | Strategy unit tests |
| `instruments/xauusd/macro_features/` | Kalkulasi variabel makro XAUUSD (US TIPS 10Y, DXY) | `aeterna-strategy` | OMP | B | Macro feature tests |
| `tests/` | Golden tests deterministik & suite pengujian otomatis | `aeterna-verifier` | OMP | A | `uv run pytest tests/ -v` |
| `tests/test_emergency_handler.py` | Unit test deterministik untuk emergency handler, force close, lockfile, dan transisi state | `aeterna-verifier` | OMP | A | `uv run pytest tests/test_emergency_handler.py` |
| `scripts/` | Skrip verifikasi ekosistem 5-pilar dan audit keamanan lokal (SCA) | `aeterna-security` | Lead / Verifier | A | `uv run python scripts/audit_security.py` |
| `docs/` | Dokumentasi arsitektur, PRD, security, dan operasional | `aeterna-architect` | Lead / Manual | C | Doc review |
| `docs/aeterna/ea-development-and-optimization-guide.md` | Panduan teknik resmi optimasi MQL5 EA & multi-agent workflow | `aeterna-lead` | Lead | A | Invariant compliance audit |
| `docs/aeterna/ea-testing-and-certification-protocol.md` | Protokol sertifikasi institusional 6-tahap & kriteria live ready | `aeterna-backtest` | Lead | A | Institutional testing audit |
| `.handoff/research/` | Brief riset eksternal berlabel bukti (tanpa kode produksi) | `aeterna-research` | Lead | C | Review taksonomi bukti `agent-contract.md §8` |
| `ea/AeternaEA/` | Native MQL5 Expert Advisor Engine (Golden Baseline v1.0, Tier A) | `aeterna-strategy` | Lead | A | `metaeditor64.exe` compile + MT5 Strategy Tester |
| `ea/AeternaEA_v1_Baseline/` | Frozen immutable backup of verified v1.0 baseline (Disaster Recovery) | `aeterna-lead` | Lead | A | SHA256 checksum parity |
| `ea/experiments/` | Workspace klon eksperimen MQL5 EA (ADR-009) | `aeterna-strategy` | Lead | A | Compile pass + Strategy Tester benchmark |
| `ea/Scripts/` | PowerShell automation harness for headless batch strategy testing | `aeterna-verifier` | Lead | B | CLI batch execution pass |
| `ea/Reports/` | Historical backtest reports, charts, and metrics summaries | `aeterna-verifier` | Lead | C | Data audit verification |

---

## 2. Klasifikasi Safety Tier

### Tier A — Safety-Critical & Financial Risk
- **Modul**: `engine/main.py`, `engine/risk_gate/`, `engine/state_machine/`, `engine/execution/`, `engine/telegram_bot/`, `instruments/xauusd/config/`
- **Aturan**:
  - Wajib **Two-Key Review**: Dirancang oleh specialist terkait, di-red team oleh `aeterna-security` atau `aeterna-verifier`.
  - Wajib 100% deterministik golden test sebelum merge.
  - Wajib disetujui manual oleh Human Operator (Lead Architect) pada milestone gate terkait.

### Tier B — Core Engine & Modeling
- **Modul**: `engine/ingestion/`, `engine/analysis_engine/`, `engine/monitoring/`, `instruments/xauusd/strategies/`
- **Aturan**:
  - Wajib memenuhi test coverage critical path $\ge 80\%$.
  - Wajib lulus strict typing (`pyright`), linter Rust (`clippy`), atau Go (`go vet`).

### Tier C — Documentation & Configuration
- **Modul**: `docs/`, `.github/`, config tooling
- **Aturan**:
  - Review keselarasan terhadap invariant dan bebas dari committed secrets.
