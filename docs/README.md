# Docs Index

This directory contains the public design and operations notes for `marten-runtime`.

## Start Here

1. [../README.md](../README.md)
2. [DEPLOYMENT.md](./DEPLOYMENT.md)
3. [DEPLOYMENT_CN.md](./DEPLOYMENT_CN.md)
4. [ARCHITECTURE_EVOLUTION.md](./ARCHITECTURE_EVOLUTION.md)
5. [ARCHITECTURE_EVOLUTION_CN.md](./ARCHITECTURE_EVOLUTION_CN.md)
6. [ARCHITECTURE_CHANGELOG.md](./ARCHITECTURE_CHANGELOG.md)
7. [architecture/adr/README.md](./architecture/adr/README.md)
8. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
9. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)
10. [archive/README.md](./archive/README.md)

## Architecture Reading Path

Use this order when you want both the current architecture and the evolution path:

1. `README.md`
   - current scope, runtime spine, deployment-facing entry points
2. `DEPLOYMENT*.md`
   - shortest deployment path, minimum config, startup, health checks, and optional integrations
3. `ARCHITECTURE_EVOLUTION*.md`
   - reader-first stage narrative for how the architecture reached its current boundary
4. `ARCHITECTURE_CHANGELOG.md`
   - append-only architecture timeline with proof and verification
5. `architecture/adr/`
   - stable constraints and accepted boundaries
6. `CONFIG_SURFACES.md`
   - configuration ownership for deployment
7. `LIVE_VERIFICATION_CHECKLIST.md`
   - live-chain validation and operator checks


## What Each File Is For

- `DEPLOYMENT.md` / `DEPLOYMENT_CN.md`
  - shortest deployment path for operators who want the simplest workable setup first and optional integrations second
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

- the primary documentation path is: `README -> docs/README -> DEPLOYMENT* -> ARCHITECTURE_EVOLUTION* -> ARCHITECTURE_CHANGELOG -> ADR -> CONFIG_SURFACES`
- architecture docs should make two things obvious: the current runtime spine and the stage-by-stage boundary changes that became baseline
- historical design/process docs are secondary; summarize durable truth into `ARCHITECTURE_CHANGELOG.md` before deciding whether a historical original still deserves archive space
- archive should stay intentionally small and should not become a graveyard for every stage plan or branch execution note
- the 2026-04-09 branch-evolution slice is now reduced to one retained archive note: `docs/archive/branch-evolution/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- the 2026-04-11 repo slimming work is now summarized in `docs/archive/plans/2026-04-11-repo-slimming-summary.md`; the current deep cleanup backlog lives in `docs/2026-04-28-deep-repo-cleanup-checklist.md`, and durable runtime conclusions live in `docs/ARCHITECTURE_CHANGELOG.md`
- the 2026-04-17 Langfuse observability design now lives in `docs/2026-04-17-langfuse-observability-design.md`; it records the original tracing design baseline for the now-implemented Langfuse runtime observability slice
- local ignored `STATUS.md` now stays as a compact branch execution board; architecture and operator truth stay on the active docs path, and compressed execution history lives in `docs/archive/plans/2026-04-28-status-history-summary.md`

## Current State

- the default runtime app is now `main_agent`; its prompt assets are tuned for an execution-first main agent rather than a demo helper persona
- Milestone A of the agent runtime harness is implemented
- same-conversation FIFO queueing is implemented for HTTP `/messages` and Feishu interactive ingress
- durable SQLite session persistence is now part of the baseline: session history, tool summaries, bindings, and compaction jobs survive restart, and `SessionStore` now stays as a contract seam rather than a second in-memory runtime engine
- selected-agent routing is now fully live: `requested_agent_id` can switch app manifest, bootstrap assets, allowed tool surface, and model profile through `config/agents.toml`
- the `session` family is now the explicit catalog and switch surface: `session.new` and `session.resume` keep restore bounded by one replay-turn budget and can enqueue source-session background compaction
- the thin `memory` builtin is active as one file-backed continuity slice under runtime ownership for explicit cross-session user facts and preferences; it stays separate from session history and self-improve lessons
- the narrow self-improve loop is implemented: failure/recovery evidence persists in SQLite, candidate lessons are produced through a dedicated skill, accepted lessons are exported into runtime-managed `SYSTEM_LESSONS.md`
- the default main agent can list candidate lessons, inspect candidate detail, read self-improve summary, and delete bad candidates without raw DB exposure through the narrow `self_improve` family surface
- the model-visible `automation` family tool now talks directly to the automation store for register/list/detail/update/delete/pause/resume, while manual trigger and isolated dispatch stay in the automation subsystem
- provider configuration is now split across `config/providers.toml` and `config/models.toml`; run diagnostics expose attempted profiles/providers and final provider selection for failover inspection
- the Feishu message pipeline unification and generic renderer iterations are complete enough to move into archive; current Feishu source-of-truth is the generic-card design doc plus `ARCHITECTURE_CHANGELOG.md`
- the current runtime latency breakdown slice is complete enough to move into archive; timing truth now lives in code, tests, and `ARCHITECTURE_CHANGELOG.md`
- the bootstrap assembly hygiene cleanup is complete enough to move into archive; current bootstrap truth now lives in code, tests, and `ARCHITECTURE_CHANGELOG.md`
- the April 14 to April 25 plan/spec wave has been absorbed into active docs; current runtime truth now lives in `README.md`, `DEPLOYMENT*.md`, `ARCHITECTURE_EVOLUTION*.md`, `ARCHITECTURE_CHANGELOG.md`, `CONFIG_SURFACES.md`, and code/tests
- `assistant` is no longer part of the routable runtime agent surface; active ingress and persisted runtime agent ids are canonicalized to `main`, and the active `spawn_subagent` ingress now keeps `standard` plus `brief_only` / `brief_plus_snapshot` as the only canonical child defaults
- live Feishu validation has already confirmed the self-improve candidate query/delete path on the real runtime chain; use `last_run_id -> diagnostics/run -> trace_id -> diagnostics/trace` for correlation
- Langfuse tracing is now implemented as an optional external observability surface: runtime diagnostics expose enabled/healthy/configured state, run and trace diagnostics expose Langfuse external refs, transient client errors degrade health without removing capability, and live validation has confirmed plain chat, multi-tool, and parent/child subagent traces against Langfuse cloud
- stable architecture truth now lives in `docs/architecture/adr/` plus `docs/ARCHITECTURE_CHANGELOG.md`
- `apps/main_agent/SYSTEM_LESSONS.md` is a runtime-managed artifact and is intentionally ignored by git
- thin LLM context compaction is now implemented as one thin long-thread continuity slice: only oversized conversation-history prefixes are rewritten, runtime scaffolding remains intact, and HTTP `/messages` persists/reuses compact checkpoints
- context-usage accuracy is now implemented as the current thin runtime baseline: provider actual usage is normalized first, tokenizer-family preflight estimates are computed from the final outbound payload, and deterministic rough fallback remains last-resort only
- thin cross-turn tool continuity now uses the LLM-first tool-episode-summary path on the main chain; deterministic extraction remains only as a thin fallback, and the earlier rules-first baseline is archived for traceability
- Public docs are template-first and avoid local-only paths or secrets
