# Docs Index

This directory contains the public design and operations notes for `marten-runtime`.

## Start Here

1. [../README.md](../README.md)
2. [2026-03-29-private-agent-harness-design.md](./2026-03-29-private-agent-harness-design.md)
3. [plans/2026-03-29-private-agent-harness-plan.md](./plans/2026-03-29-private-agent-harness-plan.md)
4. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
5. [ARCHITECTURE_AUDIT.md](./ARCHITECTURE_AUDIT.md)
6. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)

## What Each File Is For

- `2026-03-29-private-agent-harness-design.md`
  - product-direction and architecture decision for the first-wave private-agent harness
- `plans/2026-03-29-private-agent-harness-plan.md`
  - chunked implementation plan and milestone boundaries
- `ARCHITECTURE_AUDIT.md`
  - current-state audit of the implemented runtime versus the intended harness shape
- `CONFIG_SURFACES.md`
  - source-of-truth map for where each kind of config should live, including `*.example.toml` templates and local override files
- `LIVE_VERIFICATION_CHECKLIST.md`
  - operator checklist for the real `Feishu -> LLM -> MCP -> Feishu` chain

## Historical Plans

The `plans/` directory contains both active and historical execution plans.

- `2026-03-28-feishu-websocket-first-migration-plan.md`
  - historical record of the Feishu websocket cutover
- `2026-03-28-feishu-webhook-first-hardening-plan.md`
  - historical plan kept for context; it is not the active transport baseline
- `2026-03-29-feishu-live-verification-plan.md`
  - live verification runbook for real Feishu conversations

## Current State

- Milestone A of the private-agent harness is implemented
- Milestone B is intentionally still pending
- Public docs are template-first and avoid local-only paths or secrets
