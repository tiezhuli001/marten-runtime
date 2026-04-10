# Next-Branch Evolution Master Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use this single master document to execute the full next evolution branch for `marten-runtime`: preserve the Stage 1 verified baseline, perform Stage 2 controlled decomposition without goal drift, and keep all later slices aligned to one authoritative execution source.

**Architecture:** This plan follows `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`. It is an evidence-first evolution plan, not a redesign plan. Stage 1 is already completed and remains a verified baseline. Stage 2 is the current implementation frontier and must execute seam-by-seam under strict LLM-first and fail-closed boundaries. This document is now the sole execution entry; stage-specific docs remain as supporting references, not parallel execution plans.

**Tech Stack:** Python 3.12, `unittest`, FastAPI HTTP diagnostics routes, MCP integrations, repo docs under `docs/`, runtime code under `src/marten_runtime/`, continuity in `STATUS.md`.

---

## Scope Guardrails

Re-read before implementation:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/architecture/adr/0001-thin-harness-boundary.md`
- `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

Hard constraints:

- Do **not** add a planner, intent router, policy center, or generic classifier subsystem.
- Do **not** mix unrelated cleanup into this branch.
- Do **not** combine structural moves and instruction-wording changes in the same slice.
- Do **not** remove a fast path until its exit strategy, tests, and live checks are explicitly recorded.
- Do **not** start function-level extraction during Stage 1.
- Every slice must end with targeted verification.
- Final completion requires independent-port HTTP live verification.

## Authoritative Execution Rule

This document is the **single authoritative execution plan** for the next-branch evolution work.

Historical/supporting docs may still exist:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-1-execution-plan.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-execution-plan.md`

But those are now **reference baselines only**. They are not separate execution entry points.

All future execution, progress sync, drift checks, and implementation sequencing should anchor to **this** document plus:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

If any reference doc conflicts with this master plan, update the reference doc or `STATUS.md`; do not fork execution across multiple plans.

## Stage Status Snapshot

### Stage 1 — Completed baseline

Stage 1 is complete and remains the source-backed baseline:

1. fast-path inventory baseline created
2. baseline-lock tests added/tightened
3. diagnostics truthfulness locked
4. MiniMax-backed independent-port live verification has already been revalidated

Stage 1 must **not** be re-opened unless the baseline itself is proven stale.

### Stage 2 — Current execution frontier

Stage 2 is the current implementation frontier and must proceed in this order:

1. complete the per-item fast-path decision matrix
2. write the function-level `runtime/loop.py` split blueprint
3. execute the first approved seam extraction
4. verify each slice before any further movement

### Later slices

Any later slice beyond the currently approved Stage 2 seams must be appended to this document rather than introduced as a new standalone execution entry.

---

## Files And Responsibilities

### Design / progress docs

- Create: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-1-execution-plan.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

### Runtime seams likely to change in Stage 2 only

- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Create as needed under `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/`:
  - `route_hardening.py`
  - `direct_rendering.py`
  - `recovery_flow.py`
  - `tool_outcome_flow.py`

Only create modules that correspond to a real extracted seam. Do not create placeholder modules.

### Tests likely to change

- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`
- Modify as needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_gateway.py`
- Modify as needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py`

---

## Verification Baseline

### Narrow seam regression

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop
```

### Diagnostics and contract regression

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_contract_compatibility tests.test_gateway
```

### Required branch regression

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp tests.test_contract_compatibility
```

### Optional full confidence sweep if drift appears

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v
```

---

## Stage 1 Summary

Stage 1 consists only of:

1. fast-path inventory baseline
2. targeted baseline-locking tests
3. design/plan synchronization

Stage 1 must not move runtime code across modules.

## Stage 2 Summary

Stage 2 may begin only after Stage 1 is complete. Stage 2 consists of:

1. per-item fast-path decision matrix
2. function-level `runtime/loop.py` split blueprint
3. controlled implementation slices
4. full regression and live verification

Current Stage 2 non-negotiable boundaries:

- provider failures remain **fail-closed**
- LLM remains the core path
- no planner / intent-router / policy-center drift
- no code movement before decision matrix + split blueprint are written down
- Feishu-specific protocol logic should move toward the channel boundary only if behavior remains stable under tests and live verification
- duplicated pure `_is_*_query` helpers may converge into shared helper ownership only if the result stays a thin matcher layer rather than a new classifier subsystem

## Current Documentation Gaps Before Stage 2 Code Movement

The repo has already entered the **execution-ready Stage 2 design state**.

The previously missing documentation outputs are now present:

1. the fast-path inventory now includes the per-item Stage 2 decision matrix
2. the function-level `runtime/loop.py` split blueprint now exists at `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`
3. accepted-deviation recording is now written for the retained temporary deviations and mirrored into `docs/ARCHITECTURE_CHANGELOG.md`
4. the master plan below still contains historical Stage 1 execution chunks and must be read as:
   - historical baseline for Stage 1
   - active execution frontier for Stage 2

Stage 2 code extraction may start only from the first approved slice in the blueprint; no broader refactor is authorized.

## Historical Chunk 1: Stage 1 Inventory First, No Code Motion Yet

This chunk is a completed baseline record. It is kept here so later agents can see what Stage 1 actually locked.

Do **not** re-execute this chunk unless the Stage 1 baseline is proven stale.

### Task 1: Write the fast-path inventory and exit strategy document

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Enumerate all current fast paths and recovery-only shortcuts**
- [ ] **Step 2: Record trigger, owner, evidence, and exit strategy for each item**
- [ ] **Step 3: Cross-check the inventory against existing tests and fill any obvious test gaps**
- [ ] **Step 4: Update `STATUS.md` to mark inventory as the branch baseline**

### Task 2: Lock the baseline with focused tests before decomposition

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`

- [ ] **Step 1: Add or tighten tests for every seam planned for extraction**
- [ ] **Step 2: Add or retain diagnostics assertions proving runtime server surface truthfulness**
- [ ] **Step 3: Run the narrowest new tests first and confirm they fail only for the intended gap**
- [ ] **Step 4: Run seam regression and record results in `STATUS.md`**

### Historical Stage 1 stopping rule

After Chunk 1 completes:

- update `STATUS.md`
- confirm Stage 1 done criteria from the design document
- stop and create the Stage 2 plan inputs instead of beginning code extraction immediately

---

## Active Stage 2 Execution Order (Authoritative)

The previously written per-chunk detail below had started to drift from the newer Stage 2 decision matrix and blueprint.

From this point forward, the **authoritative Stage 2 execution order** is the one frozen by:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-execution-plan.md`

That order is:

1. shared matcher convergence only
   - converge duplicated pure `_is_*_query` / normalization helpers into `query_hardening.py`
   - keep route policy in `loop.py`
2. Feishu guard migration sidecar
   - move Feishu protocol ownership toward the Feishu channel boundary only if replacement proof is real
3. deterministic direct-render extraction
4. recovery-only extraction, only if the seam remains thin after direct-render extraction
5. tool-outcome helper subset extraction, only if a clearly pure/near-pure subset still exists
6. full regression + independent-port live verification

### No formal Stage 3 in this branch

This branch currently defines only:

- **Stage 1**: completed baseline locking
- **Stage 2**: controlled implementation and verification

There is **no formal Stage 3** in the current design or execution contract.

If later work becomes necessary, it must be handled in exactly one of these two ways:

1. append another **later slice inside Stage 2** if it is still part of the same bounded evolution goal and still respects the current matrix/blueprint constraints
2. create a **future branch / future design doc** if the work would change the branch boundary, introduce a new architectural question, or require new evidence not yet available

### Why the docs do not “write all future stages now”

Because the current branch is intentionally **evidence-first**, not speculation-first.

Writing a hypothetical Stage 3 now would create three risks:

1. it would pretend we already know whether Stage 2 extractions stay thin enough in practice
2. it would encourage agents to keep refactoring past the verified boundary instead of stopping after the approved slices
3. it would mix confirmed branch scope with unverified future ideas, which is exactly the drift this doc set is trying to prevent

So the correct current rule is:

- write **all currently justified Stage 2 slices in full**
- do **not** invent a speculative Stage 3 before Stage 2 evidence exists

### Active implementation entry

If implementation starts now, the first approved slice is still:

- shared matcher convergence into `query_hardening.py`
- with route policy remaining in `loop.py`
- with `tests.test_query_hardening` as the first regression gate

### Active verification rule

After every Stage 2 slice:

- run targeted tests first
- then run broader regression if the seam changed external behavior
- rerun independent-port live verification for any `/messages` behavior change
- update `STATUS.md` before starting the next slice

## Done Criteria

This plan is complete only when:

- inventory doc exists and is accurate
- planned safe seams were extracted without goal drift
- capability/instruction/channel boundaries were tightened in isolated slices
- targeted tests passed after each slice
- required branch regression passed
- independent-port live verification passed across plain, builtin, MCP, and skill flows
- `STATUS.md` reflects reality
