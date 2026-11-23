---
name: aeterna-task-protocol
description: Canonical harness-neutral protocol for authoring, authorizing, executing, and evaluating self-contained AETERNA task packets for any agentic AI harness.
license: AGPL-3.0-only
compatibility: universal
metadata:
  protocol_version: "2.0.0"
  authority: canonical
  supersedes: "omp-task-protocol"
  target_harnesses: [claude-code, codex-cli, deepseek-harness, antigravity-cli, opencode, generic-agentic-cli]
  workflow: task-packet
  source_of_truth: docs/aeterna/AUTONOMOUS_BUILDER.md
---

# AETERNA Task Protocol — Canonical, Harness-Neutral

## 1. Purpose

Mengubah desain yang telah disetujui menjadi **satu paket tugas mandiri** yang bisa dijalankan oleh agentic AI mana pun tanpa riwayat chat, lalu mengevaluasi hasilnya dengan bukti mekanis. Protokol ini menggantikan identitas lama `omp-task-protocol`; OMP hanyalah salah satu builder yang mungkin, bukan syarat kepatuhan.

## 2. Authority & Precedence

1. Tier 0 aturan proyek tidak bisa dioverride:
   - Jangan mematikan / me-restart 9router port `20128`.
   - Operasi destruktif, deploy produksi, dan migrasi berisiko butuh approval operator.
   - Dilarang pipe-to-shell (`irm | iex`, `curl | sh`) di Windows.
2. `docs/aeterna/agent-state.md` menentukan apakah `active_task` ada.
3. Jika `active_task: null`, agent **dilarang menulis kode**. Hanya audit read-only atau berhenti.
4. Task packet adalah satu-satunya authorization boundary: `allowed_paths`, `acceptance_commands`, dan `base_commit`.
5. Konflik antar dokumen → `NEEDS_DECISION`, bukan interpretasi sendiri.

## 3. Harness Binding

| Harness | Entry file | Kewajiban skill/capability |
| :--- | :--- | :--- |
| Claude Code | `CLAUDE.md` → `AGENTS.md` | Muat `aeterna-task-protocol` bila skill system tersedia; jika tidak, baca file ini + `AUTONOMOUS_BUILDER.md`. |
| Codex CLI | `AGENTS.md` | Sama; patuhi `skills_loaded` / `fallback_docs_read`. |
| DeepSeek harness | `AGENTS.md` | Sama; tidak boleh mengklaim skill yang tidak tersedia. |
| Antigravity CLI | `AGENTS.md` | Sama. |
| OpenCode | `AGENTS.md` + `opencode.json` | Skill `aeterna-*` diizinkan; `aeterna-task-protocol` kanonik. |
| Generic agentic CLI | `AGENTS.md` | Jika tidak bisa membaca file atau menjalankan command → `BLOCKED`. |

Deklarasi wajib di `context_manifest`:

```yaml
skills_loaded: ["aeterna-task-protocol"]
fallback_docs_read: []
builder_harness: claude-code | codex-cli | deepseek-harness | antigravity-cli | opencode | generic
```

Jika skill system tidak tersedia:

```yaml
skills_loaded: []
fallback_docs_read:
  - ".opencode/skills/aeterna-task-protocol/SKILL.md"
  - "docs/aeterna/AUTONOMOUS_BUILDER.md"
  - "VERIFY.md"
```

## 4. Definition of Ready (DoR)

Sebuah task packet dinyatakan `READY` hanya jika semua berikut terpenuhi:

1. `task_id`, `tier`, `target_milestone`, `target_branch`, `base_commit`, dan `builder_harness` terisi.
2. `base_commit` adalah ancestor dari `HEAD` saat packet dibuat.
3. `covers_req` memetakan ke `docs/aeterna/requirements.md`.
4. Scope adalah whitelist eksplisit, maksimal **3 file** dan **< 300 baris** diff.
5. `Forbidden Scope` menyebut file safety-critical yang dilarang disentuh tanpa instruksi eksplisit.
6. RTM memiliki `REQ ID → implementasi → test case → target output`.
7. Hard invariants numerik dicantumkan dari `invariant-cheatsheet.md`, bukan dari ingatan.
8. Test matrix memuat unit, golden/edge case bila relevan.
9. `acceptance_commands` bisa dijalankan tanpa input manusia dan menyertakan runner resmi: `uv run`, `cargo`, `go`.
10. Side-effect declaration mengisi `NONE` atau daftar perubahan kontrak yang disetujui.
11. Untuk refactor, characterization test eksisting wajib disebut path-nya.
12. Git protocol ditentukan: branch `feat/m<Milestone>-<slug>` untuk Tier A/B, commit conventional, PR via `gh pr create` bila tersedia.
13. Verification mandate menuntut raw output + `Verification Audit Report`.
14. Tidak ada kredensial, token, account ID, server broker, atau data pribadi di packet.
15. `next_action` menyebut phase aktif, gate yang belum lulus, dan uji termurah berikutnya bila packet berupa diskusi/perencanaan.

## 5. Numeric & Safety Budgets

| Item | Limit | Alasan |
| :--- | :--- | :--- |
| File per task | ≤ 3 | Reviewability dan blast radius. |
| Diff per task | < 300 lines | Menjaga diff surgical. |
| Fungsi | < 50 lines | Clean code gate. |
| Nesting | ≤ 4 | Kompleksitas kognitif. |
| Risk per trade | `0.5%` | Invariant absolut. |
| Daily loss | `2.0%` | Circuit breaker. |
| Hard drawdown | `10.0%` | Killswitch. |
| Posisi aktif | `1` | Invariant absolut. |
| Trade/hari | `5` | Invariant absolut. |
| Min R:R | `2.0` | Invariant absolut. |
| LLM produksi | `0` | Determinism. |
| Port 20128 | Do not kill | Tier 0. |

## 6. Procedure — Authoring

1. Baca `docs/aeterna/agent-state.md`; pastikan `active_task` dan `allowed_paths` sesuai permintaan operator.
2. Baca `docs/aeterna/invariant-cheatsheet.md` dan salin konstanta yang relevan.
3. Baca `docs/aeterna/task-packet-template.md` (alias lama: `docs/aeterna/omp-task-template.md`).
4. Petakan requirement ke file dan test; isi RTM.
5. Tetapkan `allowed_paths`, `Forbidden Scope`, dan diff budget.
6. Tulis `acceptance_commands` dengan runner resmi.
7. Tulis side-effect declaration.
8. Tulis packet ke `.handoff/tasks/TASK-M<X>-<YY>.md`.
9. Perbarui `docs/aeterna/agent-state.md` bila packet menjadi `active_task`.

## 7. Procedure — Execution & Evaluation

1. Builder wajib membaca packet dari awal tanpa mengandalkan chat history.
2. Builder wajib deklarasi `skills_loaded` atau `fallback_docs_read`.
3. Sebelum edit: cek `git merge-base --is-ancestor <base_commit> HEAD`.
4. Sentuh hanya `allowed_paths`.
5. Jalankan seluruh `acceptance_commands` + cross-cutting checks dari `VERIFY.md`.
6. Tempel raw output apa adanya; dilarang merangkai angka tanpa perintah nyata.
7. Floating status:
   - `PASS` hanya jika return code 0, scope patuh, dan bukti lengkap.
   - `BLOCKED` jika command gagal, scope dilanggar, atau gate belum valid.
   - `NEEDS_DECISION` jika dokumen bertentangan atau izin tidak jelas.
8. Lead melakukan evidence review. Verifier independen wajib untuk Tier A, gate, keuangan, risiko, keamanan, atau kontradiksi.
9. Stop setelah PR. Merge manual oleh human operator. Dilarang `gh pr merge`, `git merge`, auto-merge.

## 8. Output Contract

```yaml
envelope:
  status: READY | BLOCKED | NEEDS_DECISION
  role: aeterna-lead | aeterna-<role>
  milestone: M<1-7>
  tier: A | B | C
  active_phase: P0 | P1 | P2 | P3 | P4
  gates_not_passed: [...]
  next_action: "<phase + cheapest test + gate reminder>"
context_manifest:
  skills_loaded: [...]
  fallback_docs_read: [...]
  builder_harness: <harness>
task_packet:
  path: .handoff/tasks/TASK-M<X>-<YY>.md
  status: READY | DRAFT | BLOCKED
  allowed_paths: [...]
  acceptance_commands: [...]
verification:
  raw_output_attached: true | false
  audit_report: PASS | FAIL | NOT_RUN
```

## 9. Self-Check

1. [ ] Apakah packet bisa dipahami tanpa riwayat chat?
2. [ ] Apakah semua file yang boleh disentuh ada di whitelist?
3. [ ] Apakah RTM dan test case spesifik?
4. [ ] Apakah invariant numerik disalin dari source of truth?
5. [ ] Apakah acceptance commands dapat dijalankan mesin?
6. [ ] Apakah deklarasi skill/fallback benar untuk harness yang dipakai?
7. [ ] Apakah side effects dan git protocol dinyatakan?
8. [ ] Apakah tidak ada kredensial/secret/account ID?

## 10. Failure Modes

- **Gejala**: Builder mengedit file di luar scope.  
  **Tindakan**: Tolak laporan, revert file di luar scope, ulangi verifikasi dari awal.
- **Gejala**: Builder mengklaim PASS tanpa raw output.  
  **Tindakan**: Status `BLOCKED`; minta command + output asli.
- **Gejala**: Agent mengaku memanggil skill yang tidak tersedia.  
  **Tindakan**: Status `BLOCKED`; wajib `fallback_docs_read`.
- **Gejala**: Packet menyuruh merge otomatis.  
  **Tindakan**: P0 violation; hapus instruksi, ganti dengan "stop after PR".

## 11. Legacy Compatibility

Skill lama `omp-task-protocol` tetap dikenali sebagai alias untuk konfigurasi lama. Jika diaktifkan, agent wajib langsung memuat/membaca `aeterna-task-protocol` dan mengabaikan identitas OMP sebagai pembatas scope.

## 12. Explicit Non-Authorization

Protokol ini bukan izin menulis kode, bukan izin order live, bukan izin publikasi, dan bukan pengganti approval manusia.
