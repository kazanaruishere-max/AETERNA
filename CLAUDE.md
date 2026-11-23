# Claude Code Entry — AETERNA Quant

This file is a pointer. The authoritative project contract is `AGENTS.md`.

Before doing any work, read in this order:

1. `AGENTS.md`
2. `docs/aeterna/agent-state.md`
3. `docs/aeterna/invariant-cheatsheet.md`
4. `docs/aeterna/REPO_BOUNDARY.md`
5. `docs/aeterna/AUTONOMOUS_BUILDER.md`
5. The task packet named in `agent-state.md`, if `active_task` is not null

If `active_task` is null, do not write code. Perform read-only audit or stop.

For builder tasks, follow `docs/aeterna/AUTONOMOUS_BUILDER.md` and the canonical `aeterna-task-protocol`. If the skill system is supported, load the available AETERNA skills; otherwise read the fallback docs and report `fallback_docs_read` plus `builder_harness: claude-code`.

Hard rules: respect `allowed_paths`, run all acceptance commands, attach raw output, never call `gh pr merge`, never write secrets, never stop 9router on port 20128, and stop after creating the PR.
