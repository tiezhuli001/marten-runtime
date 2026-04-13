# Docs Index

This directory contains the public design and operations notes for `marten-runtime`.

## Start Here

1. [../README.md](../README.md)
2. [ARCHITECTURE_EVOLUTION.md](./ARCHITECTURE_EVOLUTION.md)
3. [ARCHITECTURE_EVOLUTION_CN.md](./ARCHITECTURE_EVOLUTION_CN.md)
4. [ARCHITECTURE_CHANGELOG.md](./ARCHITECTURE_CHANGELOG.md)
5. [architecture/adr/README.md](./architecture/adr/README.md)
6. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
7. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)
8. [archive/README.md](./archive/README.md)

## What Each File Is For

- `ARCHITECTURE_EVOLUTION.md` / `ARCHITECTURE_EVOLUTION_CN.md`
  - reader-first architecture evolution guides that explain the main runtime spine, stage boundaries, and why the current architecture looks the way it does
- `ARCHITECTURE_CHANGELOG.md`
  - append-only record of architecture evolution, why the baseline changed, and what verification proved it; this is the primary timeline-truth document
- `architecture/adr/`
  - stable architecture decision records for non-drifting runtime boundaries and subsystem roles
- `CONFIG_SURFACES.md`
  - source-of-truth map for where each kind of config should live, including `*.example.toml` templates and local override files
- `LIVE_VERIFICATION_CHECKLIST.md`
  - operator checklist for the real `Feishu -> LLM -> MCP -> Feishu` chain
- `archive/`
  - a small set of historical audits and completed plans that still carry unique traceability value; archive is intentionally not the default home for every old process document

## Notes

- the primary documentation path is: `README -> docs/README -> ARCHITECTURE_EVOLUTION* -> ARCHITECTURE_CHANGELOG -> ADR -> CONFIG_SURFACES`
- historical design/process docs are secondary; summarize durable truth into `ARCHITECTURE_CHANGELOG.md` before deciding whether a historical original still deserves archive space
- archive should stay intentionally small and should not become a graveyard for every stage plan or branch execution note
- the 2026-04-09 next-branch evolution design/execution/blueprint docs now live under `docs/archive/branch-evolution/` and are no longer part of the default reading path
- the 2026-04-11 repo slimming work is now summarized in `docs/archive/plans/2026-04-11-repo-slimming-summary.md`; durable conclusions live in `docs/ARCHITECTURE_CHANGELOG.md` and the module review docs under `docs/review/`
- tracked `STATUS.md` is no longer part of the repository source of truth; local continuity can still exist in an ignored local `STATUS.md`

## Current State

- Milestone A of the private-agent harness is implemented
- same-conversation FIFO queueing is implemented for HTTP `/messages` and Feishu interactive ingress
- the narrow self-improve loop is implemented: failure/recovery evidence persists in SQLite, candidate lessons are produced through a dedicated skill, accepted lessons are exported into runtime-managed `SYSTEM_LESSONS.md`
- the first thin domain-query adapter slice is implemented for `self_improve`: the assistant can list candidate lessons, inspect candidate detail, read self-improve summary, and delete bad candidates without raw DB exposure
- the automation resource layer is now adapter-backed as well: the model-visible `automation` family tool converges on the same thin internal adapter for register/list/detail/update/delete/pause/resume while scheduler/trigger/dispatch stay in the automation subsystem
- the Feishu message pipeline unification and generic renderer iterations are complete enough to move into archive; current Feishu source-of-truth is the generic-card design doc plus `ARCHITECTURE_CHANGELOG.md`
- the current runtime latency breakdown slice is complete enough to move into archive; timing truth now lives in code, tests, and `ARCHITECTURE_CHANGELOG.md`
- the bootstrap assembly hygiene cleanup is complete enough to move into archive; current bootstrap truth now lives in code, tests, and `ARCHITECTURE_CHANGELOG.md`
- the two adapter design docs are now archived as completed design history; current automation/self-improve truth lives in code, tests, `CONFIG_SURFACES.md`, and `ARCHITECTURE_CHANGELOG.md`
- live Feishu validation has already confirmed the self-improve candidate query/delete path on the real runtime chain; use `last_run_id -> diagnostics/run -> trace_id -> diagnostics/trace` for correlation
- stable architecture truth now lives in `docs/architecture/adr/` plus `docs/ARCHITECTURE_CHANGELOG.md`
- `apps/example_assistant/SYSTEM_LESSONS.md` is a runtime-managed artifact and is intentionally ignored by git
- durable session persistence is intentionally still pending
- thin LLM context compaction is now implemented as one thin long-thread continuity slice: only oversized conversation-history prefixes are rewritten, runtime scaffolding remains intact, and HTTP `/messages` persists/reuses compact checkpoints
- context-usage accuracy is now implemented as the current thin runtime baseline: provider actual usage is normalized first, tokenizer-family preflight estimates are computed from the final outbound payload, and deterministic rough fallback remains last-resort only
- thin cross-turn tool continuity now uses the LLM-first tool-episode-summary path on the main chain; deterministic extraction remains only as a thin fallback, and the earlier rules-first baseline is archived for traceability
- Public docs are template-first and avoid local-only paths or secrets
