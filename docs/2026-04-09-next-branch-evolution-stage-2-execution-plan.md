# Next-Branch Evolution Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Stage 2 of the `marten-runtime` evolution branch without drifting away from the thin-harness boundary, the restored LLM-first runtime contract, or the Stage 1 verified baseline.

**Architecture:** Stage 2 is a controlled decomposition plan, not a redesign plan. It starts by converting the Stage 1 inventory into explicit per-item decisions, then produces a function-level split blueprint, then moves only one seam at a time with full regression and independent-port live verification after each meaningful slice. `runtime/loop.py` remains the orchestration owner throughout; helper extraction is allowed only when the extracted code is pure or near-pure and does not create a planner, intent subsystem, or policy center.

**Tech Stack:** Python 3.12, `unittest`, FastAPI HTTP runtime, MCP integrations, MiniMax-backed LLM profile (`minimax_coding`), repo docs under `docs/`, runtime code under `src/marten_runtime/`, continuity in `STATUS.md`.

---

## Stage 2 Entry Preconditions

Do **not** start implementation until all of the following are true and re-checked in the current workspace:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-execution-plan.md`
- `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

Current required truths before Stage 2 code movement:

- Stage 1 is complete and remains the source-backed baseline
- MiniMax provider is currently usable via the updated key
- provider failures must remain **fail-closed**; do not reintroduce degraded-success fallback behavior
- diagnostics runtime server surface must remain truthful for independent-port verification
- existing forced-route / direct-render behavior is baseline-locked by tests and inventory rows

If any of the above drifts, stop and update design/plan docs before code movement.

---

## Hard Guardrails

- Do **not** add a planner, intent router, policy center, or generic classifier subsystem.
- Do **not** convert Stage 2 into a broad cleanup branch.
- Do **not** combine behavioral tightening and structural extraction in the same slice.
- Do **not** reintroduce provider-auth or provider-transport degraded-success fallback behavior.
- Do **not** change `llm_request_count` semantics unless the slice explicitly targets that metric and has updated tests.
- Do **not** create placeholder helper modules just because the umbrella design mentioned them.
- Prefer extending an existing thin helper module over creating a new one when ownership is already close enough (for example `query_hardening.py`).
- After every slice, run targeted tests before any broader suite.
- After every slice that changes runtime behavior on `/messages`, rerun independent-port live verification.

---

## Required Stage 2 Outputs

Before Stage 2 is considered complete, it must produce all of the following:

1. a per-item fast-path decision matrix derived from the Stage 1 inventory
2. a function-level split blueprint for `runtime/loop.py`
3. one or more verified code slices implementing the approved extractions
4. updated `STATUS.md` recording exact commands, results, and remaining risks
5. a final independent-port live verification on `127.0.0.1:8001`

---

## File Structure And Ownership Targets

### Planning / continuity files

- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

### Runtime files that may change

- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Modify or extend if justified: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/query_hardening.py`
- Create only if an extracted seam is proven real and thin:
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/direct_rendering.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/recovery_flow.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/tool_outcome_flow.py`

### Tests that must remain aligned

- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`
- Modify as needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_gateway.py`
- Modify as needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py`
- Modify as needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_query_hardening.py`

---

## Verification Ladder

### Narrow targeted checks

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop
```

### Contract / diagnostics checks

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_contract_compatibility tests.test_gateway
```

### Runtime + MCP slice regression

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_runtime_mcp tests.test_contract_compatibility
```

### Required Stage 2 branch regression

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_query_hardening tests.test_llm_client tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp tests.test_contract_compatibility
```

### Independent-port live verification

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m uvicorn marten_runtime.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8001
```

Live matrix that must be rerun after any `/messages`-behavior slice:

- `GET /healthz`
- `GET /diagnostics/runtime`
- plain conversation
- builtin time query
- builtin runtime-context query
- GitHub MCP latest-commit query
- skill load query

For each live run, record:

- `run_id`
- final event type / text summary
- diagnostics `status`
- diagnostics `llm_request_count`
- diagnostics `tool_calls`

---

## Chunk 1: Decision Matrix Before Code Movement

### Task 1: Convert Stage 1 inventory into explicit Stage 2 decisions

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`

- [ ] **Step 1: Re-read every Stage 1 inventory row against the current codebase**
- [ ] **Step 2: Replace each `pending-stage-2-decision` with exactly one status**
  - `retain-now-with-explicit-deviation`
  - `extract-without-behavior-change`
  - `shrink-later-after-replacement-evidence`
  - `remove-when-replacement-verified`
- [ ] **Step 3: For every retained item, record why LLM-only handling is still insufficient or too risky**
- [ ] **Step 4: For every removable/shrinkable item, record the exact evidence required before removal**
- [ ] **Step 5: Add an explicit row note that provider failures remain fail-closed and are not eligible for degraded-success shortcuts**
- [ ] **Step 6: Update `STATUS.md` with the approved decision-matrix completion marker**

### Task 2: Record accepted deviations explicitly

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/docs/ARCHITECTURE_CHANGELOG.md`

- [ ] **Step 1: For every item retained as a conscious deviation, add a short rationale**
- [ ] **Step 2: Note the user-visible or live-chain risk if that deviation were removed too early**
- [ ] **Step 3: If the decision is effectively long-lived, mirror it into changelog/ADR-facing docs instead of leaving it only in a local note**

### Chunk 1 stopping rule

Do **not** move code until the matrix is complete, internally consistent, and reflected in `STATUS.md`.

---

## Chunk 2: Function-Level Split Blueprint

### Task 3: Write the `runtime/loop.py` split blueprint

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`

- [ ] **Step 1: Enumerate current helper clusters inside `runtime/loop.py` by responsibility**
  - forced-route selection
  - deterministic direct rendering
  - successful-tool-result recovery
  - provider-failure handling
  - tool-outcome summary composition
  - terminal failure emission
- [ ] **Step 2: Mark each helper cluster as one of**
  - `keep-in-loop`
  - `extract-now`
  - `extract-later`
- [ ] **Step 3: For every `extract-now` cluster, define target owner module and why the seam is thin enough**
- [ ] **Step 4: For every `keep-in-loop` cluster, explain what state/orchestration coupling still prevents safe extraction**
- [ ] **Step 5: For every approved extraction, define the exact regression set and live checks required after the move**
- [ ] **Step 6: Update `STATUS.md` with blueprint completion and the exact first code slice to execute**

### Task 4: Lock Stage 2 execution order

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`

- [ ] **Step 1: Freeze the slice order to avoid opportunistic refactoring**
- [ ] **Step 2: Require that direct-render extraction cannot begin before route-hardening extraction is verified**
- [ ] **Step 3: Require that recovery-flow extraction cannot begin before direct-render extraction is verified**
- [ ] **Step 4: Require that tool-outcome-flow extraction is skipped entirely if the blueprint shows it is still too coupled**

### Chunk 2 stopping rule

Do **not** start extraction until the blueprint names the exact helper group, target file, tests, and live verification matrix for the first slice.

---

## Chunk 3: First Implementation Slice — Pure Route Hardening

### Task 5: Extract only pure route-hardening helpers

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Prefer modify over create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/query_hardening.py`
- Create only if blueprint proves a distinct seam exists: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/route_hardening.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_query_hardening.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Write or tighten the narrowest tests for the pure matcher/eligibility seam**
- [ ] **Step 2: Run those tests first and verify red if behavior is not yet represented correctly**
- [ ] **Step 3: Move only pure matching / route-eligibility helpers**
- [ ] **Step 4: Keep top-level routing decisions in `loop.py`; do not create a new routing coordinator**
- [ ] **Step 5: Run `tests.test_query_hardening` and focused runtime-loop tests**
- [ ] **Step 6: Run contract regression if matcher semantics changed**
- [ ] **Step 7: Record exact moved helpers and evidence in `STATUS.md`**

### Slice-specific stop rule

If extraction requires passing runtime state objects, history handles, or orchestration callbacks into the new module, the seam is not pure enough; stop and keep that helper in `loop.py`.

### Task 5A: Converge duplicated pure `_is_*_query` helpers only if the seam stays thin

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/query_hardening.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_query_hardening.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Inventory all duplicated `_is_*_query`-style helpers and classify each one as pure matcher vs policy-bearing helper**
- [ ] **Step 2: Move only pure matcher / normalization logic into `query_hardening.py` or an equally thin shared helper boundary**
- [ ] **Step 3: Keep route ordering, family-tool selection, and explicit action policy in `loop.py`**
- [ ] **Step 4: Run `tests.test_query_hardening` first**
- [ ] **Step 5: Run focused `tests.test_runtime_loop` cases covering time / automation / trending / GitHub route hardening**
- [ ] **Step 6: Record which duplicated helpers intentionally remained in `loop.py` and why**

### Task 5A stop rule

If the proposed shared helper starts deciding route precedence, family-tool action, or other policy, abort the move and keep that logic in `loop.py`.

---

## Chunk 4: Second Implementation Slice — Deterministic Direct Rendering

### Task 6: Extract only deterministic direct-render helpers

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Create if justified: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/direct_rendering.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- Test if needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_gateway.py`

- [ ] **Step 1: Identify helpers that are pure render transforms from tool result to final text**
- [ ] **Step 2: Do not move rendering that still makes policy decisions about whether recovery should happen**
- [ ] **Step 3: Write or tighten render-focused tests first**
- [ ] **Step 4: Move only deterministic render helpers**
- [ ] **Step 5: Re-run direct-render and gateway-focused regressions**
- [ ] **Step 6: Re-run independent-port live checks for builtin time, GitHub latest commit, and skill load if their visible output changed**

### Slice-specific stop rule

If the helper decides *whether* to recover rather than only *how* to render, it belongs to recovery flow, not direct rendering.

---

## Chunk 5: Third Implementation Slice — Recovery-Only Helpers

### Task 7: Extract recovery-only helpers if and only if they remain thin

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Create if justified: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/recovery_flow.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- Test if needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py`

- [ ] **Step 1: Separate already-available-tool-result recovery from provider-failure handling**
- [ ] **Step 2: Keep fail-closed provider failure emission in `loop.py` unless the blueprint proves the seam is still thin**
- [ ] **Step 3: Write or tighten recovery-specific tests before movement**
- [ ] **Step 4: Move only helpers that consume tool history and return recovery decisions/text, without hidden side effects**
- [ ] **Step 5: Re-run runtime-loop + MCP regression**
- [ ] **Step 6: Re-run independent-port live verification if any recovery path changed**

### Slice-specific stop rule

If the extraction starts owning failure recording, run finalization, or event emission, stop. Those remain loop orchestration responsibilities.

---

## Chunk 6: Fourth Implementation Slice — Tool-Outcome Summary Glue

### Task 8: Extract tool-outcome composition helpers only if the blueprint still approves it

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Create if justified: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/tool_outcome_flow.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Limit the extraction target to pure/near-pure composition and merge helpers**
- [ ] **Step 2: Keep history mutation and final append decisions in `loop.py` unless the seam is obviously safe**
- [ ] **Step 3: Write or tighten summary-specific tests first**
- [ ] **Step 4: Move only the approved helper subset**
- [ ] **Step 5: Re-run tool-outcome-summary regressions and broader runtime-loop checks**

### Slice-specific stop rule

If this slice starts passing half of `RuntimeLoop` into the new module, do not extract it in this branch.

---

### Task 8A: Migrate the Feishu card protocol guard toward the channel boundary

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Modify relevant Feishu channel code under `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_llm_client.py`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_feishu.py`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_gateway.py`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`

- [ ] **Step 1: Decide the minimal channel-owned boundary for Feishu protocol enforcement or guard materialization**
- [ ] **Step 2: Remove direct Feishu protocol inference from `llm_client.py` only if a channel-owned replacement preserves current behavior**
- [ ] **Step 3: Keep plain HTTP behavior unchanged while moving Feishu-only logic**
- [ ] **Step 4: Run `tests.test_llm_client` first**
- [ ] **Step 5: Run Feishu / gateway / contract regression**
- [ ] **Step 6: Run Feishu-focused live verification if visible protocol/render behavior changes**

### Task 8A stop rule

If the replacement requires `llm_client.py` to keep inferring channel protocol from Feishu-specific skill ids anyway, the ownership seam is not real yet; keep the guard where it is and record the blocker instead of half-moving it.

---

## Chunk 7: Final Verification And Closure

### Task 9: Run the required Stage 2 regression suite

- [ ] **Step 1: Run the required Stage 2 branch regression baseline**
- [ ] **Step 2: If any failure appears, debug the most recently moved seam before changing anything else**
- [ ] **Step 3: Record exact commands and pass/fail counts in `STATUS.md`**

### Task 10: Run final independent-port live verification

- [ ] **Step 1: Start the source-backed runtime on `127.0.0.1:8001`**
- [ ] **Step 2: Verify `/healthz` and `/diagnostics/runtime`**
- [ ] **Step 3: Verify plain `/messages` turn**
- [ ] **Step 4: Verify builtin `time` turn**
- [ ] **Step 5: Verify builtin `runtime.context_status` turn**
- [ ] **Step 6: Verify GitHub MCP latest-commit turn**
- [ ] **Step 7: Verify skill-load turn**
- [ ] **Step 8: Capture run diagnostics and write them into `STATUS.md`**

### Task 11: Final alignment review

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- Modify if needed: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`

- [ ] **Step 1: Confirm every moved seam matches the approved decision matrix and blueprint**
- [ ] **Step 2: Confirm no provider-failure degraded-success path was reintroduced**
- [ ] **Step 3: Confirm no planner / intent-router / policy-center drift appeared**
- [ ] **Step 4: Mark remaining deferred items explicitly instead of leaving them implicit**

---

## Stage 2 Done Criteria

Stage 2 is done only if all of the following are true:

- the decision matrix is complete
- the function-level split blueprint exists and matches the actual slices executed
- each moved seam has targeted regression evidence
- required branch regression passes
- independent-port live verification passes
- `STATUS.md` records reality, including any seams intentionally left in `loop.py`
- the runtime still behaves as a thin harness with LLM-first semantics and fail-closed provider failure handling

If these are not all true, Stage 2 is not done.
