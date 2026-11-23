# PLAN-02 — Monthly Maintenance Check

- `plan_id`: PLAN-02
- `created_utc`: 2026-11-22
- `status`: ACCEPTED_WITH_GUARD
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-verifier`
- `evidence_status`: CODE_CONTRACT_EXISTS
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Premise

Pengecekan maintenance bulanan untuk bug, dependency advisory, dan konsistensi gate.

## 2. Current Facts

- `.github/dependabot.yml`: advisory dependency monthly.
- `.github/workflows/codeql.yml`: weekly Senin 06:00 UTC.
- Belum ada maintenance gate bulanan penuh.
- `docs/aeterna/runbook-beta.md:104-119`: parameter strategi dibekukan saat pengumpulan 50–100 sampel.

## 3. The Unknowns

- Owner eksekusi bulanan.
- Format laporan.
- Apakah perbaikan boleh mengubah parameter saat sample window.

## 4. Options & Trade-offs

- Checklist + dry-run report: auditability tinggi, determinisme terjaga.
- Auto-fix bulanan: risiko drift numerik dan perubahan silent.

## 5. Direction

Checklist only. Bug fix tetap lewat branch → PR → verifier → human merge.

## 6. Cheapest Test

Satu script/checklist menjalankan:

```text
uv run pytest tests/ -q
uv run ruff check .
uv run pyright
cargo test --all
go test ./...
query kill-criteria
```

Output ditulis ke `docs/aeterna/MAINTENANCE-REPORT-YYYY-MM.md`. Dry-run sekali, tanpa auto-apply.

## 7. Entry Criteria / Kill Switch

Stop jika `instruments/xauusd/config/parameters.yaml` berubah selama 50–100 sample window. Tidak ada `gh pr merge`, `git merge`, atau auto-merge.

## 8. Explicit Non-Authorization

File ini bukan task packet dan bukan izin untuk mengubah kode produksi.
