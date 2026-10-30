# Clean Code & Refactor Standard — AETERNA Quant Project (docs/aeterna/clean-code-rules.md)

Dokumen ini memuat standar kuantitatif kualitas kode, konvensi penulisan, dan protokol refactoring tanpa efek samping untuk proyek AETERNA Quant. OMP (builder) wajib mematuhi aturan ini, dan `aeterna-verifier` wajib menolak kode yang melanggar.

---

## 1. Aturan Kuantitatif Ukuran Kode (Keras)

1. **Panjang Fungsi**: Maksimal **50 baris** per fungsi. Jika fungsi melebihi 50 baris, pecah menjadi fungsi utilitas pembantu berfokus tunggal.
2. **Panjang File**: Tipikal **200–400 baris**, maksimal mutlak **800 baris**.
3. **Nesting Level**: Maksimal **4 tingkat indentasi**. Gunakan *early return* / *guard clauses* untuk meratakan struktur kode.
4. **Zero Dead Code**: Dilarang mengunggah fungsi, variabel, atau import yang tidak pernah dipanggil.

---

## 2. Standar Bahasa & Linter Mandatori

### 2.1 Python (3.12+)
- **Runner**: Wajib via `uv run` (bukan python global).
- **Linter & Formatter**:
  ```powershell
  uv run ruff check .
  uv run ruff format --check .
  ```
- **Type Checking (Strict)**:
  ```powershell
  uv run pyright
  ```
- **Konvensi**:
  - Wajib type hints eksplisit pada seluruh parameter dan return value fungsi publik.
  - Transfer data harga, order, dan sinyal wajib menggunakan immutable data structures: `@dataclass(frozen=True)` atau Pydantic immutable models.
  - **Zero Silent Error Swallowing**: Dilarang keras menggunakan `except: pass` atau menangkap exception tanpa pencatatan log level `ERROR`.

### 2.2 Rust (PyO3 Engine)
- **Linter & Clippy**:
  ```powershell
  cargo fmt --check
  cargo clippy -- -D warnings
  ```
- **Konvensi**:
  - Dilarang keras menggunakan blok `unsafe` kecuali pada wrapper eksternal PyO3 FFI yang terisolasi ketat.
  - Dilarang menggunakan `.unwrap()` pada jalur komputasi finansial; gunakan `Result<T, E>` dengan penanganan error eksplisit via `thiserror` atau `anyhow`.

### 2.3 Go (Watchdog Daemon)
- **Formatting & Vet**:
  ```powershell
  gofmt -l .
  go vet ./...
  ```
- **Konvensi**:
  - Kode watchdog wajib beroperasi *panic-free*. Pasang mekanisme `recover()` pada goroutine utama pengawas.
  - Dilarang menelan error secara diam-diam (`_ = err`). Setiap kegagalan komunikasi wajib memicu state aman (`NO-ENTRY`).

---

## 3. Protokol Refactoring Tanpa Efek Samping (Behavior-Preserving)

Refactoring bertujuan meningkatkan kualitas struktur kode tanpa mengubah fungsionalitas:

1. **Characterization Tests**: Sebelum merombak kode eksisting, pastikan unit test yang ada mencakup seluruh kasus penggunaan (*behavior lock*). Jika test belum ada, buat test terlebih dahulu.
2. **Parity Check**: Setelah refactoring selesai, seluruh test suite wajib lulus 100% tanpa modifikasi pada ekspektasi output test.
3. **Pemisahan Commit**: Commit perbaikan arsitektur/refactoring (`refactor: ...`) DILARANG dicampur dengan commit fitur baru (`feat: ...`).
4. **Scope Isolation**: Dilarang melakukan *drive-by refactoring* (mengubah kode di luar modul yang sedang ditugaskan). Perbaikan di luar scope wajib dicatat sebagai tiket task baru.

---

## 4. Format Dokumentasi Tanggung Jawab Modul

Setiap file kode sumber baru wajib menyertakan blok docstring tanggung jawab tunggal pada baris paling atas:

```python
"""
Module: engine.risk_gate.sizing
Responsibility: Menghitung ukuran lot aman berbasis 0.5% risk dan graduated liquidity scaling.
Owner: aeterna-risk
Tier: A
"""
```
