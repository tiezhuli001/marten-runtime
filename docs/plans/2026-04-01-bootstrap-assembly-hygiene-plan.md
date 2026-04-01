# Bootstrap Assembly Hygiene Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink `interfaces/http/bootstrap.py` from an all-in-one assembly hotspot into smaller runtime-wiring helpers without changing runtime behavior.

**Architecture:** Keep the current thin-harness semantics and public contracts intact. Only extract cohesive helpers around runtime assembly, tool registration, and dispatch/delivery wiring so `bootstrap.py` stops accumulating unrelated responsibilities.

**Tech Stack:** Python, unittest, current `marten-runtime` HTTP runtime bootstrap path

---

## Chunk 1: Responsibility Map

### Task 1: Freeze current behavior before refactor

**Files:**
- Test: `tests/test_contract_compatibility.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_feishu.py`

- [ ] **Step 1: Run the current targeted baseline**

Run: `PYTHONPATH=src python -m unittest tests.test_contract_compatibility tests.test_runtime_loop tests.test_feishu -v`
Expected: PASS

- [ ] **Step 2: Record the current responsibilities in `bootstrap.py`**

Capture these groups:
- runtime config + manifest assembly
- tool registry setup
- skill/MCP/self-improve/automation runtime wiring
- inbound interactive path
- automation dispatch path
- delivery path

### Task 2: Decide extraction boundaries

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Create: `src/marten_runtime/interfaces/http/bootstrap_helpers.py`

- [ ] **Step 1: Define one helper per cohesive responsibility**

Target helpers:
- `build_runtime_state_core(...)`
- `register_capability_tools(...)`
- `process_interactive_envelope(...)`
- `process_automation_dispatch(...)`

- [ ] **Step 2: Keep `HTTPRuntimeState` and external entrypoints stable**

No API changes to:
- `build_http_runtime(...)`
- `build_manual_automation_dispatch(...)`
- `_deliver_automation_events(...)`

## Chunk 2: Safe Extraction

### Task 3: Extract tool registration

**Files:**
- Create: `src/marten_runtime/interfaces/http/bootstrap_helpers.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Test: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Write a narrow regression if behavior changes**
- [ ] **Step 2: Move capability tool registration into helper functions**
- [ ] **Step 3: Re-run targeted tests**

Run: `PYTHONPATH=src python -m unittest tests.test_contract_compatibility -v`
Expected: PASS

### Task 4: Extract inbound and automation processing

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_helpers.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_feishu.py`

- [ ] **Step 1: Extract interactive processing helper without changing queueing/session semantics**
- [ ] **Step 2: Extract automation dispatch helper without changing Feishu delivery semantics**
- [ ] **Step 3: Re-run targeted tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_feishu -v`
Expected: PASS

## Chunk 3: Final Verification

### Task 5: Run full suite

**Files:**
- Test: `tests/`

- [ ] **Step 1: Run full repository tests**

Run: `PYTHONPATH=src python -m unittest -v`
Expected: PASS

- [ ] **Step 2: Update docs if helper extraction changes file ownership or reading path**

Files to check:
- `docs/README.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- local `STATUS.md`
