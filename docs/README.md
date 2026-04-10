# Docs Index

This directory contains the public design and operations notes for `marten-runtime`.

## Start Here

1. [../README.md](../README.md)
2. [ARCHITECTURE_EVOLUTION.md](./ARCHITECTURE_EVOLUTION.md)
3. [ARCHITECTURE_EVOLUTION_CN.md](./ARCHITECTURE_EVOLUTION_CN.md)
4. [ARCHITECTURE_CHANGELOG.md](./ARCHITECTURE_CHANGELOG.md)
5. [architecture/adr/README.md](./architecture/adr/README.md)
6. [2026-03-29-private-agent-harness-design.md](./2026-03-29-private-agent-harness-design.md)
7. [2026-03-30-conversation-lanes-provider-resilience-design.md](./2026-03-30-conversation-lanes-provider-resilience-design.md)
8. [2026-03-30-self-improve-design.md](./2026-03-30-self-improve-design.md)
9. [2026-03-31-progressive-disclosure-llm-first-capability-design.md](./2026-03-31-progressive-disclosure-llm-first-capability-design.md)
10. [2026-04-01-feishu-generic-card-protocol-design.md](./2026-04-01-feishu-generic-card-protocol-design.md)
11. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
12. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)
13. [archive/README.md](./archive/README.md)

## What Each File Is For

- `ARCHITECTURE_EVOLUTION.md` / `ARCHITECTURE_EVOLUTION_CN.md`
  - reader-first architecture evolution guides that explain the main runtime spine, stage boundaries, and why the current architecture looks the way it does
- `ARCHITECTURE_CHANGELOG.md`
  - append-only record of architecture evolution, why the baseline changed, and what verification proved it
- `architecture/adr/`
  - stable architecture decision records for non-drifting runtime boundaries and subsystem roles
- `2026-03-29-private-agent-harness-design.md`
  - product-direction and architecture decision for the first-wave private-agent harness
- `2026-03-30-conversation-lanes-provider-resilience-design.md`
  - current hardening design for same-conversation queueing and provider resilience
- `2026-03-30-self-improve-design.md`
  - design for the narrow self-improve loop, evidence store, lesson gate, and `SYSTEM_LESSONS.md` injection
- `2026-03-31-progressive-disclosure-llm-first-capability-design.md`
  - final design for shrinking capability exposure to skill summaries, capability catalog, and on-demand expansion
- `2026-04-01-feishu-generic-card-protocol-design.md`
  - current design for the Feishu-side minimal `feishu_card` protocol, generic renderer boundary, and LLM-first structured reply contract
- `CONFIG_SURFACES.md`
  - source-of-truth map for where each kind of config should live, including `*.example.toml` templates and local override files
- `LIVE_VERIFICATION_CHECKLIST.md`
  - operator checklist for the real `Feishu -> LLM -> MCP -> Feishu` chain
- `archive/`
  - historical audits and completed implementation plans that remain useful for traceability but are no longer the primary reading path

## Notes

- completed plans, completed slice designs, and one-off audits are moved under `docs/archive/` instead of competing with current source-of-truth and active docs
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
