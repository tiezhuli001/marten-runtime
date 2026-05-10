Date: 2026-04-28
Status: archived summary
Scope: completed deep repo cleanup wave

# 2026-04-28 Deep Repo Cleanup Summary

This note preserves the durable result of the 2026-04-28 cleanup wave. The active cleanup queue from that day has been executed, absorbed into architecture docs, or superseded by later branch work.

## Goal And Active Spine

The repository remains centered on:

`channel -> binding -> runtime loop -> builtin tool / MCP / skill -> delivery / diagnostics`

Cleanup decisions stay behavior-preserving and proof-driven. Runtime changes must keep message understanding, tool choice, and capability choice in the model path.

## Completed Work

- Removed stale adapter-wave archive docs after the direct-store runtime shape became the documented baseline.
- Removed stale GitHub hot repos digest execution plan after the MCP-first GitHub path became the active implementation.
- Retired the older aggressive cleanup checklist and kept this summary as the surviving 2026-04-28 cleanup note.
- Inlined the single-consumer subagent in-memory store into `src/marten_runtime/subagents/service.py`.
- Removed the isolated subagent-store test after owner assertions moved into service and integration suites.
- Reused shared Feishu test helpers where local duplicates only recorded delivered payloads.
- Thinned gateway / Feishu acceptance tests so smoke coverage stays in `tests/test_acceptance.py` and owner truth stays in lower-level suites.

## Surviving Contracts

- `SubagentService` owns bounded child task state and lifecycle transitions.
- `tests/test_acceptance.py` owns end-to-end smoke scenarios.
- Feishu rendering and delivery contracts live in `tests/feishu/` and related integration tests.
- Long-term architecture truth lives in `docs/ARCHITECTURE_CHANGELOG.md` and `docs/architecture/adr/`.

## Verification Retained From The Wave

- protected-core regression from the 2026-04-28 cleanup wave: pass.
- main-chain regression from the 2026-04-28 cleanup wave: pass.
- post-cleanup owner-bundle verification: pass.
- `compileall` and `git diff --check`: pass.
- simulated Feishu full-chain smoke covered plain chat, builtin tool, MCP multi-turn, skill, subagent, `session.new`, new-session follow-up, `session.resume`, and resumed-session follow-up.

## Current Successors

- architecture timeline: `docs/ARCHITECTURE_CHANGELOG.md`
- architecture decisions: `docs/architecture/adr/`
- docs index: `docs/README.md`
- cleanup history summary: `docs/archive/plans/2026-04-11-repo-slimming-summary.md`
