# PLAN-03 — Kubernetes / Docker Preparation

- `plan_id`: PLAN-03
- `created_utc`: 2026-11-22
- `status`: REJECTED_FOR_NOW
- `approval`: NOT_APPROVED_FOR_IMPLEMENTATION
- `phase`: P1 Journal
- `owner`: `aeterna-architect` (later)
- `evidence_status`: ARCHITECTURE_MISMATCH
- `canonical_state`: `docs/aeterna/agent-state.md`

## 1. Premise

Menyiapkan Kubernetes/Docker sebelum beta.

## 2. Current Facts

- Tidak ada `Dockerfile`, `docker-compose`, Helm, atau manifest k8s di repo.
- Runtime bergantung pada host lokal Windows, MT5 terminal, DPAPI keystore, SQLite WAL, Go watchdog `127.0.0.1:20129`.
- 9router `localhost:20128` dilarang dimatikan atau di-restart.
- Beban saat ini: 1 simbol, 1 posisi maksimal, ≤5 trade/hari.

## 3. The Unknowns

- Target host deployment.
- Windows container compatibility.
- Keystore di container.
- Lifecycle MT5 terminal.
- Health semantics untuk mode `SIGNAL_ONLY`.

## 4. Options & Trade-offs

- Single-host process contract + healthcheck: murah, cocok dengan MT5/DPAPI.
- Docker untuk tooling stateless: opsional nanti.
- Kubernetes sekarang: control plane + scheduling + keystore complexity tanpa manfaat langsung.

## 5. Direction

Tidak jadi. Siapkan process contract dulu. Docker hanya jika ada tooling stateless yang jelas.

## 6. Cheapest Test

Jalankan runtime 7 hari kalender di host lokal, lalu restart drill hanya PID non-9router dari port spesifik. Dokumentasikan startup/shutdown. Jika tidak butuh intervensi manual, k8s tidak terjustifikasi.

## 7. Entry Criteria / Kill Switch

Reopen hanya jika ada hard requirement multi-host / multi-broker atau runtime non-Windows. Tidak boleh menargetkan port 20128.

## 8. Explicit Non-Authorization

File ini bukan izin membuat Dockerfile, compose, Helm chart, atau cluster manifest.
