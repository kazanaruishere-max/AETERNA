# Code Ownership & Responsibility Matrix — AETERNA Quant Project (docs/aeterna/code-ownership.md)

Matriks kepemilikan kode untuk memastikan setiap direktori dan file memiliki **tanggung jawab tunggal (*Single Responsibility*)**, pemilik sub-agent yang jelas, dan kriteria verifikasi yang terukur. Dilarang membuat kode tanpa mendaftarkannya pada dokumen ini.

---

## 1. Peta Kepemilikan Modul (Module Ownership Map)

| Path Modul | Tanggung Jawab Tunggal | Owner Agent (OpenCode) | Builder (OMP) | Tier | Verification Gate |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `engine/ingestion/python/` | Ingestion data M1 OHLCV dari MT5 & scanning OANDA Book | `aeterna-ingestion` | OMP | B | `TEST-ING-*` |
| `engine/ingestion/go/` | Ingestion/scheduler berkecepatan tinggi & polling state | `aeterna-ingestion` | OMP | B | `go test ./engine/ingestion/go/...` |
| `engine/state_machine/` | Evaluasi status trading berbasis EWMA spread & jadwal news | `aeterna-risk` | OMP | A | `TEST-RSK-001`, `TEST-RSK-002` |
| `engine/risk_gate/` | Watchdog independen Go: evaluasi limit risiko & killswitch | `aeterna-risk` | OMP | A | `GATE-M4-HUMAN` |
| `engine/analysis_engine/rust/` | Engine backtest & kalkulasi kuantitatif performa tinggi | `aeterna-backtest` | OMP | B | `cargo test --all` |
| `engine/analysis_engine/python/` | Wrapper PyO3, regime Kronos ONNX runtime, strategy pool | `aeterna-strategy` | OMP | B | `pytest tests/analysis/` |
| `engine/execution/` | Bridge MT5 Exness, server-side SL/TP, order lifecycle | `aeterna-execution` | OMP | A | `GATE-M5-HUMAN` |
| `engine/telegram_bot/` | Interface admin, notifikasi alert, inline control 2-step | `aeterna-execution` | OMP | A | `TEST-TEL-*` |
| `engine/shared/db/` | Shared SQLite WAL connection & repository IPC layer | `aeterna-architect` | OMP | A | `TEST-DB-*` |
| `engine/monitoring/` | Daily reporting metrics, audit trail, dump Parquet | `aeterna-architect` | OMP | B | `TEST-DB-*` |
| `db/` | Canonical DDL SQLite WAL schema (SSoT untuk Python & Go) | `aeterna-architect` | Lead / OMP | A | `test_canonical_schema_file_on_disk` |
| `instruments/xauusd/config/` | Starting parameters YAML XAUUSD v1.0 (read-only config) | `aeterna-strategy` | OMP | A | Schema validation test |
| `instruments/xauusd/strategies/` | Logika 4 strategi spesifik XAUUSD (ATR Breakout, dll) | `aeterna-strategy` | OMP | B | Strategy unit tests |
| `instruments/xauusd/macro_features/` | Kalkulasi variabel makro XAUUSD (US TIPS 10Y, DXY) | `aeterna-strategy` | OMP | B | Macro feature tests |
| `tests/` | Golden tests deterministik & suite pengujian otomatis | `aeterna-verifier` | OMP | A | `uv run pytest tests/ -v` |
| `docs/` | Dokumentasi arsitektur, PRD, security, dan operasional | `aeterna-architect` | Lead / Manual | C | Doc review |

---

## 2. Klasifikasi Safety Tier

### Tier A — Safety-Critical & Financial Risk
- **Modul**: `engine/risk_gate/`, `engine/state_machine/`, `engine/execution/`, `engine/telegram_bot/`, `instruments/xauusd/config/`
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
