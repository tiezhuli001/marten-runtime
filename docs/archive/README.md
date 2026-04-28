# Archive Index

This directory holds a small set of historical documents kept only for audit traceability.

## What Stays Here

- superseded design history that still helps explain older code or cleanup decisions
- older cleanup / architecture audits
- a short list of archived execution plans whose durable truth already lives in active docs

## Current Groups

- root archived design notes:
  - `2026-04-06-thin-llm-context-compaction-design.md`
  - `2026-04-07-context-usage-accuracy-design.md`
  - `2026-04-07-llm-tool-episode-summary-design.md`
- `audits/`
  - older architecture and cleanup audits kept only when they still carry unique traceability
- `branch-evolution/`
  - one retained fast-path inventory note from the 2026-04-09 branch-evolution slice
- `plans/`
  - older archived execution plans that still provide traceability for pre-2026-04-14 work
  - the compressed `STATUS.md` history summary from 2026-04-28

## Removed After Absorption

The completed 2026-04-14 through 2026-04-25 plan/spec wave was removed on 2026-04-27 after its durable truth was absorbed into `README.md`, `docs/DEPLOYMENT*.md`, `docs/ARCHITECTURE_EVOLUTION*.md`, `docs/ARCHITECTURE_CHANGELOG.md`, and `docs/CONFIG_SURFACES.md`.

The 2026-03-31 adapter-wave archive trio was removed on 2026-04-28 after the direct-store runtime baseline became the only live control-plane shape in code, tests, `README.md`, `docs/README.md`, and `docs/ARCHITECTURE_CHANGELOG.md`.

## Rules

- Archive is not part of the primary reading path.
- Stable architecture truth lives in `docs/architecture/adr/` and `docs/ARCHITECTURE_CHANGELOG.md`.
- Active operator and deployment truth lives on the main docs path.
- Archive stays intentionally small.
