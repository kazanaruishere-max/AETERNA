# Requirement Traceability Matrix (RTM) — AETERNA Quant Project (docs/aeterna/requirements.md)

Matriks penelusuran persyaratan sistem dari dokumen acuan tingkat tinggi (`PRD.md`, `architecture.md`, `security.md`, `agents.md`) ke implementasi tugas dan bukti pengujian. Setiap perubahan fitur wajib memperbarui baris pada tabel ini.

---

## 1. Data Foundation & Ingestion (Milestone 1)

| REQ ID | Sumber | Deskripsi Persyaratan | Target | Disposisi | Task ID | Test / Gate | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `REQ-ING-001` | arch §2 | Skema database SQLite dengan mode WAL untuk hot tier 60-90 hari | M1 | COVERED | TASK-M1-01 | `TEST-DB-001` | VERIFIED |
| `REQ-ING-002` | arch §6.1 | Tabel `trades`, `blocked_signals`, `model_registry`, `market_candles`, `system_state` | M1 | COVERED | TASK-M1-01 | `TEST-DB-002` | VERIFIED |
| `REQ-ING-003` | arch §3.1 | Binding MT5 Python untuk ingestion data M1 OHLCV + Tick Volume Exness | M1 | COVERED | TASK-M1-02 | `TEST-ING-001` | VERIFIED |
| `REQ-ING-004` | arch §3.1 | Scanning OANDA v20 REST API untuk data Order/Position Book (read-only) | M1 | COVERED | TASK-M1-03 | `TEST-ING-002` | VERIFIED |
| `REQ-ING-005` | arch §6.2 | Data tagging eksplisit: `training`, `validation`, `forward_test`, `live_production` | M1 | COVERED | TASK-M1-01 | `TEST-DB-003` | VERIFIED |
| `REQ-ING-006` | arch §6.2 | Modul dump arsip Parquet untuk data operasional berumur > 90 hari | M1 | DEFERRED | TASK-M1-04 | `TEST-ING-003` | BACKLOG |

---

## 2. Backtest Engine & Modeling (Milestone 2)

| REQ ID | Sumber | Deskripsi Persyaratan | Target | Disposisi | Task ID | Test / Gate | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `REQ-BKT-001` | arch §2 | Extension Rust performa tinggi via PyO3 untuk komputasi backtest | M2 | COVERED | TASK-M2-01 | `cargo test --all` | VERIFIED |
| `REQ-BKT-002` | arch §3.4 | Pemodelan rentang bebas slippage Exness dan simulasi slippage adaptif | M2 | COVERED | TASK-M2-02 | `test_slippage_free_range` | VERIFIED |
| `REQ-BKT-003` | arch §3.4 | Validasi Stop Level minimum akun Standard Exness pada pending/SL/TP | M2 | COVERED | TASK-M2-02 | `test_stop_level_validation` | VERIFIED |
| `REQ-BKT-004` | arch §3.4 | Simulasi Gap Rule Exness pada pembukaan pasar mingguan (3 jam pertama) | M2 | COVERED | TASK-M2-02 | `test_gap_rule` | VERIFIED |
| `REQ-BKT-005` | arch §4.1 | Harness validasi Monte Carlo 1000 iterasi & Walk-Forward analysis | M2 | COVERED | TASK-M2-03 | `test_monte_carlo_deterministic_reproducibility` | VERIFIED |

---

## 3. Strategi & Multi-Timeframe (Milestone 3 & 7)

| REQ ID | Sumber | Deskripsi Persyaratan | Target | Disposisi | Task ID | Test / Gate | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `REQ-STR-001` | arch §4.1 | Implementasi Strategi 1: Volatility Breakout ATR expansion M15 | M3 | PENDING | TASK-M3-01 | `TEST-STR-001` | BACKLOG |
| `REQ-STR-002` | arch §4.3 | Hierarki Multi-Timeframe: H4 Regime, H1 Setup, M15 Execution | M3 | PENDING | TASK-M3-02 | `TEST-STR-002` | BACKLOG |
| `REQ-STR-003` | arch §9 | Starting parameters YAML loader dinamis (`instruments/xauusd/config/parameters.yaml`) | M3 | PENDING | TASK-M3-03 | `TEST-STR-003` | BACKLOG |
| `REQ-STR-004` | arch §4.1 | Strategi 2: Positioning Contrarian (OANDA Book Sentiment) | M7 | DEFERRED | - | - | BACKLOG |
| `REQ-STR-005` | arch §4.1 | Strategi 3: Intermarket Correlation (US Real Yield TIPS 10Y + DXY) | M7 | DEFERRED | - | - | BACKLOG |
| `REQ-STR-006` | arch §4.1 | Strategi 4: Mean-Reversion Adaptive Volatility Band | M7 | DEFERRED | - | - | BACKLOG |
| `REQ-STR-007` | arch §4.2 | Integrasi model Kronos ONNX Runtime CPU untuk deteksi regime H4 | M7 | DEFERRED | - | - | BACKLOG |

---

## 4. Risk Gate, State Machine, & Watchdog (Milestone 4)

| REQ ID | Sumber | Deskripsi Persyaratan | Target | Disposisi | Task ID | Test / Gate | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `REQ-RSK-001` | arch §3.3 | State machine berita 4 state: `NORMAL`, `PRE_NEWS_WATCH`, `PAUSED`, `RECOVERY_CHECK` | M4 | COVERED | TASK-M4-01 | `test_state_machine.py` | VERIFIED |
| `REQ-RSK-002` | arch §3.3 | Kalkulasi EWMA spread baseline ($\alpha=0.08$) dan Z-Score real-time | M4 | COVERED | TASK-M4-01 | `test_state_machine.py` | VERIFIED |
| `REQ-RSK-003` | arch §3.5 | Deteksi likuiditas via Z-score tick volume dan graduated sizing 50% | M4 | COVERED | TASK-M4-02 | `test_liquidity_sizing.py` | VERIFIED |
| `REQ-RSK-004` | arch §5.1 | Daemon watchdog independen Go untuk validasi limit risiko pra-entry | M4 | COVERED | TASK-M4-03 | `watchdog_test.go` | VERIFIED |
| `REQ-RSK-005` | arch §5.2 | Exit Logic 5 lapis (SL/TP, Trailing, Partial, Time 8-bar, Regime) | M4 | COVERED | TASK-M3-02-FIX | `test_engine.rs` | VERIFIED |
| `REQ-RSK-006` | arch §5.2 | Force close seluruh posisi 15 menit sebelum rollover harian bank | M4 | COVERED | TASK-M4-02 | `test_liquidity_sizing.py` | VERIFIED |
| `REQ-RSK-007` | PRD §3 | Enforce parameter keras: 0.5% risk, 2% daily loss, 10% drawdown killswitch | M4 | COVERED | TASK-M4-03 | `watchdog_test.go` | VERIFIED |

---

## 5. Eksekusi MT5, Logging, & Telegram (Milestone 5 & 6)

| REQ ID | Sumber | Deskripsi Persyaratan | Target | Disposisi | Task ID | Test / Gate | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `REQ-EXE-001` | arch §5.3 | Server-Side Attached SL/TP wajib pada setiap pengiriman order Exness | M5 | PENDING | TASK-M5-01 | `GATE-M5-HUMAN` | BACKLOG |
| `REQ-EXE-006` | arch §3.1 | Thread-safety & mutual exclusion lock (`threading.Lock`) pada `ExnessClient` (P0 Blocker: cegah race condition MT5 C-extension antar-thread candle ingestion vs live spread polling 1Hz) | M5 | MANDATORY_BLOCKER | TASK-M5-01 | `TEST-EXE-LOCK` | BACKLOG |
| `REQ-EXE-002` | arch §5.3 | Server-side trailing stop via modifikasi order langsung ke broker | M5 | PENDING | TASK-M5-02 | `TEST-EXE-001` | BACKLOG |
| `REQ-EXE-003` | sec §1 | Manajemen kredensial zero-plaintext via `.env` dan Windows DPAPI | M5 | PENDING | TASK-M5-03 | `TEST-SEC-001` | BACKLOG |
| `REQ-EXE-004` | sec §3 | Log sanitization filter (redaksi otomatis password, token, akun MT5) | M5 | PENDING | TASK-M5-04 | `TEST-SEC-002` | BACKLOG |
| `REQ-EXE-005` | sec §3.3 | Proteksi izin akses Windows ACL (`icacls`) Current User Only pada log dan DB | M5 | PENDING | TASK-M5-04 | `TEST-SEC-003` | BACKLOG |
| `REQ-TEL-001` | sec §2.1 | Telegram Bot dengan whitelist integer `TELEGRAM_ADMIN_ID` (silent drop) | M6 | PENDING | TASK-M6-01 | `TEST-TEL-001` | BACKLOG |
| `REQ-TEL-002` | sec §2.2 | Ephemeral callback nonce 60 detik untuk pencegahan replay attack | M6 | PENDING | TASK-M6-01 | `TEST-TEL-002` | BACKLOG |
| `REQ-TEL-003` | sec §2.3 | Two-step confirmation (batas 15s) untuk Killswitch dan Force Close All | M6 | PENDING | TASK-M6-02 | `TEST-TEL-003` | BACKLOG |
| `REQ-TEL-004` | arch §6.3 | Laporan harian otomatis: PnL, Win/Loss, Max DD, waktu PAUSED, link Myfxbook | M6 | PENDING | TASK-M6-03 | `TEST-TEL-004` | BACKLOG |
