# ADR Index

This directory holds the stable architecture decision records for `marten-runtime`.

Use ADRs for decisions that should not drift casually:

- runtime boundaries
- default capability exposure rules
- subsystem role boundaries
- long-lived constraints that future agents must preserve

## How To Read These

Start here when you need the durable architecture baseline:

1. [0001-thin-harness-boundary.md](./0001-thin-harness-boundary.md)
2. [0002-progressive-disclosure-default-surface.md](./0002-progressive-disclosure-default-surface.md)
3. [0003-self-improve-runtime-learning-not-architecture-memory.md](./0003-self-improve-runtime-learning-not-architecture-memory.md)
4. [0004-llm-first-tool-routing-boundary.md](./0004-llm-first-tool-routing-boundary.md)
5. [../../ARCHITECTURE_CHANGELOG.md](../../ARCHITECTURE_CHANGELOG.md)

## Conventions

- ADRs are append-new, not overwrite-history.
- Use one ADR per stable decision boundary.
- If the boundary changes later, add a new ADR or a superseding section instead of silently rewriting old intent.
- Use `docs/ARCHITECTURE_CHANGELOG.md` to record when a decision entered the baseline and what verification proved it.
