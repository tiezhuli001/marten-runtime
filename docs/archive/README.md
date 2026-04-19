# Archive Index

This directory holds completed plans and one-off audits that remain useful for traceability but are no longer part of the primary reading path.

## What Belongs Here

- completed implementation plans
- cleanup audits
- architecture audits that were superseded by ADRs plus `ARCHITECTURE_CHANGELOG.md`

## Current Archived Items

- `2026-03-31-agent-domain-query-adapter-design.md`
- `2026-03-31-automation-domain-adapter-design.md`
- `2026-04-06-thin-llm-context-compaction-design.md`
- `2026-04-07-context-usage-accuracy-design.md`
- `2026-04-07-llm-tool-episode-summary-design.md`
- `audits/ARCHITECTURE_AUDIT.md`
- `audits/2026-03-31-repo-cleanup-audit.md`
- `plans/2026-04-01-bootstrap-assembly-hygiene-plan.md`
- `plans/2026-04-01-feishu-message-pipeline-unification-plan.md`
- `plans/2026-04-05-github-trending-mcp-plan.md`
- `plans/2026-04-07-context-usage-accuracy-plan.md`
- `plans/2026-04-07-llm-tool-episode-summary-plan.md`
- `plans/2026-04-07-thin-llm-context-compaction-plan.md`
- `plans/2026-04-05-delete-github-hot-repos-digest-plan.md`
- `plans/2026-04-11-repo-slimming-summary.md`

## Archive Groups

- `branch-evolution/`
  - 2026-04-09 fast-path inventory / exit strategy, preserved as the only remaining branch-phase decision note from that slice

## Rules

- Do not treat archive docs as the current source of truth.
- Stable architecture truth lives in `docs/architecture/adr/` and `docs/ARCHITECTURE_CHANGELOG.md`.
- Archive is intentionally small; move docs here only when they still carry unique traceability value after summary-first consolidation.
- If a future cleanup or implementation plan is reopened, it should return to `docs/plans/`; otherwise completed plans stay archived here.

- some historical design docs were removed instead of archived once their durable truth was absorbed into ADRs and `docs/ARCHITECTURE_CHANGELOG.md`
- the 2026-04-01 runtime-latency / 2026-04-02 Feishu generic-renderer / 2026-04-07 tool-outcome-summary execution plans were removed after their durable truth was absorbed into code, tests, `docs/README.md`, and `docs/ARCHITECTURE_CHANGELOG.md`
- the 2026-04-09 branch-evolution design / blueprint docs were removed after their durable truth was absorbed into `docs/ARCHITECTURE_CHANGELOG.md`, `docs/ARCHITECTURE_EVOLUTION*.md`, and the retained fast-path inventory note
- the 2026-03-31 progressive-disclosure capability-refinement plan was removed after its remaining audit references were compressed into durable-truth pointers to ADR/changelog/evolution docs
