# Docs Index

This directory contains the public design and operations notes for `marten-runtime`.

## Start Here

1. [../README.md](../README.md)
2. [ARCHITECTURE_CHANGELOG.md](./ARCHITECTURE_CHANGELOG.md)
3. [architecture/adr/README.md](./architecture/adr/README.md)
4. [2026-03-29-private-agent-harness-design.md](./2026-03-29-private-agent-harness-design.md)
5. [2026-03-30-conversation-lanes-provider-resilience-design.md](./2026-03-30-conversation-lanes-provider-resilience-design.md)
6. [2026-03-30-self-improve-design.md](./2026-03-30-self-improve-design.md)
7. [2026-03-31-agent-domain-query-adapter-design.md](./2026-03-31-agent-domain-query-adapter-design.md)
8. [2026-03-31-automation-domain-adapter-design.md](./2026-03-31-automation-domain-adapter-design.md)
9. [2026-03-31-progressive-disclosure-llm-first-capability-design.md](./2026-03-31-progressive-disclosure-llm-first-capability-design.md)
10. [plans/2026-04-01-bootstrap-assembly-hygiene-plan.md](./plans/2026-04-01-bootstrap-assembly-hygiene-plan.md)
11. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
12. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)
13. [archive/README.md](./archive/README.md)

## What Each File Is For

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
- `2026-03-31-agent-domain-query-adapter-design.md`
  - design for a thin domain-query adapter that keeps user-facing inspection on `agent + skill + builtin tool` rather than raw DB CRUD
- `2026-03-31-automation-domain-adapter-design.md`
  - design for moving the public automation resource layer onto the same thin adapter core without exposing scheduler internals or generic CRUD to the LLM
- `2026-03-31-progressive-disclosure-llm-first-capability-design.md`
  - final design for shrinking capability exposure to skill summaries, capability catalog, and on-demand expansion
- `plans/2026-04-01-bootstrap-assembly-hygiene-plan.md`
  - current active cleanup follow-up plan for shrinking the `interfaces/http/bootstrap.py` assembly hotspot without changing runtime behavior
- `CONFIG_SURFACES.md`
  - source-of-truth map for where each kind of config should live, including `*.example.toml` templates and local override files
- `LIVE_VERIFICATION_CHECKLIST.md`
  - operator checklist for the real `Feishu -> LLM -> MCP -> Feishu` chain
- `archive/`
  - historical audits and completed implementation plans that remain useful for traceability but are no longer the primary reading path

## Notes

- completed plans and one-off audits are moved under `docs/archive/` instead of competing with current source-of-truth and active docs
- tracked `STATUS.md` is no longer part of the repository source of truth; local continuity can still exist in an ignored local `STATUS.md`

## Current State

- Milestone A of the private-agent harness is implemented
- same-conversation FIFO queueing is implemented for HTTP `/messages` and Feishu interactive ingress
- the narrow self-improve loop is implemented: failure/recovery evidence persists in SQLite, candidate lessons are produced through a dedicated skill, accepted lessons are exported into runtime-managed `SYSTEM_LESSONS.md`
- the first thin domain-query adapter slice is implemented for `self_improve`: the assistant can list candidate lessons, inspect candidate detail, read self-improve summary, and delete bad candidates without raw DB exposure
- the automation resource layer is now adapter-backed as well: `list_automations`, `get_automation_detail`, `update_automation`, `delete_automation`, `pause_automation`, `resume_automation`, and the final write step of `register_automation` all converge on the same thin internal adapter while scheduler/trigger/dispatch stay in the automation subsystem
- live Feishu validation has already confirmed the self-improve candidate query/delete path on the real runtime chain; use `last_run_id -> diagnostics/run -> trace_id -> diagnostics/trace` for correlation
- stable architecture truth now lives in `docs/architecture/adr/` plus `docs/ARCHITECTURE_CHANGELOG.md`
- `apps/example_assistant/SYSTEM_LESSONS.md` is a runtime-managed artifact and is intentionally ignored by git
- durable session persistence is intentionally still pending
- Public docs are template-first and avoid local-only paths or secrets
