# ADR 0001: Thin Harness Boundary

- Status: Accepted
- Date: 2026-03-31

## Context

`marten-runtime` is intended to be a private-agent runtime harness, not a general workflow platform or host-side decision engine.

Without an explicit boundary, the host tends to grow toward:

- message classification
- intent routing
- capability-specific branches
- policy centers
- orchestration frameworks

That drift makes the runtime thicker, harder to reason about, and more likely to duplicate model decisions.

## Decision

The host remains a thin harness.

The host is allowed to do only these classes of work:

- channel ingress and delivery
- binding and agent selection through declared routing rules
- runtime context assembly
- capability catalog rendering
- on-demand expansion and execution
- timeout, retry, and error normalization
- diagnostics and observability

The host must not become:

- a turn-level message classifier
- a host-side intent router
- a generic workflow or durable worker platform
- a mutable capability policy center
- a framework center that keeps absorbing domain decisions

## Consequences

- same-conversation serialization is acceptable as a runtime hardening primitive
- provider retry normalization is acceptable as a harness resilience primitive
- default capability exposure must stay declarative and family-level
- future features should be rejected if they require the host to decide what the model should think or select

## References

- [Private Agent Harness Design](../../2026-03-29-private-agent-harness-design.md)
- [Architecture Changelog](../../ARCHITECTURE_CHANGELOG.md)
