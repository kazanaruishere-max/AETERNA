---
name: aeterna-verify
description: Perintah verifikasi mekanis multi-stack (Python, Rust, Go), validasi golden test deterministik, dan audit clean code.
license: Proprietary
compatibility: opencode
metadata:
  stack: [python, rust, go]
  workflow: verification-gate
---

# Purpose
Menyediakan instruksi eksekusi verifikasi teknis deterministik lintas bahasa (Python `uv`, Rust `cargo`, Go `go test`), validasi *clean code* linter, dan penegakan *zero fabrication* pada pelaporan bukti.

# When to use
- Gunakan setiap kali OMP menyelesaikan task packet.
- Gunakan saat `aeterna-verifier` menguji patch atau branch sebelum digabungkan.
- Gunakan saat memverifikasi refactoring untuk membuktikan tidak ada efek samping fungsional.

# Hard rules
1. Dilarang mengarang (*fabricate*) hasil pengujian. Seluruh bukti wajib melampirkan teks output asli dari terminal.
2. Pengujian jalur finansial kritis wajib mencakup Golden Test deterministik:
   - Sizing lot & batas 0.5% risk.
   - State machine transition (EWMA spread Z-score).
   - Exit logic 5 lapis terpisah.
   - Slippage penalty simulator Rust.
3. Formatter, linter, dan strict type checker wajib lulus 100% tanpa warning/error yang diabaikan.
4. Refactor wajib membuktikan parity: test sebelum dan sesudah refactor harus lulus tanpa modifikasi ekspektasi test.

# Required inputs
- Path direktori atau file yang diuji.
- Task packet acuan dengan Acceptance Criteria.

# Procedure
1. Jalankan linter dan formatter per stack:
   - Python: `uv run ruff check .` dan `uv run ruff format --check .` dan `uv run pyright`
   - Rust: `cargo fmt --check` dan `cargo clippy -- -D warnings`
   - Go: `gofmt -l .` dan `go vet ./...`
2. Jalankan test suite relevan:
   - Python: `uv run pytest tests/<submodul> -v`
   - Rust: `cargo test --all`
   - Go: `go test -v ./...`
3. Periksa apakah ada file di luar scope yang dimodifikasi (`git diff --stat`).
4. Periksa apakah ada file baru yang belum terdaftar di `docs/aeterna/code-ownership.md`.
5. Terbitkan Blok Accountability:
   - ✅ Terverifikasi: <apa> + <perintah> -> <hasil nyata>
   - ⚠️ Belum terverifikasi: <asumsi/gap>
   - 🔻 Risiko teratas: <1-2 risiko> - deteksi: <cara>

# Output contract
```markdown
### Verification Audit Report
- Scope Check: [PASS - Hanya file scope yang disentuh]
- Code Ownership: [PASS - Terdaftar di code-ownership.md]
- Linter & Typecheck:
  - Python (ruff, pyright): PASS
  - Rust (clippy): PASS
  - Go (vet): PASS
- Test Suite Results:
  - Command: uv run pytest tests/ -v
  - Output: <N> passed in <X>s
- Golden Tests Verified: [YES]
- Behavior Parity (Refactor): [CONFIRMED / NOT APPLICABLE]
- Verdict: PASS | FAIL
```

# Self-check
1. [ ] Apakah perintah dijalankan langsung di terminal?
2. [ ] Apakah return code adalah 0?
3. [ ] Apakah tidak ada suppressed errors (`# type: ignore`, `// nolint`) tanpa persetujuan?

# Failure modes
- **Gejala**: Test lulus tetapi ada warning linter `F401 (unused import)`.
- **Tindakan**: Status tetap `FAIL`. OMP wajib membersihkan dead code sebelum task disetujui.
