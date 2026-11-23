---
name: omp-task-protocol
description: Deprecated compatibility alias. Canonical harness-neutral protocol is aeterna-task-protocol.
license: AGPL-3.0-only
compatibility: universal
metadata:
  status: DEPRECATED_ALIAS
  canonical_skill: aeterna-task-protocol
  protocol_version: "2.0.0"
---

# Deprecated Alias — omp-task-protocol

Skill ini dipertahankan hanya untuk konfigurasi lama. OMP bukan satu-satunya builder yang diizinkan.

Jika skill ini termuat:

1. Segera muat skill kanonik `aeterna-task-protocol`.
2. Jika skill system tidak mendukung pemuatan lanjutan, baca sebagai teks:
   - `.opencode/skills/aeterna-task-protocol/SKILL.md`
   - `docs/aeterna/AUTONOMOUS_BUILDER.md`
3. Terapkan protokol kanonik verbatim.
4. Laporkan:
   ```yaml
   skills_loaded: ["omp-task-protocol", "aeterna-task-protocol"]
   canonical_protocol: "aeterna-task-protocol"
   ```

Dilarang membuat task packet bertema OMP-only. Dilarang menyatakan builder harus memakai OMP. Builder mana pun yang mematuhi `AGENTS.md` dan protokol kanonik sah digunakan.
