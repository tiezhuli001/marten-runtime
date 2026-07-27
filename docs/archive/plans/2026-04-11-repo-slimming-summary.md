# 2026-04-11 Repo Slimming Summary

This note keeps one historical outcome from the 2026-04-11 slimming round:

- the repository should stay centered on `channel -> binding -> runtime loop -> builtin tool / MCP / skill -> delivery / diagnostics`
- cleanup remains behavior-preserving and should prefer orphan helpers, false-alive tests, and unjustified wrappers before active seams
- archive stays small; durable truth belongs on the active docs path and in code/tests

Current sources of truth:

- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/architecture/adr/`
- `src/`
- `tests/`

The 2026-04-28 cleanup wave is compressed in `docs/archive/plans/2026-04-28-status-history-summary.md`.

Low-yield hold areas from the old review-core remain unchanged:

- `bootstrap-runtime`
- `sqlite-subsystem-growth`

Future slimming work should start from a fresh focused checklist rather than restoring the removed 2026-04-11 execution plans.

## Bootstrap Assembly Hygiene Outcome

The former 2026-04-01 bootstrap assembly plan has been absorbed here.

- HTTP bootstrap remains the composition root for runtime construction.
- Cohesive helpers own runtime assembly, capability registration, interactive dispatch, automation dispatch, and delivery wiring.
- Public construction entrypoints and `HTTPRuntimeState` contracts remain stable.
- Session queueing, tool registration, automation behavior, and Feishu delivery semantics remain protected by owner and contract tests.
- Structural extraction follows behavior-preserving verification and keeps runtime decisions inside the thin-harness boundary.
