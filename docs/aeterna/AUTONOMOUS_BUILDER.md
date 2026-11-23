# Autonomous Builder Contract — AETERNA Quant

Dokumen ini adalah kontrak eksekusi untuk builder otonom dari CLI mana pun: Claude Code, Codex CLI, OpenCode, Antigravity CLI, atau agen lain yang bisa membaca file, menjalankan perintah, dan menulis kode.

Root `AGENTS.md` adalah entrypoint netral. File ini adalah detail operasionalnya.

---

## 1. Supported Builder Harnesses

| CLI | Entry file yang dibaca | Catatan |
| :--- | :--- | :--- |
| Claude Code | `CLAUDE.md` → `AGENTS.md` | Jika `CLAUDE.md` tersedia, gunakan sebagai pointer. |
| Codex CLI | `AGENTS.md` | Ikuti kontrak root. |
| DeepSeek harness | `AGENTS.md` | Ikuti kontrak root; gunakan fallback bila skill system tidak ada. |
| OpenCode | `AGENTS.md` + `opencode.json` | Skill `aeterna-*` tersedia bila diizinkan; `aeterna-task-protocol` kanonik. |
| Antigravity CLI | `AGENTS.md` | Perlakukan sebagai kontrak utama. |
| Lainnya | `AGENTS.md` | Jika tidak bisa membaca file atau menjalankan command, `BLOCKED`. |

CLI tidak mengubah aturan kualitas. Tool boleh berbeda; bukti, scope, dan gate tetap sama.

### 1.1 Universal Skill Binding

Protokol kanonik untuk authoring dan evaluasi task packet adalah `aeterna-task-protocol` (`.opencode/skills/aeterna-task-protocol/SKILL.md`). Skill lama `omp-task-protocol` adalah alias deprecated, bukan pembatas harness.

Setiap harness wajib:

| Kebutuhan | Skill kanonik | Fallback bila skill system tidak tersedia |
| :--- | :--- | :--- |
| Task packet | `aeterna-task-protocol` | `.opencode/skills/aeterna-task-protocol/SKILL.md` + `docs/aeterna/task-packet-template.md` |
| Invariant | `aeterna-invariants` | `.opencode/skills/aeterna-invariants/SKILL.md` + `docs/aeterna/invariant-cheatsheet.md` |
| Gate | `aeterna-milestone-gate` | `.opencode/skills/aeterna-milestone-gate/SKILL.md` |
| Verifikasi | `aeterna-verify` | `VERIFY.md` + `docs/aeterna/clean-code-rules.md` |
| Handoff | `aeterna-handoff` | `.opencode/skills/aeterna-handoff/SKILL.md` |

Wajib melaporkan salah satu:

```yaml
skills_loaded: ["aeterna-task-protocol", "aeterna-invariants"]
fallback_docs_read: []
builder_harness: claude-code | codex-cli | deepseek-harness | antigravity-cli | opencode | generic
```

Atau:

```yaml
skills_loaded: []
fallback_docs_read:
  - ".opencode/skills/aeterna-task-protocol/SKILL.md"
  - "docs/aeterna/AUTONOMOUS_BUILDER.md"
  - "VERIFY.md"
builder_harness: <harness>
```

Dilarang mengklaim skill yang tidak tersedia. Output tanpa deklarasi ini berstatus `BLOCKED`.

---

## 2. Wajib Dibaca Sebelum Bekerja

Builder wajib membaca, dalam urutan ini:

1. `AGENTS.md`
2. `docs/aeterna/agent-state.md`
3. `docs/aeterna/invariant-cheatsheet.md`
4. `docs/aeterna/AUTONOMOUS_BUILDER.md`
5. `docs/aeterna/clean-code-rules.md`
6. `VERIFY.md`
7. Task packet di `task_packet` jika `active_task` tidak null

Jika `active_task: null`, builder **tidak boleh menulis kode**. Hanya audit read-only atau berhenti.

---

## 3. Gate Awal

Sebelum mengubah apa pun:

1. Cek `git merge-base --is-ancestor <base_commit> HEAD`.
2. Jika gagal → `BLOCKED`.
3. Cek `allowed_paths` pada state/task packet.
4. Jika path yang dibutuhkan tidak termasuk scope → `NEEDS_DECISION`.
5. Jika gate yang dibutuhkan task belum PASSED → `BLOCKED`.
6. Jika dokumen bertentangan → `NEEDS_DECISION`, jangan menebak.

---

## 4. Capability Mapping

### Jika CLI memiliki skill system

Gunakan skill yang tersedia:

| Kebutuhan | Skill |
| :--- | :--- |
| Task packet | `aeterna-task-protocol` |
| Invariant | `aeterna-invariants` |
| Gate / phase | `aeterna-milestone-gate` |
| Handoff | `aeterna-handoff` |
| Verifikasi | `aeterna-verify` / `verification-loop` |
| Bug sulit | `diagnose` |
| Keamanan/secret | `security-review` |
| TDD | `tdd-workflow` |
| Standar kode | `coding-standards` |
| API | `api-design` |
| Database | `backend-patterns` |

### Jika CLI tidak memiliki skill system

Baca file skill/doc setara sebagai teks biasa:

- `.opencode/skills/aeterna-task-protocol/SKILL.md`
- `.opencode/skills/aeterna-invariants/SKILL.md`
- `.opencode/skills/aeterna-milestone-gate/SKILL.md`
- `.opencode/skills/aeterna-verify/SKILL.md`
- `.opencode/skills/aeterna-handoff/SKILL.md`
- `docs/aeterna/task-packet-template.md`
- `docs/aeterna/clean-code-rules.md`
- `VERIFY.md`

Laporkan di `context_manifest`:

```yaml
skills_loaded: []
fallback_docs_read:
  - "docs/aeterna/clean-code-rules.md"
  - "VERIFY.md"
```

Tidak boleh mengklaim memanggil skill yang tidak tersedia.

---

## 5. Aturan Implementasi

1. **Scope ketat**: hanya `allowed_paths`.
2. **Diff minimum**: paling sedikit file dan baris yang mungkin.
3. **TDD/characterization**: tulis atau jalankan test relevan sebelum/bersamaan dengan implementasi.
4. **Satu perilaku per task**: jangan menggabungkan refactor dan fitur.
5. **Input boundary validation**: validasi data eksternal.
6. **Error handling eksplisit**: dilarang `except: pass`, `unwrap()` produksi, atau `_ = err`.
7. **Immutability default**: kembalikan objek baru, jangan mutate input.
8. **Tidak ada dependency baru** kecuali task packet mengizinkan.
9. **Tidak ada secret**: token, password, login, account ID, server broker tidak boleh masuk kode/test/log.
10. **Tidak ada LLM di jalur produksi**.
11. **Do Not Kill 9router port 20128**.
12. **Dilarang `order_send`, `PositionModify`, `gh pr merge`, `git merge`**.

---

## 6. Clean Code Gate

- Fungsi `< 50` baris.
- File `200–400` baris tipikal, maksimal `800`.
- Nesting `<= 4`.
- Typing eksplisit pada fungsi publik.
- Tanpa dead code, unused import, atau helper tanpa pemanggil.
- Lulus `ruff`, `pyright`, `clippy`, `go vet`, `go test`, `cargo test`, dan `pytest` sesuai stack yang disentuh.
- File baru wajib didaftarkan di `docs/aeterna/code-ownership.md`.

---

## 7. Verification Ladder

1. Builder menjalankan seluruh `acceptance_commands` dari task packet.
2. Builder menjalankan cross-cutting check:
   ```powershell
   uv run pytest tests/ -q
   uv run ruff check .
   uv run pyright
   git diff --check
   ```
3. Untuk Rust/Go, tambahkan:
   ```powershell
   cargo test --all
   cargo clippy -- -D warnings
   go test ./...
   go vet ./...
   ```
4. Raw output wajib ditempelkan apa adanya.
5. Jika gagal, perbaiki dalam scope lalu ulangi.
6. Jika tetap gagal → `BLOCKED` dengan failure dan command.

Self-verification bukan independent audit. Tier A/gate/security tetap memerlukan verifier independen atau human gate.

---

## 8. Git Protocol

Untuk Tier A/B:

```powershell
git checkout -b <target_branch> <base_commit>
# implement
git add <allowed_paths>
git commit -m "<type>(<scope>): <imperative summary>"
git push -u origin <target_branch>
gh pr create --title "<type>(<scope>): <summary>" --body "<report-back>"
```

Stop setelah PR. Merge hanya human operator.

Development source of truth adalah repo GitHub `AETERNA` (beta). `OpenAeterna` adalah repositori release/publik dan bukan target push development harian. Jangan push update development ke `OpenAeterna`; hanya operator yang boleh membuat rilis resmi. Lihat `docs/aeterna/REPO_BOUNDARY.md`.

Jika CLI tidak memiliki `gh`, lapsi PR manual ke operator dan jangan push langsung ke `main`.

---

## 9. Report-Back Contract

Gunakan envelope `docs/aeterna/agent-contract.md §7` dan sertakan:

1. Daftar file yang diubah/dibuat.
2. `context_manifest`.
3. `skills_loaded` atau `fallback_docs_read`.
4. `Verification Audit Report`.
5. Raw output seluruh acceptance commands.
6. Clean code checklist.
7. Side effects.
8. Deviasi atau `BLOCKED`/`NEEDS_DECISION` bila ada.
9. Nomor PR atau alasan PR tidak dibuat.

Dilarang mengklaim PASS tanpa output asli.

---

## 10. Definition of Done

Task selesai hanya jika:

- Scope patuh.
- Semua acceptance commands return code 0.
- RTM diperbarui bila task menyentuh requirement.
- File baru terdaftar di ownership.
- Tidak ada secret/artifact privat yang ter-stage.
- PR dibuat atau alasan blocker jelas.
- Envelope final dikirim.

Tanpa salah satu di atas → status bukan selesai.
