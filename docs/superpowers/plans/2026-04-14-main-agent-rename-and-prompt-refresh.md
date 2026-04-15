# Main Agent Rename And Prompt Refresh Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the default app from `example_assistant` to `main_agent` and refresh the main agent prompt assets so the runtime default behaves like a primary execution agent instead of a demo assistant.

**Architecture:** Keep the existing app manifest and prompt assembly contract intact (`AGENTS.md` / `BOOTSTRAP.md` / `SOUL.md` / `TOOLS.md`). Change the default app identity at the app/config/runtime-default layer, then update prompt assets and tests so the renamed app stays the canonical runtime baseline.

**Tech Stack:** Python 3.11+, unittest, TOML config, Markdown prompt assets

---

## Chunk 1: Default app rename

### Task 1: Add failing coverage for the new default app id

**Files:**
- Modify: `tests/test_bootstrap_prompt.py`
- Modify: `tests/test_agent_specs.py`
- Modify: `tests/test_router.py`

- [ ] Step 1: update assertions/fixtures to expect `main_agent`
- [ ] Step 2: run the targeted unittest cases and confirm failure against the old baseline
- [ ] Step 3: update runtime defaults, app manifest references, and config defaults to `main_agent`
- [ ] Step 4: rerun the targeted unittest cases and confirm pass

### Task 2: Rename the default app directory and prompt asset root

**Files:**
- Move: `apps/example_assistant/` -> `apps/main_agent/`
- Modify: `apps/main_agent/app.toml`
- Modify: `src/marten_runtime/apps/runtime_defaults.py`
- Modify: `src/marten_runtime/agents/specs.py`
- Modify: `config/agents.toml`

- [ ] Step 1: rename the app directory after the tests are red
- [ ] Step 2: update manifest/default constants and config references
- [ ] Step 3: rerun the targeted unittest cases and confirm pass

## Chunk 2: Prompt refresh

### Task 3: Add failing prompt assertions for the new execution-agent language

**Files:**
- Modify: `tests/test_bootstrap_prompt.py`

- [ ] Step 1: add assertions that the assembled prompt contains the new main-agent positioning language
- [ ] Step 2: run the targeted prompt tests and confirm failure
- [ ] Step 3: rewrite `apps/main_agent/AGENTS.md`, `BOOTSTRAP.md`, `SOUL.md`, and `TOOLS.md`
- [ ] Step 4: rerun the targeted prompt tests and confirm pass

### Task 4: Update docs and compatibility references

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `docs/archive/audits/2026-03-31-repo-cleanup-audit.md`
- Modify: any test fixture or source default still using the old app id where the default app is semantically referenced

- [ ] Step 1: replace durable default-app references with `main_agent`
- [ ] Step 2: keep historical context intact where `example_assistant` is only mentioned as old state
- [ ] Step 3: run grep to confirm no active default-app references remain except historical notes

## Chunk 3: Verification and continuity

### Task 5: Run focused verification

**Files:**
- Modify: `STATUS.md`

- [ ] Step 1: run focused tests covering app manifest loading, prompt assembly, routing, runtime defaults, automation payload defaults, and runtime/tool flows touched by the rename
- [ ] Step 2: run a repo-wide grep for `example_assistant` and classify any surviving hits as intentional history vs missed active reference
- [ ] Step 3: update `STATUS.md` with completed work, verification commands, and any remaining drift notes
