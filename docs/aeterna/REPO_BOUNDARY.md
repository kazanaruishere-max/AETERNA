# Repository Boundary Contract

Dokumen ini adalah sumber kebenaran untuk membedakan dua repositori AETERNA.

| Repository | Role | Isi | Push Rule |
| :--- | :--- | :--- | :--- |
| `AETERNA` | **Beta development source of truth** | README detail, task packets, agent state, research briefs, gate evidence, CI fixes, implementation history | Semua update development masuk ke sini |
| `OpenAeterna` | **Release/public artifact** | Clean source archive, README rilis ringkas, LICENSE, SECURITY, DISCLAIMER, VERIFY, CHANGELOG, release notes | Hanya official release tag oleh operator |

## AETERNA

Repositori ini adalah tempat kerja agent. Agent development boleh:

- membuat/mengubah task packet;
- update `docs/aeterna/agent-state.md`;
- menyimpan research brief;
- mengubah CI, docs internal, kode, test, dan infrastruktur sesuai scope;
- commit dan push ke `AETERNA` sesuai instruksi operator.

README di `AETERNA` harus **detail** dan menjelaskan arsitektur, workflow, invariant, perintah verifikasi, dan tata kelola development.

## OpenAeterna

Repositori ini adalah artifact rilis. Isinya harus bersih:

- tanpa `.env`, `.secrets.enc`, DB, logs, reports;
- tanpa `.handoff`, internal agent docs, task packets;
- tanpa data broker, equity, ticket, server, atau klaim performa;
- README rilis ringkas dan aman untuk publik.

Agent development **dilarang** push perubahan harian ke `OpenAeterna`. Push ke `OpenAeterna` hanya terjadi saat operator membuat rilis resmi.

## Agent Rule

Sebelum push, agent wajib:

1. `git remote -v`
2. verifikasi remote sesuai target yang diminta operator;
3. baca README repositori tersebut;
4. jika ragu, berhenti dan laporkan `NEEDS_DECISION`.

Jangan pernah menyamakan README `AETERNA` dan `OpenAeterna`. Keduanya melayani fase yang berbeda.
