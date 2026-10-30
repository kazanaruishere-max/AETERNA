# Agent Development Environment & Technical Conventions (agents.md)

Dokumen ini merupakan panduan operasional multi-agent AI untuk rekayasa perangkat lunak sistem AI Trading XAUUSD, diturunkan dari `ai-trading-master-reference.md` (§12, §14) serta usulan konvensi teknis yang disetujui.

---

## 1. Peran Agent & Batasan Lingkungan (Agent Roles & Boundaries)

Pengembangan sistem memanfaatkan kolaborasi multi-agent lokal terisolasi:

```
                  ┌──────────────────────────────┐
                  │    Human Operator (Solo)     │
                  └──────────────┬───────────────┘
                                 │ Review & Approval
                                 ▼
                  ┌──────────────────────────────┐
                  │   OpenCode (Lead Architect)  │
                  └──────────────┬───────────────┘
                                 │ Delegasi task spesifik
                                 ▼
                  ┌──────────────────────────────┐
                  │   OMP / Sub-Agent (Dev)      │
                  │   (Isolasi Orca Git Worktree)│
                  └──────────────────────────────┘
```

### Konfigurasi Tooling & Model Gateway
1. **Orkestrator**: **Orca** (onorca.dev, MIT open source) digunakan untuk menjalankan agent pada Git worktree terisolasi.
2. **Model Gateway**: **9Router** (localhost:20128).
   - **Peraturan Keras (Do Not Kill)**: Proses 9Router pada port 20128 tidak boleh dihentikan, di-restart, atau di-kill dalam kondisi apa pun.
   - **Cakupan Akses Model**: Terbatas pada **OpenCode Free tier + OpenRouter**. Dilarang keras mengaktifkan interception/MITM Bridge berbayar yang melanggar ToS upstream.
3. **Pemisahan Tegas Jalur AI (Strict Production Boundary)**:
   - LLM (Claude, GPT, dsb.) **HANYA** berfungsi sebagai asisten koding offline (*developer tooling*).
   - **ZERO LLM DI JALUR PRODUKSI**: Mesin inferensi produksi tidak pernah memanggil LLM/API eksternal. Evaluasi strategi, deteksi regime, dan penentuan risk score 100% menggunakan model kuantitatif deterministik (Kronos ONNX Runtime, time-series stats, dan algoritma matematis native).

---

## 2. Urutan Milestone & Verification Gates

Pengembangan wajib mengikuti roadmap bertahap berikut. Tidak diperkenankan melompati milestone.

| Milestone | Ruang Lingkup | Verification Gate Manusia (🔴) |
| :---: | :--- | :---: |
| **M1** | **Data Foundation**: Skema database SQLite WAL, ingestion MT5 Exness (M1 OHLCV + volume), streaming OANDA v20 REST. | Otomatis (Unit test lolos) |
| **M2** | **Backtest Engine**: Extension Rust (PyO3), pemodelan slippage realistis Exness, data loading M1. | 🔴 **Review Wajib**: Verifikasi manual perhitungan PnL, spread penalty, dan slippage vs hitungan tangan. |
| **M3** | **Satu Strategi + Regime Awal**: Volatility Breakout (ATR expansion), filter regime rule-based awal (belum Kronos). | Otomatis (Backtest report lolos) |
| **M4** | **Risk Gate & State Machine**: Watchdog independen Go, dual news filter (kalender blackout + Z-score spread), graduated liquidity sizing. | 🔴 **Review Wajib**: Audit baris demi baris logika sizing, batas drawdown, dan emergency killswitch. |
| **M5** | **Eksekusi Exness & Logging**: Binding MT5 Python, server-side attached SL/TP, logging transaksi komprehensif. | 🔴 **Review Wajib**: Uji eksekusi demo, pastikan SL/TP terverifikasi ada di server broker MT5. |
| **M6** | **Telegram Control & Reporting**: Notifikasi per-trade, laporan harian otomatis, inline button (pause/resume/override). | Otomatis (E2E alert test lolos) |
| **M7+** | **Advanced Layers**: Integrasi Kronos ONNX, macro features, strategi 2/3/4, Z-score adaptif penuh, broker bake-off Exness vs HFM. | Evaluasi berkala |

*Catatan Milestone 5*: **Forward test resmi sistem baru baru boleh dimulai setelah Milestone 5 selesai dan lolos verifikasi.** Jika modal riil belum mencapai ~$1,000, forward test wajib berjalan di akun Standard Demo.

---

## 3. Konvensi Git & Struktur Worktree

Untuk menjaga stabilitas repositori saat banyak agent bekerja serentak:

### 3.1 Pola Branching (Trunk-Based)
- Branch utama: `main`. Selalu dalam kondisi deployable dan lulus test.
- Feature Branch: `feat/m<nomor_milestone>-<slug_pendek>` (contoh: `feat/m1-sqlite-schema`).
- Hotfix Branch: `hotfix/<slug>` untuk perbaikan bug mendesak.

### 3.2 Isolasi Orca Git Worktree
- Setiap tugas terisolasi dialokasikan ke direktori `.worktrees/`:
  ```
  .worktrees/
  ├── m1-ingestion/
  ├── m2-backtest-rust/
  └── m4-risk-watchdog/
  ```
- File `.env` rahasia **tidak boleh di-copy sembarangan ke worktree**. Gunakan template `.env.example` dengan mock credentials selama pengembangan.

### 3.3 Struktur Commit
Wajib menggunakan format **Conventional Commits**:
```
<type>(<scope>): <deskripsi imperatif singkat dalam bahasa Inggris/Indonesia>
```
- **Type**: `feat` | `fix` | `test` | `refactor` | `chore` | `perf` | `docs`.
- **Scope**: Modul terdampak (`risk`, `ingestion`, `backtest`, `telegram`, `db`).
- **Contoh Valid**:
  - `feat(risk): enforce server-side SL/TP attachment on MT5 order send`
  - `test(state-machine): add unit test for EWMA spread z-score spike`
  - `fix(backtest): correct pip calculation logic for XAUUSD contract size`
- Dilarang menambahkan komentar/komit bertele-tele dari AI ("Generated by AI agent...").

### 3.4 Penegakan Branch Protection & CODEOWNERS
Untuk mencegah sub-agent atau pull request memodifikasi logika proteksi risiko atau parameter finansial tanpa pengawasan:
1. File `.github/CODEOWNERS` melindungi 6 path safety-critical:
   - `engine/risk_gate/`
   - `engine/state_machine/`
   - `engine/analysis_engine/rust/`
   - `engine/execution/`
   - `engine/telegram_bot/`
   - `instruments/xauusd/config/parameters.yaml`
2. PR yang menyentuh salah satu dari 6 path tersebut wajib direview dan disetujui manual oleh Lead Architect sebelum dapat di-merge.
3. Status check `Financial Golden Tests (Deterministic)` berstatus wajib (*required check*) pada pengaturan GitHub Branch Protection `main`, memblokir merge secara fisik jika kalkulasi numerik gagal.

---

## 4. Standar Pengujian (Testing Requirements)

Pengujian berfokus pada **critical path** (perhitungan finansial dan mekanisme keselamatan).

### 4.1 Modul Wajib 100% Deterministic Test (Golden Test)
1. **Risk Sizing & Lot Calculation**: Uji variasi equity, pastikan output lot tidak pernah melebihi 0.5% risk atau di bawah 0.01 lot minimum Standard.
2. **State Machine Transitions**: Uji transisi state lengkap (`NORMAL` → `PRE_NEWS` → `PAUSED` → `RECOVERY` → `NORMAL`) dengan data deret waktu sintetik.
3. **Exit Logic 5 Lapis**: Uji pemicu terpisah untuk Fixed SL/TP, Trailing Stop, Partial Close, Time Invalidation (8 bar), dan Regime Invalidation.
4. **Slippage Simulator (Rust)**: Uji konsistensi penalti slippage terhadap data tick artifisial.

### 4.2 Tooling Eksekusi Pengujian
- **Python**: Wajib menggunakan `uv`:
  ```powershell
  uv run pytest tests/ -v
  ```
- **Rust**:
  ```powershell
  cargo test --all
  ```
- **Go (Watchdog)**:
  ```powershell
  go test -v ./...
  ```

---

## 5. Standar Kode & Bahasa Pemrograman

### 5.1 Python Standards
- Eksekusi environment wajib melalui `uv` (bukan virtualenv manual atau `python` global).
- Tipe data ketat (*strict typing*): Wajib menggunakan type hints pada semua fungsi publik dan divalidasi dengan `pyright` atau `mypy`.
- Immutability: Gunakan `dataclasses(frozen=True)` atau `pydantic` immutable model untuk transfer data harga/sinyal.
- Panjang file maksimal 400 baris; fungsi maksimal 50 baris.

### 5.2 Rust Standards
- Mengutamakan performa dan *safety*: Dilarang menggunakan blok `unsafe` kecuali pada wrapper PyO3 FFI yang terisolasi ketat.
- Penanganan error eksplisit via `Result<T, E>`. Dilarang menggunakan `.unwrap()` pada jalur komputasi utama; gunakan pencatatan error terstruktur.
- Lulus linter `cargo clippy -- -D warnings`.

### 5.3 Go Standards
- Watchdog wajib beroperasi *panic-free*. Gunakan mekanisme `recover()` pada goroutine pengawas.
- Dependency seminimal mungkin (utamakan standard library `net/http`, `database/sql`, `os/signal`).

### 5.4 Penanganan Error (Zero Silent Swallowing)
- **Dilarang menelan error diam-diam** (`except: pass` atau `_ = err`).
- Setiap kegagalan komunikasi dengan MetaTrader 5 atau OANDA wajib dicatat dengan level `ERROR` ke file log audit dan mengubah state mesin ke status aman (*NO-ENTRY*).
- Tandai simplifikasi sengaja dengan format komentar:
  ```python
  # ponytail: simplifikasi polling SQLite; upgrade ke IPC socket jika latency > 100ms
  ```
