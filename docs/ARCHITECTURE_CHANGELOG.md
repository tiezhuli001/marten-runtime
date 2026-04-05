# Architecture Changelog

This file is the append-only architecture evolution log for `marten-runtime`.

Use it to answer:

- what architecture changed
- why the change happened
- which ADR or design doc is now authoritative
- what verification proved the new baseline

Do not use this file for day-to-day task tracking. Local continuity belongs in a local-only `STATUS.md`.

## Source Of Truth Rules

- Stable architectural decisions live in `docs/architecture/adr/`.
- Time-ordered architecture evolution is recorded here.
- Detailed execution history may still exist in local `STATUS.md`, but `STATUS.md` is not a repository source of truth.
- If a change updates the runtime boundary, default capability surface, or long-lived subsystem role, add an entry here.

## Entries

### 2026-04-05: GitHub Trending Became A Repo-Local MCP Sidecar Instead Of A Skill-Only Approximation

- Change:
  - added one repo-local stdio MCP sidecar at [github_trending.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/mcp_servers/github_trending.py)
  - the new sidecar exposes exactly one tool:
    - `trending_repositories`
  - registered the sidecar through [mcps.json](/Users/litiezhu/workspace/github/marten-runtime/mcps.json) instead of adding a runtime builtin or GitHub-specific routing branch
  - the temporary GitHub skill bridge was first narrowed and has now been removed; trending requests now rely on the MCP sidecar plus automation-boundary compatibility instead of a GitHub-specific skill file
- Why:
  - the upstream official GitHub MCP surface currently exposes repository search but not a real trending feed
  - using `search_repositories` plus prompt/skill rules was a semantic approximation and added avoidable LLM/tool turns
  - the thinner boundary is: model selects MCP → sidecar fetches/parses GitHub Trending → renderer formats result
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [2026-04-05 GitHub Trending MCP Plan](./archive/plans/2026-04-05-github-trending-mcp-plan.md)
- Verification:
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `269` tests green
  - live runtime diagnostics now discover `github_trending` with one tool `trending_repositories`
  - live request `帮我看下今天 github 热门仓库` on run `run_a2d2f279` used:
    - `mcp.list`
    - `mcp.call(server_id=github_trending, tool_name=trending_repositories)`
  - corrected live parse output now preserves canonical repo URLs and sane `stars_total` extraction from GitHub Trending HTML
  - live GitHub Trending HTML re-check on `2026-04-06` confirmed the returned list follows the official page order rather than a local descending-stars sort
  - latest Feishu wording now explicitly states `按 GitHub Trending 页面顺序` and avoids repeating fetched time in both the summary and the ordering note
### 2026-04-02: Feishu Outbound Rendering Settled On One Generic Renderer + One Thin Always-On Skill

- Change:
  - finalized the Feishu outbound boundary around:
    - one generic renderer in [rendering.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/rendering.py)
    - transport-only delivery in [delivery.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/delivery.py)
    - one thin always-on Feishu skill in [feishu_channel_formatting/SKILL.md](/Users/litiezhu/workspace/github/marten-runtime/skills/feishu_channel_formatting/SKILL.md)
  - the generic renderer now owns:
    - protocol parsing for observed provider output shapes
    - one schema `2.0` card skeleton
    - unified final/error card presentation
    - structured-reply canonicalization that strips duplicated visible bullets outside `feishu_card`
  - the Feishu skill now enforces the stable channel rule:
    - one-line direct answers may stay plain text
    - multi-line or grouped replies should end with one trailing `feishu_card`
  - no business-specific renderer taxonomy, delivery-side semantic classification, or host-side intent routing was introduced
- Why:
  - the real Feishu issues were a mix of presentation flatness, provider output drift, and duplicate visible content
  - those problems were best solved by strengthening one generic renderer and one thin channel skill, not by adding more renderer families or prompt-heavy host logic
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [Feishu Generic Card Protocol Design](./2026-04-01-feishu-generic-card-protocol-design.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_skills tests.test_contract_compatibility tests.test_runtime_loop -v`
    - pass
  - focused renderer regressions cover:
    - protocol-backed card rendering
    - inline / wrapped / invoke-style protocol parsing
    - one-line final and error card rendering
    - duplicate visible bullet stripping
  - local and live Feishu smoke confirmed the renderer path stays stable without widening the architecture

### 2026-04-01: `time` Capability Text Was Hardened For Natural-Language Clock Queries

- Change:
  - strengthened the `time` capability summary, usage rules, and tool description so natural-language clock requests like `现在几点` and `what time is it` explicitly route through the live `time` tool instead of relying on model memory
  - kept the fix inside capability/tool exposure text and did not add a new bootstrap-level intent rule or host-side router
- Why:
  - the previous live validation exposed a real prompt-to-tool compliance gap: the model sometimes answered current-time questions from stale memory
  - this boundary belongs in tool semantics, not in a widened bootstrap policy layer
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_runtime_capabilities tests.test_contract_compatibility tests.test_bootstrap_prompt tests.test_models -v`
    - pass, `44` tests green
  - focused live probes confirmed natural-language current-time requests now execute the `time` tool instead of answering from memory

### 2026-04-01: Repository Hygiene Boundaries Were Tightened

- Change:
  - added `apps/example_assistant/SYSTEM_LESSONS.md` to `.gitignore`
  - formalized `SYSTEM_LESSONS.md` as a runtime-managed artifact instead of a repository baseline file
  - introduced `docs/archive/` and moved completed one-off audits and the completed refinement plan out of the primary docs path
  - recorded the bootstrap cleanup plan at `docs/archive/plans/2026-04-01-bootstrap-assembly-hygiene-plan.md`
- Why:
  - runtime-generated files should not keep dirtying the repository after normal live runs
  - completed audits and plans were competing with current source-of-truth docs and active reading paths
  - the main remaining structural hotspot is `interfaces/http/bootstrap.py`, so the next active plan should focus there explicitly
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_bootstrap_prompt tests.test_self_improve_gate tests.test_contract_compatibility tests.test_skills -v`
  - docs and README entry paths now separate active docs from archive docs

### 2026-03-31: ADR + Architecture Changelog Becomes The Long-Term Source Of Truth

- Change:
  - introduced `docs/architecture/adr/` as the stable home for non-drifting architecture decisions
  - introduced this `docs/ARCHITECTURE_CHANGELOG.md` as the append-only architecture evolution log
  - moved repository continuity away from tracked `STATUS.md`; `STATUS.md` is now local-only and ignored by git
- Why:
  - `STATUS.md` was useful for active execution, but it mixed temporary task state with long-lived architecture truth
  - future agents need a durable source of truth for boundaries without replaying local execution history
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Supporting design docs:
  - [Private Agent Harness Design](./2026-03-29-private-agent-harness-design.md)
  - [Conversation Lanes And Provider Resilience Design](./2026-03-30-conversation-lanes-provider-resilience-design.md)
  - [Self-Improve Design](./2026-03-30-self-improve-design.md)
  - [Progressive Disclosure Capability Design](./2026-03-31-progressive-disclosure-llm-first-capability-design.md)
- Verification:
  - `PYTHONPATH=src python -m unittest -v`
  - docs index and live verification checklist updated to point at ADR + changelog rather than tracked `STATUS.md`

### 2026-03-31: Progressive Disclosure Refinement And Harness-Only Tightening Is The Current Baseline

- Change:
  - locked the default assistant-visible surface to five family entrypoints: `automation`, `mcp`, `self_improve`, `skill`, `time`
  - kept skill exposure as summary-first with body-on-demand
  - kept MCP exposure as family-level and server-summary-first, with detail and call on demand
  - removed remaining host-side keyword routing and extra prompt narration
- Why:
  - the runtime must stay a thin harness instead of drifting into host-side intent routing or a heavyweight capability framework
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
- Supporting design docs:
  - [Progressive Disclosure Capability Design](./2026-03-31-progressive-disclosure-llm-first-capability-design.md)
  - [Architecture Audit](./archive/audits/ARCHITECTURE_AUDIT.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_models tests.test_bootstrap_prompt tests.test_runtime_capabilities tests.test_contract_compatibility -v`
  - live probes confirmed plain chat, `time`, `mcp`, automation summary, and self-improve summary on the runtime path

### 2026-03-30: Conversation Lanes And Provider Resilience Became Part Of The Runtime Baseline

- Change:
  - added same-conversation FIFO queueing for HTTP and Feishu interactive ingress
  - added retry normalization for retryable provider transport and upstream failures
  - replaced placeholder queue diagnostics with live `conversation_lanes` diagnostics
- Why:
  - overlapping turns and provider jitter were destabilizing the live interactive chain
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
- Supporting design docs:
  - [Conversation Lanes And Provider Resilience Design](./2026-03-30-conversation-lanes-provider-resilience-design.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_runtime_lanes tests.test_gateway tests.test_feishu tests.test_provider_retry tests.test_runtime_loop tests.test_contract_compatibility -v`
  - `/diagnostics/queue` now returns live lane stats instead of placeholder output

### 2026-03-30: Self-Improve Was Accepted As A Narrow Runtime Learning Slice

- Change:
  - added failure/recovery evidence recording, candidate generation, lesson acceptance, and active lesson export through `SYSTEM_LESSONS.md`
  - kept self-improve scoped to runtime learning and candidate management, not generic memory or architecture truth
- Why:
  - the runtime needs a thin way to preserve recurring operational lessons without widening into a memory platform
- Source of truth:
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Supporting design docs:
  - [Self-Improve Design](./2026-03-30-self-improve-design.md)
- Verification:
  - self-improve tests and live runtime summary paths remain green
