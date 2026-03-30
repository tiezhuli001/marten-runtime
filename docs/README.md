# Docs Index

This directory contains the public design and operations notes for `marten-runtime`.

## Start Here

1. [../README.md](../README.md)
2. [2026-03-29-private-agent-harness-design.md](./2026-03-29-private-agent-harness-design.md)
3. [2026-03-30-conversation-lanes-provider-resilience-design.md](./2026-03-30-conversation-lanes-provider-resilience-design.md)
4. [plans/2026-03-30-github-hot-repos-mvp-plan.md](./plans/2026-03-30-github-hot-repos-mvp-plan.md)
5. [plans/2026-03-30-conversation-lanes-provider-resilience-plan.md](./plans/2026-03-30-conversation-lanes-provider-resilience-plan.md)
6. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
7. [ARCHITECTURE_AUDIT.md](./ARCHITECTURE_AUDIT.md)
8. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)

## What Each File Is For

- `2026-03-29-private-agent-harness-design.md`
  - product-direction and architecture decision for the first-wave private-agent harness
- `2026-03-30-conversation-lanes-provider-resilience-design.md`
  - current hardening design for same-conversation queueing and provider resilience
- `plans/2026-03-30-github-hot-repos-mvp-plan.md`
  - active MVP implementation plan for chat-registered GitHub digest automations
- `plans/2026-03-30-conversation-lanes-provider-resilience-plan.md`
  - active implementation plan for same-conversation serialization and provider retry hardening
- `plans/2026-03-29-private-agent-harness-plan.md`
  - baseline milestone plan for the first-wave private-agent harness
- `ARCHITECTURE_AUDIT.md`
  - current-state audit of the implemented runtime versus the intended harness shape
- `CONFIG_SURFACES.md`
  - source-of-truth map for where each kind of config should live, including `*.example.toml` templates and local override files
- `LIVE_VERIFICATION_CHECKLIST.md`
  - operator checklist for the real `Feishu -> LLM -> MCP -> Feishu` chain

## Notes

- obsolete planning docs that no longer match the active baseline are intentionally removed instead of kept as in-repo history
- the remaining `plans/` files are either active implementation plans or still-useful operational references

## Current State

- Milestone A of the private-agent harness is implemented
- same-conversation FIFO queueing is implemented for HTTP `/messages` and Feishu interactive ingress
- durable session persistence is intentionally still pending
- Public docs are template-first and avoid local-only paths or secrets
