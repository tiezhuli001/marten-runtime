# ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory

- Status: Accepted
- Date: 2026-03-31

## Context

`self_improve` records repeated failures, recoveries, candidate lessons, and accepted runtime lessons.

That mechanism is useful for operational learning, but it is the wrong place to store long-lived architecture truth:

- runtime lessons are scoped to execution behavior
- lesson quality is driven by observed failures and recoveries
- active lessons can change over time
- architecture boundaries need more stable, curated ownership

## Decision

`self_improve` remains a narrow runtime learning slice only.

It is allowed to store:

- failure and recovery evidence
- lesson candidates
- accepted active runtime lessons
- runtime-managed `SYSTEM_LESSONS.md`

It must not become:

- the repository architecture memory
- the canonical record of architecture decisions
- a generic long-term memory platform
- a place to store mutable product direction or source-of-truth architecture rules

Long-lived architecture truth moves to:

- `docs/architecture/adr/`
- `docs/ARCHITECTURE_CHANGELOG.md`

## Consequences

- `SYSTEM_LESSONS.md` should contain active runtime lessons only
- agents should not look to `self_improve` for stable architecture boundaries
- architecture drift should be corrected in ADRs or changelog entries, not by teaching the runtime a new lesson

## References

- [Architecture Changelog](../../ARCHITECTURE_CHANGELOG.md)
