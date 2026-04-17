# Langfuse Observability Implementation Plan

> **For agentic workers:** Execute this plan in the current branch and current workspace. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit, do not spawn subagents, and do not widen scope beyond Langfuse tracing unless the user explicitly asks.

**Goal:** Implement Langfuse tracing for `marten-runtime` so every runtime turn, LLM round, and tool invocation is observable through Langfuse and locally correlated through existing diagnostics.

**Architecture:** Keep the harness thin and preserve the current runtime-owned execution spine. Add one narrow Langfuse observability adapter, wire it once during bootstrap, instrument `RuntimeLoop.run()` for root trace / generation / tool span lifecycle, and write external correlation ids back into existing run and trace diagnostics. Every module ships with focused unit tests, then the completed slice runs broader contract coverage and a full-chain smoke.

**Tech Stack:** Python 3.11+, unittest, FastAPI `TestClient`, existing `RuntimeLoop` / `InMemoryRunHistory` / HTTP diagnostics stack, Langfuse Python SDK, repo-local config via `.env.example`

---

## Global implementation constraints

- Preserve the current thin harness boundary and keep runtime semantics owned by local `RunRecord` / `trace_index` structures.
- Langfuse remains optional; startup and tests must work with no Langfuse config.
- Instrument the runtime spine directly; do not refactor the provider transport into a different abstraction just to add tracing.
- One narrow observability module owns all SDK imports and Langfuse-specific branching.
- Partial Langfuse config must surface through diagnostics and no-op behavior instead of crashing startup.
- Each new module or changed contract must get focused unit coverage before implementation is considered complete.
- Unit and contract tests must stay offline; use fake Langfuse clients/recorders and never require live Langfuse network access.
- Full completion requires broader regression plus one end-to-end chain test that proves local diagnostics and Langfuse correlation stay aligned.
- Keep scope on tracing/observability only. Prompt management, OpenTelemetry, dashboard work, and README/docs refresh stay out of scope until tracing code and tests pass.
- Update `STATUS.md` after the plan-writing slice and again after implementation milestones land.

---

## Anti-drift execution rules

- Keep implementation inside Langfuse tracing only; do not migrate prompts into Langfuse in this plan.
- Do not add OpenTelemetry, metrics exporters, dashboard code, or analytics aggregation in this plan.
- Do not refactor unrelated runtime files for style or cleanup.
- Prefer extending existing tests where the runtime contract already lives; create new tests only when there is no natural existing home.
- Every chunk must end with a green proof command before moving to the next chunk.

---

## File structure and responsibility map

### New files

- `src/marten_runtime/observability/langfuse.py`
  - Own Langfuse config parsing, no-op fallback, client lifecycle, trace/generation/tool-span helpers, and flush/shutdown behavior.
- `tests/test_langfuse_observability.py`
  - Unit tests for the new observability adapter.
- `tests/runtime_loop/test_langfuse_runtime_observability.py`
  - Runtime-loop level tests for root trace, generation, tool span, and finalization behavior.
- `tests/contracts/test_langfuse_diagnostics_contracts.py`
  - Contract tests for `/diagnostics/runtime`, `/diagnostics/run/{run_id}`, and `/diagnostics/trace/{trace_id}` Langfuse surfaces.
- `tests/test_langfuse_bootstrap.py`
  - Bootstrap and FastAPI lifespan tests for observer initialization and shutdown.
- `tests/test_trace_correlation.py`
  - Existing trace endpoint coverage extended with Langfuse `external_refs`.

### Existing files to modify

- `.env.example`
  - Add `LANGFUSE_BASE_URL` and keep existing keys documented together.
- `requirements.txt`
  - Add the Langfuse SDK dependency.
- `pyproject.toml`
  - Mirror the Langfuse dependency in project metadata.
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - Build the observer once, attach it to `HTTPRuntimeState`, and pass it into runtime-owned services.
- `src/marten_runtime/interfaces/http/app.py`
  - Flush/shutdown the observer during FastAPI lifespan teardown.
- `src/marten_runtime/runtime/history.py`
  - Add a small external-observability surface to `RunRecord`.
- `src/marten_runtime/runtime/loop.py`
  - Start/finalize root trace and wrap each LLM/tool boundary.
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - Write Langfuse correlation ids into `trace_index[trace_id].external_refs`.
- `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
  - Expose runtime-level Langfuse enabled/configured state.
- `tests/contracts/test_runtime_contracts.py`
  - Extend runtime diagnostics coverage if shared contracts already live there.
- `tests/contracts/test_gateway_contracts.py`
  - Extend run/trace diagnostics contract coverage if shared contracts already live there.
- `tests/test_acceptance.py`
  - Extend or add one full-chain acceptance smoke that validates local diagnostics and Langfuse correlation fields.

### Optional follow-up docs after implementation lands

- `docs/CONFIG_SURFACES.md`
- `README.md`
- `README_CN.md`

These docs stay outside this implementation plan until code and tests pass.

---

## Chunk 1: Lock observability adapter contract with failing tests

### Task 1: Define the Langfuse adapter API and no-op behavior

**Files:**
- Create: `src/marten_runtime/observability/langfuse.py`
- Create: `tests/test_langfuse_observability.py`

- [ ] **Step 1: Write failing tests for config parsing and enabled/configured states**

Cover:
- no env keys present → observer reports `enabled=False`, `configured=False`, and behaves as no-op
- full env present → observer reports `enabled=True`, `configured=True`, and resolves `base_url`
- partial env present → observer reports `enabled=False`, `configured=False`, and includes a stable reason such as `missing_langfuse_config`
- observer methods are safe to call in all three states

- [ ] **Step 2: Write failing tests for trace/generation/tool/finalization API shape**

Cover:
- `start_run_trace(...)` returns a lightweight handle or record with stable ids
- `observe_generation(...)` stores stage, model, usage, status, and latency on a fake transport/client
- `observe_tool_call(...)` stores tool metadata and success/error status
- `finalize_run(...)` stores final status, error code, final text, and aggregate usage
- `flush()` and `shutdown()` are safe and idempotent

- [ ] **Step 3: Implement the minimal adapter with a strict no-op fallback**

Implementation notes:
- keep Langfuse SDK import isolated in this module
- create a tiny config model and a tiny runtime-facing observer protocol/class
- build a fake-client-friendly constructor path for tests
- avoid leaking SDK types across module boundaries

- [ ] **Step 4: Run focused unit tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_langfuse_observability`

Expected: PASS

- [ ] **Step 5: Checkpoint scope and changed files**

Requirements:
- confirm changed files still match this task boundary
- confirm no commit is created unless the user explicitly asks
- record any new test file paths in `STATUS.md` only when the chunk is complete


---

## Chunk 2: Wire bootstrap, config, and shutdown lifecycle

### Task 2: Add config surfaces and runtime bootstrap wiring

**Files:**
- Modify: `.env.example`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Extend: `tests/test_langfuse_observability.py`
- Create: `tests/test_langfuse_bootstrap.py`

- [ ] **Step 1: Write failing tests for runtime bootstrap wiring**

Cover:
- `build_http_runtime(...)` attaches a Langfuse observer to runtime state
- no-config runtime boot keeps the observer in no-op mode
- full-config runtime boot creates an enabled observer
- FastAPI lifespan teardown calls observer shutdown/flush exactly once

- [ ] **Step 2: Add the config surface**

Implementation notes:
- add `LANGFUSE_BASE_URL` to `.env.example`
- add the Langfuse dependency to both dependency files
- keep versioning style aligned with the rest of the repo

- [ ] **Step 3: Extend `HTTPRuntimeState` and bootstrap wiring**

Implementation notes:
- attach the observer to `HTTPRuntimeState`
- construct it once from resolved env in `build_http_runtime(...)`
- keep bootstrap flow local and explicit; no hidden global singletons

- [ ] **Step 4: Extend FastAPI lifespan teardown**

Implementation notes:
- call observer `flush()` / `shutdown()` during `lifespan` cleanup
- keep existing `subagent_service.shutdown()` and event-loop cleanup ordering intact
- tests should prove cleanup still completes with observer enabled and disabled

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_langfuse_observability tests.test_langfuse_bootstrap`

Expected: PASS

- [ ] **Step 6: Checkpoint scope and changed files**

Requirements:
- confirm changed files still match this task boundary
- confirm no commit is created unless the user explicitly asks
- record any new test file paths in `STATUS.md` only when the chunk is complete


---

## Chunk 3: Add run-history external correlation contract

### Task 3: Persist Langfuse correlation ids in run history

**Files:**
- Modify: `src/marten_runtime/runtime/history.py`
- Create: `tests/test_runtime_history.py`
- Create: `tests/runtime_loop/test_langfuse_runtime_observability.py`

- [ ] **Step 1: Write failing tests for `RunRecord` external observability fields**

Cover:
- run history can store `langfuse_trace_id`
- run history can store `langfuse_url`
- fields serialize through `.model_dump(mode="json")`
- missing values keep existing run diagnostics shape stable

- [ ] **Step 2: Implement a minimal structured field**

Implementation notes:
- add a small nested model such as `ExternalObservabilityRefs`
- keep default empty values simple and serialization-friendly
- add one helper on `InMemoryRunHistory` for setting external observability refs

- [ ] **Step 3: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_history tests.runtime_loop.test_langfuse_runtime_observability`

Expected: PASS

- [ ] **Step 4: Checkpoint scope and changed files**

Requirements:
- confirm changed files still match this task boundary
- confirm no commit is created unless the user explicitly asks
- record any new test file paths in `STATUS.md` only when the chunk is complete


---

## Chunk 4: Instrument `RuntimeLoop.run()` for root trace and generation spans

### Task 4: Add root trace lifecycle and LLM generation observations

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Extend: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Extend: `tests/runtime_loop/test_langfuse_runtime_observability.py`
- Extend: `tests/test_subagent_runtime_loop.py`

- [ ] **Step 1: Write failing runtime-loop tests for root trace start/finalization**

Cover:
- plain chat turn starts one root trace after `run_id` creation
- successful plain chat finalizes trace with `status=succeeded`
- provider failure finalizes trace with `status=failed` and normalized error code
- runtime loop limit / empty final response paths still finalize the root trace

- [ ] **Step 2: Write failing runtime-loop tests for generation spans**

Cover:
- first LLM round records `llm.first`
- tool follow-up LLM round records `llm.followup`
- generation metadata includes model name, provider name, request kind, stage, latency, and usage when available
- provider retry diagnostics are attached when `last_call_diagnostics` exists

- [ ] **Step 3: Implement root trace and generation instrumentation**

Implementation notes:
- start the root trace immediately after `run = self.history.start(...)`
- include `trace_id`, `run_id`, `session_id`, `agent_id`, `app_id`, `channel_id`, `request_kind`, `config_snapshot_id`, `bootstrap_manifest_id`, `parent_run_id`
- wrap each `resolved_llm.complete(current_request)` call with generation observation
- on every success/error return path, finalize the root trace and write Langfuse refs back to run history

- [ ] **Step 4: Add coverage for subagent child runs**

Cover:
- a child run with `parent_run_id` still starts a root trace with child metadata
- local run history keeps Langfuse refs for the child run as well

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.runtime_loop.test_langfuse_runtime_observability tests.test_subagent_runtime_loop`

Expected: PASS

- [ ] **Step 5: Checkpoint scope and changed files**

Requirements:
- confirm changed files still match this task boundary
- confirm no commit is created unless the user explicitly asks
- record any new test file paths in `STATUS.md` only when the chunk is complete


---

## Chunk 5: Instrument tool spans and error branches

### Task 5: Add tool-call span observations for success and failure paths

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Extend: `tests/runtime_loop/test_langfuse_runtime_observability.py`
- Extend: `tests/runtime_mcp/test_followup_recovery.py`
- Extend: `tests/runtime_loop/test_tool_followup_and_recovery.py`

- [ ] **Step 1: Write failing tests for successful builtin tool span capture**

Cover:
- one builtin tool turn records one `tool.call` span
- span metadata includes tool name, payload, result summary, run id, trace id, and elapsed time

- [ ] **Step 2: Write failing tests for successful MCP tool span capture**

Cover:
- one MCP tool turn records one `tool.call` span
- span metadata includes MCP family/tool details and success state

- [ ] **Step 3: Write failing tests for rejected and failed tool paths**

Cover:
- `ToolCallRejected` records an error span with rejection code
- `ToolExecutionFailed` records an error span with execution failure code
- trace finalization remains correct after tool failure exits

- [ ] **Step 4: Implement tool span observation**

Implementation notes:
- wrap `resolve_tool_call(...)` with observer timing
- observe both success and failure branches
- reuse existing normalized tool result structures where practical
- keep `history.record_tool_call(...)` as local source of truth

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.runtime_loop.test_langfuse_runtime_observability tests.runtime_mcp.test_followup_recovery tests.runtime_loop.test_tool_followup_and_recovery`

Expected: PASS

- [ ] **Step 5: Checkpoint scope and changed files**

Requirements:
- confirm changed files still match this task boundary
- confirm no commit is created unless the user explicitly asks
- record any new test file paths in `STATUS.md` only when the chunk is complete


---

## Chunk 6: Expose runtime, run, and trace diagnostics

### Task 6: Surface Langfuse state through existing HTTP diagnostics

**Files:**
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Create: `tests/contracts/test_langfuse_diagnostics_contracts.py`
- Extend: `tests/contracts/test_runtime_contracts.py`
- Extend: `tests/contracts/test_gateway_contracts.py`
- Extend: `tests/test_trace_correlation.py`

- [ ] **Step 1: Write failing contract tests for `/diagnostics/runtime`**

Cover:
- response includes `observability.langfuse.enabled`
- response includes `observability.langfuse.configured`
- response includes `observability.langfuse.base_url`
- response includes a stable configuration reason when config is partial
- no-config and configured states both serialize cleanly

- [ ] **Step 2: Write failing contract tests for `/diagnostics/run/{run_id}` and `/diagnostics/trace/{trace_id}`**

Cover:
- run diagnostics include Langfuse trace correlation fields
- trace diagnostics include `external_refs.langfuse_trace_id` and `external_refs.langfuse_url`
- existing `run_ids`, `job_ids`, and `event_ids` fields remain intact
- `tests/test_trace_correlation.py` still passes with the new refs present

- [ ] **Step 3: Implement diagnostics exposure**

Implementation notes:
- extend runtime diagnostics serializer with a narrow `observability.langfuse` block
- when a run completes, copy Langfuse refs into `trace_index[trace_id].external_refs`
- keep diagnostics stable for runs that occurred with Langfuse disabled

- [ ] **Step 4: Run focused contract tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.contracts.test_langfuse_diagnostics_contracts tests.contracts.test_runtime_contracts tests.contracts.test_gateway_contracts tests.test_trace_correlation`

Expected: PASS

- [ ] **Step 5: Checkpoint scope and changed files**

Requirements:
- confirm changed files still match this task boundary
- confirm no commit is created unless the user explicitly asks
- record any new test file paths in `STATUS.md` only when the chunk is complete


---

## Chunk 7: Run broader regression and full-chain validation

### Task 7: Prove the completed integration across unit, contract, and end-to-end paths

**Files:**
- Extend: `tests/test_acceptance.py`
- Update only if drift is found during verification: `STATUS.md`

- [ ] **Step 1: Add a failing acceptance/full-chain test**

Cover one real chain with `TestClient(build_test_app())` and a fake Langfuse observer/client:
- plain chat turn → root trace + one generation + local diagnostics correlation
- builtin tool turn → root trace + generation + tool span + run/trace diagnostics correlation
- one MCP tool turn → root trace + generation + tool span + run/trace diagnostics correlation

- [ ] **Step 2: Implement any remaining glue revealed by the acceptance test**

Implementation notes:
- keep fixes local
- avoid widening architecture or adding debug-only hooks that only exist for tests

- [ ] **Step 3: Run the focused acceptance test**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_acceptance`

Expected: PASS for the new Langfuse scenarios and no regressions in existing acceptance coverage

- [ ] **Step 4: Run the broader regression set**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v \
  tests.test_langfuse_observability \
  tests.test_langfuse_bootstrap \
  tests.test_runtime_history \
  tests.runtime_loop.test_langfuse_runtime_observability \
  tests.runtime_mcp.test_followup_recovery \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.contracts.test_langfuse_diagnostics_contracts \
  tests.contracts.test_runtime_contracts \
  tests.contracts.test_gateway_contracts \
  tests.test_trace_correlation \
  tests.test_subagent_runtime_loop \
  tests.test_acceptance
```

Expected: PASS

- [ ] **Step 5: Run the final full-chain smoke**

Run one explicit HTTP-runtime smoke using `TestClient(build_test_app())` or the repo's acceptance harness to prove all three subcases:
- plain chat turn succeeds and records one root trace plus one generation
- builtin tool turn succeeds and records one root trace, generation, and tool span
- MCP tool turn succeeds and records one root trace, generation, and MCP tool span
- local run diagnostics expose Langfuse correlation ids for each exercised run
- local trace diagnostics expose `external_refs` for each exercised trace

Record the exact command and decisive output in `STATUS.md`.

- [ ] **Step 6: Checkpoint scope and changed files**

Requirements:
- confirm changed files still match this task boundary
- confirm no commit is created unless the user explicitly asks
- record any new test file paths in `STATUS.md` only when the chunk is complete


---

## Final execution checklist

- [ ] Langfuse adapter exists with safe no-op behavior
- [ ] runtime bootstrap initializes and tears down the observer correctly
- [ ] run history persists Langfuse refs
- [ ] runtime loop emits root trace and generation observations
- [ ] tool execution emits success and error spans
- [ ] runtime, run, and trace diagnostics expose Langfuse state and refs
- [ ] every changed module has targeted unit or contract coverage
- [ ] broader regression passes
- [ ] final full-chain smoke passes
- [ ] `STATUS.md` reflects the finished implementation and verification truth

