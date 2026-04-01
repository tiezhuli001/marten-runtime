# ADR 0002: Progressive Disclosure Default Surface

- Status: Accepted
- Date: 2026-03-31

## Context

As skill count and MCP surface area grow, default full expansion causes prompt bloat, unstable tool surfaces, and pushes the host toward routing shortcuts.

The runtime needs a default shape that stays compact while still letting the model use the right capability when needed.

## Decision

The default capability surface is progressive-disclosure-first.

The stable default model-visible surface is:

- `automation`
- `mcp`
- `self_improve`
- `skill`
- `time`

The default exposure rules are:

- skills are visible as summaries first
- skill bodies load only on demand through the `skill` family tool
- MCP stays family-level first
- MCP server summaries are visible by default
- MCP tool details are inspected on demand
- concrete MCP tools are not leaked into the default first-round surface

The host declares the capability catalog, but the model chooses whether to expand or call.

## Consequences

- plain chat does not require a host-side intent router
- MCP tool names should not appear as the default user-visible contract
- capability declarations should remain static metadata reuse, not grow into a registry or router
- tests and acceptance coverage must align to the family-level contract instead of old concrete-tool assumptions

## References

- [Progressive Disclosure Capability Design](../../2026-03-31-progressive-disclosure-llm-first-capability-design.md)
- [Architecture Audit](../../archive/audits/ARCHITECTURE_AUDIT.md)
- [Architecture Changelog](../../ARCHITECTURE_CHANGELOG.md)
