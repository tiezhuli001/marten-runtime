# Runtime Latency Breakdown And Optimization Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break down each run's end-to-end latency into first LLM request, tool execution, second LLM request, outbound delivery, and total elapsed time, then apply one narrow optimization slice based on measured evidence rather than guesswork.

**Architecture:** Preserve the current thin-harness runtime contract and the standard two-LLM-turn flow for tool calls. First add minimal per-run timing diagnostics to existing runtime history and diagnostics surfaces, then use those measurements to identify the dominant slow path, and only then implement the smallest optimization that improves the measured bottleneck without widening the runtime into a tracing or observability platform.

**Tech Stack:** Python, unittest, current `marten-runtime` runtime loop, in-memory run history, HTTP diagnostics, Feishu delivery integration

---

## Chunk 1: Baseline Freeze And Bottleneck Hypothesis Discipline

### Task 1: Freeze the pre-change baseline

**Files:**
- Read: `docs/ARCHITECTURE_CHANGELOG.md`
- Read: `docs/architecture/adr/0001-thin-harness-boundary.md`
- Read: `docs/architecture/adr/0002-progressive-disclosure-default-surface.md`
- Read: `docs/architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md`
- Read: `src/marten_runtime/runtime/loop.py`
- Read: `src/marten_runtime/runtime/llm_client.py`
- Read: `src/marten_runtime/runtime/history.py`
- Read: `src/marten_runtime/interfaces/http/app.py`
- Read: `src/marten_runtime/channels/feishu/service.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_contract_compatibility.py`
- Test: `tests/test_health_http.py`
- Test: `tests/test_feishu.py`

- [ ] **Step 1: Confirm branch and worktree state**

Run: `git branch --show-current && git status --short`
Expected: current branch is not `main`; no unrelated blocking changes

- [ ] **Step 2: Run the focused baseline suite**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility tests.test_health_http tests.test_feishu -v`
Expected: PASS

- [ ] **Step 3: Freeze the analysis guardrails**

The implementation must keep these rules explicit:
- no host-side intent routing
- no bypass of the standard second LLM turn for normal tool calls
- no new tracing framework or broad observability subsystem
- no speculative optimization before timing evidence exists

**Testing plan for Task 1**
- Focused baseline suite must pass before any code change.
- If pre-existing failures appear, record exact failing tests and pause optimization scope until they are understood.

**Exit condition for Task 1**
- The baseline is reproducible on the feature branch and the optimization guardrails are frozen.

## Chunk 2: Per-Run Timing Instrumentation

### Task 2: Add a stable run timing data model

**Files:**
- Modify: `src/marten_runtime/runtime/history.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Add a narrow timing container to `RunRecord`**

Required fields:
- `llm_first_ms`
- `tool_ms`
- `llm_second_ms`
- `outbound_ms`
- `total_ms`

Optional only if needed:
- `tool_name`
- `delivery_event_count`

- [ ] **Step 2: Add helper methods on `InMemoryRunHistory` for stage timing updates**

Helpers should support:
- setting a single named stage
- incrementing aggregate outbound timing if multiple deliveries occur
- finalizing total timing on success and failure

- [ ] **Step 3: Preserve compatibility with existing run history contracts**

Do not remove or rename:
- `llm_request_count`
- `tool_calls`
- `status`
- `delivery_status`
- existing `list_runs()` and `get()` behavior

**Testing plan for Task 2**
- Add tests proving:
- a no-tool run can store first-LLM and total timing
- a tool-call run can store all stage timings
- existing run history serialization/reads still work
- Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility -v`
- Expected: PASS

**Exit condition for Task 2**
- Run history can store timing breakdowns without breaking current compatibility tests.

### Task 3: Instrument `RuntimeLoop` for first LLM, tool, second LLM, and total elapsed time

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/runtime/history.py`
- Test: `tests/test_runtime_loop.py`

- [ ] **Step 1: Record run start monotonic time**

Use a monotonic clock for elapsed duration measurement to avoid wall-clock skew.

- [ ] **Step 2: Measure the first `self.llm.complete(...)` call**

Timing boundary:
- start immediately before `complete()`
- stop immediately after it returns or raises

- [ ] **Step 3: Measure actual tool execution time**

Timing boundary:
- start immediately before tool resolution/execution
- stop immediately after tool result is available or execution fails

Do not accidentally include second-LLM work inside `tool_ms`.

- [ ] **Step 4: Measure the second `self.llm.complete(...)` call**

Only populate `llm_second_ms` for requests that actually enter a tool-result follow-up turn.

- [ ] **Step 5: Finalize `total_ms` on every completion path**

Completion paths that must set total elapsed timing:
- success with no tool
- success after tool
- tool rejection
- tool execution failure
- provider failure
- generic runtime failure
- tool loop limit exceeded

- [ ] **Step 6: Keep `llm_request_count` semantics unchanged**

Normal tool-call turns must still report `llm_request_count = 2`.

**Testing plan for Task 3**
- Add deterministic tests with scripted/stubbed LLM behavior and tool behavior.
- Assert:
- no-tool run has `llm_first_ms > 0`, `tool_ms = 0`, `llm_second_ms = 0`
- tool-call run has all stage timings populated
- failure paths still finalize `total_ms`
- Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop -v`
- Expected: PASS

**Exit condition for Task 3**
- Runtime loop emits correct stage timings across success and failure paths without changing the standard tool-call contract.

### Task 4: Instrument outbound delivery timing at the call boundary

**Files:**
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/runtime/history.py`
- Test: `tests/test_feishu.py`

- [ ] **Step 1: Locate the accepted-run delivery point in `service.py`**

Use the existing loop around `delivery_client.deliver(...)` as the timing boundary.

- [ ] **Step 2: Measure elapsed delivery time per visible outbound event**

Aggregate into one run-level `outbound_ms` field.

- [ ] **Step 3: Keep hidden progress behavior unchanged**

No change to:
- hidden progress semantics
- send/update fallback behavior
- dead-letter behavior

**Testing plan for Task 4**
- Add tests proving:
- accepted runs accumulate outbound timing
- hidden progress does not regress into visible delivery
- final/error delivery still works through the same paths
- Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
- Expected: PASS

**Exit condition for Task 4**
- Outbound delivery timing is captured without adding a new transport-logging subsystem or changing delivery semantics.

### Task 5: Expose timing breakdown through existing diagnostics

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Possibly modify: `src/marten_runtime/runtime/history.py`
- Test: `tests/test_health_http.py`
- Test: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Identify the current run/runtime diagnostics path**

Prefer the existing endpoint and payload shape that already exposes run metadata.

- [ ] **Step 2: Add timing fields with minimal contract drift**

Preferred shape:
- keep existing response structure
- add a `timings` object or equivalent narrow extension

- [ ] **Step 3: Keep all prior diagnostics fields stable**

No deletions or breaking renames.

**Testing plan for Task 5**
- Add HTTP assertions that diagnostics now include the timing breakdown.
- Re-run compatibility tests that consume diagnostics.
- Run: `PYTHONPATH=src python -m unittest tests.test_health_http tests.test_contract_compatibility -v`
- Expected: PASS

**Exit condition for Task 5**
- Existing diagnostics expose per-run timing breakdown without a breaking contract change.

## Chunk 3: Evidence Collection And Bottleneck Attribution

### Task 6: Use the new timings to identify the actual dominant slow path

**Files:**
- Read: `src/marten_runtime/runtime/loop.py`
- Read: `src/marten_runtime/runtime/llm_client.py`
- Read: `src/marten_runtime/channels/feishu/service.py`
- Read: `src/marten_runtime/channels/feishu/delivery.py`
- Update: local `STATUS.md`

- [ ] **Step 1: Re-run the focused suite after instrumentation**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility tests.test_health_http tests.test_feishu -v`
Expected: PASS

- [ ] **Step 2: If live work is available, restart the runtime and sample real timing data**

Recommended commands:
- `curl -sS http://127.0.0.1:8074/healthz`
- `curl -sS http://127.0.0.1:8074/diagnostics/runtime`

If live prompts are run, capture at least:
- plain no-tool turn
- simple `time` tool turn
- one Feishu-delivered turn if feasible

- [ ] **Step 3: Attribute the bottleneck**

Classify the dominant cost as one of:
- first LLM dominated
- tool execution dominated
- second LLM dominated
- outbound delivery dominated
- mixed/noisy, requiring no optimization in this slice

- [ ] **Step 4: Record the measured evidence in local continuity**

Add:
- sample run IDs
- stage timings
- chosen optimization target
- rejected hypotheses

**Testing plan for Task 6**
- No new unit tests required if this task only collects evidence, but any live sampling must be recorded with exact commands and results.

**Exit condition for Task 6**
- A single dominant optimization target is chosen from measured timing evidence instead of intuition.

## Chunk 4: Narrow Optimization Slice

### Task 7: Implement one evidence-backed optimization only

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Or modify: `src/marten_runtime/runtime/llm_client.py`
- Or modify: `src/marten_runtime/channels/feishu/service.py`
- Or modify: `src/marten_runtime/channels/feishu/delivery.py`
- Test: relevant targeted test files based on the chosen bottleneck

- [ ] **Step 1: Convert the measured bottleneck into one narrow code change**

Allowed examples:
- avoid redundant work in second-turn request assembly
- reduce avoidable history/diagnostics copying on the hot path
- trim unnecessary delivery-side overhead

Disallowed examples:
- remove the second LLM turn
- add host-side routing to force a shortcut
- introduce caching or background systems that widen architecture

- [ ] **Step 2: Add or update the smallest regression test that proves the intended behavior**

The test should validate the contract and prevent accidental architectural drift.

- [ ] **Step 3: Re-run the relevant focused suite**

Use only the files affected by the optimization.

**Testing plan for Task 7**
- At minimum run the directly affected suite.
- If the optimization touches runtime loop or diagnostics, re-run:
  `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility tests.test_health_http -v`
- If it touches Feishu delivery path, re-run:
  `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_contract_compatibility -v`

**Exit condition for Task 7**
- One evidence-backed optimization is implemented and verified without breaking architecture constraints.

## Chunk 5: Final Verification And Completion

### Task 8: Verify the instrumentation plus optimization slice end to end

**Files:**
- Test: `tests/`
- Update: `docs/ARCHITECTURE_CHANGELOG.md`
- Update: local `STATUS.md`

- [ ] **Step 1: Run the focused regression suite**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility tests.test_health_http tests.test_feishu -v`
Expected: PASS

- [ ] **Step 2: Run the full repository suite**

Run: `PYTHONPATH=src python -m unittest -v`
Expected: PASS

- [ ] **Step 3: If live runtime validation is in scope, collect post-optimization evidence**

Repeat the same prompt class used during Task 6 and compare stage timings.

- [ ] **Step 4: Record architecture evidence**

Update:
- `docs/ARCHITECTURE_CHANGELOG.md` with the timing-breakdown slice and the accepted narrow optimization
- local `STATUS.md` with commands and results

**Testing plan for Task 8**
- Focused regression and full regression must pass.
- Any live validation must record exact commands, run IDs if available, and before/after timing comparison.

**Exit condition for Task 8**
- The runtime exposes per-run stage timings, one measured bottleneck has been optimized narrowly, and all verification evidence is recorded.

## Overall Done Criteria

This plan is complete only when all of the following are true:

- Each run can expose `llm_first_ms`, `tool_ms`, `llm_second_ms`, `outbound_ms`, and `total_ms`.
- Tool-call runs still use the standard two-LLM-turn flow and preserve `llm_request_count = 2`.
- Diagnostics expose the timing breakdown through existing surfaces.
- At least one dominant latency bottleneck has been identified from real timing evidence.
- Exactly one narrow optimization slice has been implemented based on that evidence.
- Focused regression and full regression both pass.
