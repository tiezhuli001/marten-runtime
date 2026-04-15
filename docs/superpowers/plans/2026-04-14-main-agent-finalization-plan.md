# Main Agent Finalization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the `example_assistant` -> `main_agent` and `assistant` -> `main` transition so the repository has a clean, explicit main-agent baseline with intentional compatibility boundaries and minimal naming drift.

**Architecture:** Keep the current runtime behavior stable: `main_agent` remains the default app, `main` remains the default agent id, and legacy `assistant` stays only as a narrow compatibility alias where old callers may still exist. Finish by separating active truth, compatibility seams, and archive/history wording so future work has a clean baseline.

**Tech Stack:** Python 3.11+, unittest, TOML config, Markdown docs/skills

---

## Chunk 1: Baseline audit and compatibility boundary lock

### Task 1: Inventory remaining `assistant` references and classify them

**Files:**
- Modify: `STATUS.md`
- Inspect: `README.md`, `README_CN.md`, `docs/**`, `config/**`, `apps/**`, `skills/**`, `src/**`, `tests/**`

- [ ] **Step 1: Run a repo-wide grep for `assistant` and `example_assistant`**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "assistant|example_assistant" README.md README_CN.md docs config apps skills src tests
```
Expected: returns a mix of active references, compatibility seams, role-name references, and archive/history references.

- [ ] **Step 2: Classify each remaining hit into one of four buckets**

Buckets:
- active truth that should now say `main` / `main_agent`
- intentional compatibility alias (`assistant` still accepted)
- role-name / message-role usage (`role="assistant"`) that must stay unchanged
- archive/history/reference evidence that should stay unchanged

- [ ] **Step 3: Update `STATUS.md` with the classification result**

Expected: `STATUS.md` records exactly what remains and why.

### Task 2: Lock the compatibility policy in docs

**Files:**
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Add one explicit note that `assistant` is now compatibility-only, not baseline truth**
- [ ] **Step 2: Re-run a focused grep to confirm the docs use `main` / `main_agent` for active truth**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "default assistant|assistant-visible|assistant-facing" README.md docs skills
```
Expected: only archive/history or zero hits.

## Chunk 2: Compatibility seam cleanup

### Task 3: Review the runtime alias implementation for minimum necessary scope

**Files:**
- Modify: `src/marten_runtime/agents/registry.py`
- Test: `tests/test_router.py`
- Test: `tests/contracts/test_runtime_contracts.py`

- [ ] **Step 1: Write/adjust failing tests if alias scope needs tightening**
- [ ] **Step 2: Confirm only legacy agent-id lookup uses the alias, not unrelated semantics**
- [ ] **Step 3: Keep the alias map as small and explicit as possible**
- [ ] **Step 4: Re-run targeted routing/contract tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_router tests.contracts.test_runtime_contracts
```
Expected: PASS.

### Task 4: Check whether external input normalization also needs `assistant` -> `main` translation

**Files:**
- Inspect: `src/marten_runtime/interfaces/http/**`
- Inspect: `src/marten_runtime/gateway/**`
- Test: `tests/test_gateway.py`
- Test: `tests/contracts/test_gateway_contracts.py`

- [ ] **Step 1: Verify current gateway behavior is already covered by registry alias lookup**
- [ ] **Step 2: If any pre-registry normalization exists, ensure it does not reintroduce `assistant` as baseline truth**
- [ ] **Step 3: Re-run gateway tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_gateway tests.contracts.test_gateway_contracts
```
Expected: PASS.

## Chunk 3: Wording and naming cleanup outside archive

### Task 5: Finish active-surface wording cleanup

**Files:**
- Modify: `README.md`
- Modify: `README_CN.md` (if active wording still drifts)
- Modify: `docs/README.md`
- Modify: `skills/**/*.md`
- Modify: any active docs under `docs/` still using assistant-era wording for the default main agent

- [ ] **Step 1: Search for active wording like `assistant-facing`, `assistant-visible`, `default assistant`, `demo assistant persona`**
- [ ] **Step 2: Replace only active-truth wording with `main agent` semantics**
- [ ] **Step 3: Keep archive/history wording unchanged unless it falsely states current baseline truth**
- [ ] **Step 4: Re-run grep to confirm active-surface wording is clean**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "default assistant|assistant-visible|assistant-facing|demo assistant persona" README.md README_CN.md docs skills apps config src tests STATUS.md
```
Expected: only archive/history hits, or none.

## Chunk 4: Strong verification and closeout

### Task 6: Run targeted regression for renamed baseline

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: Run the renamed-baseline regression suite**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_router tests.test_bindings tests.test_acceptance tests.contracts.test_runtime_contracts tests.contracts.test_gateway_contracts tests.test_skills
```
Expected: PASS.

- [ ] **Step 2: If targeted regression is green, run the full suite**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v
```
Expected: PASS.

- [ ] **Step 3: Sync `STATUS.md` and `docs/ARCHITECTURE_CHANGELOG.md` with the final state**

Expected final state:
- default app baseline = `main_agent`
- default agent baseline = `main`
- `assistant` exists only as an intentional compatibility alias or as the LLM/chat role name
- active docs no longer describe the baseline as an assistant-first/demo-assistant system
