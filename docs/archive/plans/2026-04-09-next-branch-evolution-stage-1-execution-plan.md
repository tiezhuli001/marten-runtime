# Next-Branch Evolution Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Stage 1 of the next `marten-runtime` evolution branch by locking the fast-path inventory baseline, locking current behavior with focused tests, and preparing a non-drifting implementation frontier for Stage 2.

**Architecture:** This plan follows `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md` and is intentionally pre-implementation. Stage 1 does not move runtime code across modules and does not finalize per-item fast-path keep/remove decisions. Its job is to produce the baseline and verification scaffolding that Stage 2 implementation will rely on.

**Tech Stack:** Python 3.12, `unittest`, FastAPI diagnostics routes, repository docs under `docs/`, runtime code under `src/marten_runtime/`, progress tracking in `STATUS.md`.

---

## Scope Guardrails

Re-read before executing:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-execution-plan.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/architecture/adr/0001-thin-harness-boundary.md`
- `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

Hard constraints:

- Do **not** remove any fast path in Stage 1.
- Do **not** finalize per-item fast-path retain/remove decisions in Stage 1.
- Do **not** perform function-level `runtime/loop.py` extraction in Stage 1.
- Do **not** create `route_hardening.py`, `direct_rendering.py`, `recovery_flow.py`, or `tool_outcome_flow.py` in Stage 1.
- Do **not** change runtime behavior except for tightly targeted test-only support if absolutely necessary.
- Every change must end with targeted verification.

---

## File Structure And Responsibilities

### Docs to create or modify

- Create: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
  - the Stage 1 source-of-truth inventory baseline
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`
  - keep the phase boundary explicit
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-execution-plan.md`
  - keep the umbrella plan aligned with stage entry points
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`
  - record Stage 1 progress and verification

### Runtime and tests that may be inspected or lightly updated

- Read / inspect: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Read / inspect: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Modify if a baseline-locking test gap is found:
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_gateway.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py`

---

## Verification Baseline

### Inventory / doc consistency checks

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
for path in [
    Path('docs/2026-04-09-next-branch-evolution-design.md'),
    Path('docs/2026-04-09-next-branch-evolution-execution-plan.md'),
    Path('docs/2026-04-09-next-branch-evolution-stage-1-execution-plan.md'),
]:
    text = path.read_text(encoding='utf-8')
    assert 'Stage 1' in text
    assert 'Stage 2' in text
    print(f'{path}: ok')
PY
```

### Narrow baseline-lock regression

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_contract_compatibility
```

### Contract / gateway support regression if Stage 1 tests change there

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_contract_compatibility tests.test_gateway
```

---

## Chunk 1: Build The Inventory Baseline

### Task 1: Enumerate all current fast paths and recovery-only shortcuts

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: List every current host-side fast path and recovery-only shortcut**
- [ ] **Step 2: Record trigger, owner, purpose, protected failure mode, and current test evidence for each item**
- [ ] **Step 3: Record the required live verification surface if each item changes later**
- [ ] **Step 4: Record Stage 2 placeholders only, not final retain/remove decisions**

### Task 2: Add the Stage 2 decision placeholders explicitly

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`

- [ ] **Step 1: Add a decision-status field for each item**
- [ ] **Step 2: Restrict allowed Stage 1 status values to `pending-stage-2-decision` or `evidence-incomplete`**
- [ ] **Step 3: Add a note that accepted-deviation decisions belong to Stage 2, not Stage 1**

---

## Chunk 2: Lock The Baseline With Tests

### Task 3: Verify whether Stage 1 needs new baseline-locking tests

**Files:**
- Read / optionally modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- Read / optionally modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`

- [ ] **Step 1: Map each inventoried seam to an existing test or a missing test**
- [ ] **Step 2: If a seam lacks a stable regression test, add the smallest focused test**
- [ ] **Step 3: Run the smallest new tests first**
- [ ] **Step 4: Re-run the narrow baseline-lock regression**

### Task 4: Lock diagnostics / contract truth as part of Stage 1 baseline

**Files:**
- Read / optionally modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`

- [ ] **Step 1: Ensure `/diagnostics/runtime` truthfulness assertions stay covered**
- [ ] **Step 2: Ensure no Stage 1 doc work weakened the diagnostics regression expectation**
- [ ] **Step 3: Re-run diagnostics/contract regression if any tests changed**

---

## Chunk 3: Prepare The Stage 2 Implementation Frontier

### Task 5: Write the explicit Stage 2 inputs without doing Stage 2 work

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-execution-plan.md`

- [ ] **Step 1: State that per-item fast-path decisions are a Stage 2 deliverable**
- [ ] **Step 2: State that function-level `runtime/loop.py` split blueprint is a Stage 2 deliverable**
- [ ] **Step 3: State that no agent may start code extraction from Stage 1 outputs alone**

### Task 6: Sync continuity and stop at the verified Stage 1 boundary

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

- [ ] **Step 1: Record what Stage 1 completed**
- [ ] **Step 2: Record what remains strictly Stage 2 work**
- [ ] **Step 3: Record exact verification commands and results**
- [ ] **Step 4: Mark Stage 1 complete only if all Stage 1 done criteria are satisfied**

---

## Stage 1 Done Criteria

Stage 1 is complete only when:

- the inventory baseline doc exists
- each inventoried item has evidence and a Stage 2 placeholder status
- baseline-locking tests are present for targeted seams
- no Stage 2 implementation work was started
- the relevant regressions passed
- `STATUS.md` reflects the verified Stage 1 boundary
