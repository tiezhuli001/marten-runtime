# Project AGENTS

## Purpose

`marten-runtime` is a lightweight agent runtime harness optimized for one narrow path:

`channel -> binding -> runtime loop -> builtin tool / MCP / skill -> delivery / diagnostics`

If a change does not make that path clearer, safer, or easier to operate, it is probably not a priority.

## Priority

Prefer work that improves:
- main-chain correctness
- operator clarity
- thin harness boundaries
- verification and diagnostics on the active runtime path

Treat as lower priority by default:
- workflow-platform expansion
- queue-first orchestration
- planner/swarm complexity
- broad historical cleanup that does not help the active chain

## Change Rules

- Preserve the main runtime path and its contracts first.
- Start each tracked change on a named work branch before editing files.
- Keep `main` as the clean integration baseline.
- Do not widen the control surface without a strong reason.
- Prefer narrow, local changes over broad refactors.
- Do not delete code only because it is large, old, or lightly documented.
- Prefer removing high-confidence orphan helpers, false-alive tests, and unjustified wrapper layers first.
- Treat support/helper splits as valid only when they carry clear ownership or reduce real complexity.
- Keep docs/archive work behind source-code and active-test cleanup unless docs are blocking execution.

## LLM-First Boundary

- Keep message understanding, intent recognition, tool selection, and capability choice in the LLM path.
- Keep host code focused on capability declaration, on-demand loading, execution, safety checks, retry, persistence, delivery, and diagnostics.
- Keep routing declarative through config, bindings, and metadata.
- Prefer prompt, skill, schema, and capability-catalog updates when behavior needs to improve.
- Prefer config and metadata tables when capability exposure needs to scale.
- Keep code-owned branching limited to runtime safety, auth, retry, delivery, persistence, and diagnostics.
- Review each new branch by checking whether it expresses runtime safety or model reasoning; model reasoning belongs in the LLM path.

## Verification

- Do not claim completion without running the smallest relevant verification.
- For deletions, verify the owner tests or contract tests that protect the surviving behavior.
- If a path is only suspicious and not proven, mark it `needs-proof` rather than forcing deletion.

## Safety

- Do not overwrite unrelated uncommitted user changes.
- Do not run destructive cleanup commands without explicit confirmation.
- Keep temporary analysis artifacts out of the repository unless the user explicitly asks to keep them.

## Repository Instruction Files

- `AGENTS.md` is a small project-constraint file, not a tool dump.
- Do not auto-generate `CLAUDE.md` in this repository.
- Do not append GitNexus or other tool-specific instruction blocks to `AGENTS.md`.
- If a tool needs local scratch output or indexes, keep them outside the repo.

## Reading Path

Start here when you need project context:
- `README.md`
- `docs/README.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/CONFIG_SURFACES.md`
- `docs/LIVE_VERIFICATION_CHECKLIST.md`
