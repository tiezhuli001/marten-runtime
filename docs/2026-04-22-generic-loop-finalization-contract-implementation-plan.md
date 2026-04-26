# Generic Loop Finalization Contract Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** implement the generic fragment-based loop finalization contract so `marten-runtime` can recover degraded post-tool final answers without any fixed ordered tool-name helper.

**Architecture:** keep free-form tool selection model-driven and keep terminal direct renders narrow. Convert tool followup rendering into a structured `terminal_text + recovery_fragment` surface, add one bounded `finalization_retry` path with no callable tools, then fall back to generic ordered fragment aggregation when the retry still degrades. Delete the current `[time, runtime.context_status, mcp.list]` helper path and the tests that privilege it.

**Tech Stack:** Python 3.12, Pydantic, unittest, FastAPI runtime harness, OpenAI-compatible chat/responses transports

---

## Source Documents

- Design source of truth:
  - `docs/2026-04-22-generic-loop-finalization-contract-design.md`
- Architecture constraints:
  - `docs/architecture/adr/0001-thin-harness-boundary.md`
  - `docs/architecture/adr/0004-llm-first-tool-routing-boundary.md`
- Current continuity file:
  - `STATUS.md`
- Main implementation entry points:
  - `src/marten_runtime/runtime/llm_client.py`
  - `src/marten_runtime/runtime/tool_followup_support.py`
  - `src/marten_runtime/runtime/direct_rendering.py`
  - `src/marten_runtime/runtime/recovery_flow.py`
  - `src/marten_runtime/runtime/loop.py`
  - `src/marten_runtime/runtime/llm_message_support.py`
  - `src/marten_runtime/runtime/llm_request_instructions.py`
  - `src/marten_runtime/runtime/llm_adapters/openai_compat.py`
- Main tests to evolve:
  - `tests/test_tool_followup_support.py`
  - `tests/test_direct_rendering.py`
  - `tests/test_recovery_flow.py`
  - `tests/test_llm_client.py`
  - `tests/test_llm_transport.py`
  - `tests/runtime_loop/test_tool_followup_and_recovery.py`
  - `tests/runtime_loop/test_direct_rendering_paths.py`
  - `tests/test_acceptance.py`

## Locked Invariants

- keep free-form natural-language tool selection with the model
- keep the runtime center at:
  - `channel -> binding -> runtime loop -> builtin/MCP/skill -> delivery`
- keep terminal direct renders narrow and tool-local
- keep recovery generic:
  - no fixed tool-name lists
  - no ordered helper that recognizes `[time, runtime.context_status, mcp.list]`
- keep `recovery_fragment` runtime-only:
  - not provider-visible
  - not persisted to durable session history
  - not replayed across turns
- keep deterministic fallback truthful:
  - aggregate only safe fragments from already-executed tool results plus runtime-owned loop facts
- finalization retry must be:
  - exactly one extra provider call
  - `request_kind = "finalization_retry"`
  - no callable tools exposed
  - no forced `tool_choice`
  - interactive-class timeout and retry budget
- degraded-final detection must be:
  - exact normalized block comparison
  - strict ordered subsequence
  - no fuzzy match
  - no semantic similarity match
- do not change first-turn interactive auto-tool-choice behavior outside this slice
- do not introduce commits in this plan unless the user explicitly asks later

## File / Module Map

- `src/marten_runtime/runtime/llm_client.py`
  - define runtime-only followup models
  - extend `ToolExchange` with optional fragment metadata
- `src/marten_runtime/runtime/tool_followup_support.py`
  - normalize tool results into:
    - normalized `tool_result`
    - `ToolFollowupRender`
  - build ordinary tool-followup requests
  - build finalization-retry requests
- `src/marten_runtime/runtime/direct_rendering.py`
  - keep single-tool deterministic renderers
  - add generic fragment rendering / aggregation helpers
  - remove fixed ordered history helper logic
- `src/marten_runtime/runtime/recovery_flow.py`
  - assess finalization results
  - decide:
    - accept
    - retry
    - deterministic fallback
- `src/marten_runtime/runtime/loop.py`
  - store fragment metadata on tool history
  - integrate one-shot finalization retry
  - use generic fallback
  - remove fixed-helper upgrade path
- `src/marten_runtime/runtime/llm_message_support.py`
  - keep normal tool-followup prompt assembly
  - support `finalization_retry` with `tool_history` and zero callable tools
- `src/marten_runtime/runtime/llm_request_instructions.py`
  - add narrow instruction text for `finalization_retry`
- `src/marten_runtime/runtime/llm_adapters/openai_compat.py`
  - keep timeout/retry budgeting aligned with interactive followup for `finalization_retry`
  - preserve diagnostics `request_kind`
- `tests/test_tool_followup_support.py`
  - lock the structured followup surface
- `tests/test_direct_rendering.py`
  - lock generic fragment helpers and single-tool render behavior
- `tests/test_recovery_flow.py`
  - lock degraded-final assessment and fallback rules
- `tests/test_llm_client.py`
  - lock retry-specific instruction wording
- `tests/test_llm_transport.py`
  - lock retry payload shape, tool omission, and request-kind transport behavior
- `tests/runtime_loop/test_tool_followup_and_recovery.py`
  - lock loop retry and fragment fallback semantics
- `tests/runtime_loop/test_direct_rendering_paths.py`
  - ensure existing direct-render early exits still work
- `tests/test_acceptance.py`
  - lock the end-to-end ordered multi-tool chain on the new generic contract
- `docs/ARCHITECTURE_CHANGELOG.md`
  - record the new durable loop-finalization contract after implementation lands
- `STATUS.md`
  - keep progress and verification synced to reality

## Anti-Drift Checkpoints

Re-check these design sections after each chunk:

- design section `2`:
  - terminal direct render and recovery fragment must stay separate
- design section `3`:
  - `recovery_fragment` must stay runtime-only
- design section `5`:
  - degraded-final detection stays block-based and exact
- design section `6`:
  - retry stays one-shot and no-tools
- design section `10`:
  - fixed ordered helper path must leave the repository

If any chunk drifts from one of these checkpoints, fix the code or fix the plan before continuing.

## Delivery Order

Implement in five strict chunks:

1. structured followup data contract
2. generic fragment rendering surface
3. finalization retry request path and loop integration
4. fixed-helper deletion and regression replacement
5. docs sync and final verification

Do not start a later chunk until the current chunk:

- passes its focused verification
- still matches the design doc
- leaves `git diff --check` clean

## Chunk 1: Structured Followup Data Contract

### Task 1: Add runtime-only followup models

**Files:**
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Modify: `tests/test_tool_followup_support.py`
- Modify: `tests/test_llm_transport.py`

**Constraints:**
- add `ToolFollowupFragment`
- add `ToolFollowupRender`
- extend `ToolExchange` with optional `recovery_fragment`
- fragment metadata must remain runtime-only
- prompt serialization must still emit only:
  - `tool_name`
  - `tool_payload`
  - `tool_result`

- [ ] **Step 1: Write the failing tests**

Lock:

- `normalize_tool_result_for_followup(...)` will soon return a structured followup object instead of raw rendered text
- `build_openai_chat_payload(...)` must ignore `ToolExchange.recovery_fragment`

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_tool_followup_support \
  tests.test_llm_transport
```

Expected:

- new assertions fail because the structured followup models do not exist yet

- [ ] **Step 3: Implement the followup models**

Required shape:

```python
class ToolFollowupFragment(BaseModel):
    text: str
    source: Literal["tool_result", "loop_meta"]
    tool_name: str | None = None
    safe_for_fallback: bool = True


class ToolFollowupRender(BaseModel):
    terminal_text: str | None = None
    recovery_fragment: ToolFollowupFragment | None = None
```

And:

```python
class ToolExchange(BaseModel):
    tool_name: str
    tool_payload: dict = Field(default_factory=dict)
    tool_result: dict = Field(default_factory=dict)
    recovery_fragment: ToolFollowupFragment | None = None
```

- [ ] **Step 4: Keep prompt serialization stable**

Confirm `build_openai_messages(...)` and the responses input conversion still serialize only:

- assistant tool call
- tool result JSON

They must not leak `recovery_fragment`.

- [ ] **Step 5: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_tool_followup_support \
  tests.test_llm_transport
```

**Done means:**

- new followup models exist
- `ToolExchange` can hold fragment metadata
- provider payloads stay unchanged

### Task 2: Convert followup normalization to a structured surface

**Files:**
- Modify: `src/marten_runtime/runtime/tool_followup_support.py`
- Modify: `tests/test_tool_followup_support.py`

**Constraints:**
- replace the current raw `str | None` rendered return with `ToolFollowupRender`
- keep tool-result normalization behavior unchanged
- do not add new routing logic

- [ ] **Step 1: Write the failing tests**

Lock:

- single-intent `runtime.context_status` returns:
  - `terminal_text`
  - `recovery_fragment`
- multi-round `runtime.context_status` returns:
  - no `terminal_text`
  - still has a `recovery_fragment`
- existing session/subagent direct-render paths now populate `terminal_text`

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_tool_followup_support
```

Expected:

- failures because `normalize_tool_result_for_followup(...)` still returns `(tool_result, str | None)`

- [ ] **Step 3: Implement the structured return**

Required direction:

- rename or replace the raw rendered-text helper with a structured helper
- return:
  - normalized `tool_result`
  - `ToolFollowupRender`

Keep `append_tool_exchange(...)` unchanged in this chunk. Loop integration happens later.

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_tool_followup_support
```

**Done means:**

- followup normalization returns one explicit structured object
- terminal text and fallback fragment are no longer conflated

## Chunk 2: Generic Fragment Rendering Surface

### Task 1: Replace the fixed ordered history helper with generic fragment helpers

**Files:**
- Modify: `src/marten_runtime/runtime/direct_rendering.py`
- Modify: `tests/test_direct_rendering.py`

**Constraints:**
- keep `render_direct_tool_text(...)` or its equivalent single-tool renderer
- add generic helpers that operate on explicit fragment blocks
- delete no code yet if that would break imports before replacements are ready
- helper logic must depend on fragment blocks, not tool names

- [ ] **Step 1: Write the failing tests**

Lock:

- generic `render_recovery_fragments_text(...)` joins arbitrary fragment blocks in order
- generic `is_partial_fragment_aggregation(...)` detects strict ordered subsequences only
- exact full match is not degraded
- substring-only and paraphrase-like text are not treated as degraded

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_direct_rendering
```

Expected:

- failures because the generic fragment helpers do not exist yet

- [ ] **Step 3: Implement the generic helpers**

Required helper surface:

- `render_recovery_fragment(...)`
- `render_recovery_fragments_text(...)`
- `is_partial_fragment_aggregation(...)`

Allowed simplification:

- when a single-tool deterministic text is already trustworthy, its fragment text may reuse that same renderer output

- [ ] **Step 4: Preserve existing single-tool render coverage**

Re-check existing tests for:

- runtime
- session
- MCP commit lookup
- MCP list
- subagent acknowledgement

Those paths must still pass.

- [ ] **Step 5: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_direct_rendering
```

**Done means:**

- generic fragment helpers exist
- exact subsequence detection is covered
- single-tool deterministic renders still work

### Task 2: Make structured followup rendering produce fragments generically

**Files:**
- Modify: `src/marten_runtime/runtime/tool_followup_support.py`
- Modify: `src/marten_runtime/runtime/direct_rendering.py`
- Modify: `tests/test_tool_followup_support.py`

**Constraints:**
- fragment generation should be tool-local
- terminal direct render remains opt-in
- a tool may emit:
  - terminal only
  - fragment only
  - both
  - neither

- [ ] **Step 1: Write the failing tests**

Lock:

- `time` can contribute a fragment in a multi-step chain
- `mcp.list` can contribute a fragment even when it does not direct-render mid-loop
- `session` / `spawn_subagent` still direct-render when they are terminal

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_tool_followup_support \
  tests.test_direct_rendering
```

Expected:

- failures because followup normalization does not yet populate generic fragments correctly

- [ ] **Step 3: Implement the fragment population**

Recommended minimal path:

- single-tool deterministic renderer stays the source of truth for user-ready text
- fragment builder may reuse that text when the tool result is safe for fallback
- do not invent a second formatting system

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_tool_followup_support \
  tests.test_direct_rendering
```

**Done means:**

- followup rendering can populate safe fragments for multi-step recovery
- terminal early-exit behavior is preserved

## Chunk 3: Finalization Retry Path And Loop Integration

### Task 1: Add a dedicated finalization-retry request shape

**Files:**
- Modify: `src/marten_runtime/runtime/tool_followup_support.py`
- Modify: `src/marten_runtime/runtime/llm_message_support.py`
- Modify: `src/marten_runtime/runtime/llm_request_instructions.py`
- Modify: `src/marten_runtime/runtime/llm_adapters/openai_compat.py`
- Modify: `tests/test_llm_client.py`
- Modify: `tests/test_llm_transport.py`

**Constraints:**
- `request_kind = "finalization_retry"`
- retain `tool_history`
- clear:
  - `available_tools`
  - `requested_tool_name`
  - `requested_tool_payload`
  - `tool_result`
- request must expose no callable tools and no forced tool choice
- transport timeout and retry budgets must stay in the interactive/tool-followup family

- [ ] **Step 1: Write the failing tests**

Lock:

- retry instruction says all required tool results already exist and no more tools are needed
- chat-completions payload for `finalization_retry` contains no `tools`
- responses payload for `finalization_retry` contains no `tools`
- transport diagnostics still show `request_kind = "finalization_retry"`
- timeout / retry policy stays aligned with interactive followup behavior

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_llm_client \
  tests.test_llm_transport
```

Expected:

- failures because there is no retry-specific request shape yet

- [ ] **Step 3: Implement the request builder and instruction helper**

Required helper:

- `build_finalization_retry_request(...)`

Required behavior:

- preserve the executed `tool_history`
- expose no callable tools
- remain prompt-compatible with current tool-followup message assembly

- [ ] **Step 4: Update transport budgeting**

Implement the narrowest possible change in `openai_compat.py` so `finalization_retry` keeps:

- tool-followup timeout behavior
- interactive-class retry policy

Avoid any broader request-kind refactor.

- [ ] **Step 5: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_llm_client \
  tests.test_llm_transport
```

**Done means:**

- retry requests are distinct in diagnostics
- retry requests expose no tools
- provider budgeting stays aligned with interactive followup

### Task 2: Replace fixed-sequence recovery with generic finalization assessment

**Files:**
- Modify: `src/marten_runtime/runtime/recovery_flow.py`
- Modify: `tests/test_recovery_flow.py`

**Constraints:**
- classify post-tool final text into:
  - accepted
  - retryable degraded
  - unrecoverable
- degraded means:
  - empty text
  - generic tool-failure copy
  - exact normalized strict ordered subsequence of safe fragments
- no fixed tool-name checks

- [ ] **Step 1: Write the failing tests**

Lock:

- empty final text becomes retryable when safe fragments exist
- generic failure-copy text becomes retryable
- strict ordered subsequence becomes retryable
- richer non-subsequence free-form text is accepted unchanged
- no safe fragments means unrecoverable

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_recovery_flow
```

Expected:

- failures because recovery still depends on the fixed three-step helper

- [ ] **Step 3: Implement generic assessment helpers**

Recommended minimal shape:

- `assess_finalization_text(...)`
- `recover_successful_tool_followup_text(...)`
- `recover_tool_result_text(...)`

Keep earlier-stage tool-failure recovery behavior unless a focused test proves it must move.

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_recovery_flow
```

**Done means:**

- recovery flow no longer depends on fixed ordered tool names
- degraded-final assessment is generic and fully tested

### Task 3: Integrate one-shot retry and fallback into `RuntimeLoop`

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/runtime/tool_followup_support.py`
- Modify: `tests/runtime_loop/test_tool_followup_and_recovery.py`
- Modify: `tests/runtime_loop/test_direct_rendering_paths.py`

**Constraints:**
- store `recovery_fragment` on `tool_history`
- preserve terminal direct-render early exits
- allow exactly one finalization retry
- retry phase may not execute more tools
- richer free-form final answers must pass through unchanged

- [ ] **Step 1: Write the failing tests**

Lock:

- successful multi-tool chain with good final text ends without retry
- degraded final text triggers exactly one retry
- retry success returns retry text
- retry degraded result falls back to aggregated fragments
- retry request carries `request_kind = "finalization_retry"`
- no extra tool loop occurs after retry starts

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_direct_rendering_paths
```

Expected:

- failures because the loop still uses the fixed helper upgrade path and has no finalization-retry stage

- [ ] **Step 3: Implement the loop changes**

Required minimal behavior:

- after each successful tool call:
  - update `tool_history[-1].tool_result`
  - attach `tool_history[-1].recovery_fragment`
- on final text:
  - accept as-is when assessment says accepted
  - otherwise perform one retry
  - if retry still degrades and safe fragments exist, finalize with aggregated fragments

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_direct_rendering_paths
```

**Done means:**

- loop owns one generic post-tool finalization contract
- terminal early exits still work
- retry and fallback behavior is fully covered

## Chunk 4: Fixed-Helper Deletion And Regression Replacement

### Task 1: Delete the fixed ordered helper path from source and tests

**Files:**
- Modify: `src/marten_runtime/runtime/direct_rendering.py`
- Modify: `src/marten_runtime/runtime/recovery_flow.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `tests/test_direct_rendering.py`
- Modify: `tests/test_recovery_flow.py`

**Constraints:**
- remove:
  - `render_direct_tool_history_text(...)` in its current fixed ordered form
  - `is_partial_direct_tool_history_text(...)`
  - any private helper that exists only to recognize `[time, runtime.context_status, mcp.list]`
- keep generic fragment helpers and single-tool renderers

- [ ] **Step 1: Delete the fixed-path tests first**

Remove or rewrite tests that currently lock:

- fixed three-step history rendering
- fixed partial-sequence recovery behavior

- [ ] **Step 2: Delete the fixed-path source helpers**

Remove the old helpers and imports after the generic replacements are already green.

- [ ] **Step 3: Run anti-drift grep**

Run:

```bash
rg -n "render_direct_tool_history_text|is_partial_direct_tool_history_text|time\", \"runtime\", \"mcp\"" \
  src/marten_runtime/runtime tests
```

Expected:

- no remaining source helper that privileges the fixed three-step path

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_direct_rendering \
  tests.test_recovery_flow \
  tests.runtime_loop.test_tool_followup_and_recovery
```

**Done means:**

- fixed ordered helper code is gone
- tests now lock only generic fragment behavior

### Task 2: Rebuild acceptance coverage on the new contract

**Files:**
- Modify: `tests/test_acceptance.py`
- Modify: `tests/runtime_loop/test_tool_followup_and_recovery.py`

**Constraints:**
- acceptance may still use `time -> runtime -> mcp` as one real chain example
- the code path must stay generic
- keep live-relevant ordered-chain proof because that is the regression that originally exposed the gap

- [ ] **Step 1: Write the failing acceptance / integration assertions**

Lock:

- ordered multi-tool requests still return all required results
- final text remains truthful to execution order
- no privileged fixed helper is required for this chain to pass

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_acceptance \
  tests.runtime_loop.test_tool_followup_and_recovery
```

Expected:

- failures if acceptance still depends on the old helper names or old deterministic wording

- [ ] **Step 3: Implement the acceptance updates**

Prefer:

- assertions on coverage of truthful blocks
- assertions on retry / fallback diagnostics when appropriate

Avoid:

- hard-locking one exact prose shape if the generic retry path can still yield a stronger model-authored answer

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_acceptance \
  tests.runtime_loop.test_tool_followup_and_recovery
```

**Done means:**

- acceptance protects the user-visible regression
- source implementation remains generic

## Chunk 5: Documentation Sync And Final Verification

### Task 1: Sync architecture and continuity docs

**Files:**
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `STATUS.md`
- Optionally update status line in:
  - `docs/2026-04-22-generic-loop-finalization-contract-design.md`

**Constraints:**
- changelog entry must describe the durable contract change
- `STATUS.md` must stop advertising the deleted fixed helper as the intended final shape
- do not rewrite history; append concise factual updates

- [ ] **Step 1: Update `ARCHITECTURE_CHANGELOG.md`**

Record:

- why the fixed ordered helper was removed
- what the new generic contract is
- what verification proved it

- [ ] **Step 2: Update `STATUS.md`**

Record:

- design completed
- implementation completed
- tests run
- current live-proof status if attempted

- [ ] **Step 3: Re-check design / plan alignment**

Manual checklist:

- terminal render and fragment remain separate
- fragment metadata stays runtime-only
- retry stays one-shot and no-tools
- fixed ordered helper path is deleted

### Task 2: Run final verification

**Files:**
- No new edits expected

- [ ] **Step 1: Run focused contract suites**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_tool_followup_support \
  tests.test_direct_rendering \
  tests.test_recovery_flow \
  tests.test_llm_client \
  tests.test_llm_transport \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.test_acceptance
```

- [ ] **Step 2: Run adjacent regression suites**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_gateway \
  tests.test_runtime_capabilities \
  tests.contracts.test_runtime_contracts \
  tests.contracts.test_gateway_contracts
```

- [ ] **Step 3: Run syntax and diff hygiene checks**

Run:

```bash
python -m py_compile \
  src/marten_runtime/runtime/llm_client.py \
  src/marten_runtime/runtime/tool_followup_support.py \
  src/marten_runtime/runtime/direct_rendering.py \
  src/marten_runtime/runtime/recovery_flow.py \
  src/marten_runtime/runtime/loop.py \
  src/marten_runtime/runtime/llm_message_support.py \
  src/marten_runtime/runtime/llm_request_instructions.py \
  src/marten_runtime/runtime/llm_adapters/openai_compat.py

git diff --check
```

- [ ] **Step 4: Run one local runtime smoke if provider and local server are available**

Recommended smoke:

```bash
curl -sS http://127.0.0.1:8000/messages \
  -H 'Content-Type: application/json' \
  -d '{"channel_id":"feishu","user_id":"u_generic_loop_probe","conversation_id":"conv_generic_loop_probe","message_id":"msg_generic_loop_probe","body":"请严格按顺序先调用 time 获取当前时间，再调用 runtime 查看当前 run 的 context_status，再调用 mcp 列出 github server 的可用工具，最后用中文总结这次链路，并明确说明这次请求是否发生了多次模型/工具往返。"}'
```

Expected:

- reply is complete and truthful
- source code contains no fixed three-step helper
- success comes from generic retry / fragment fallback or stronger model-authored final text

If this smoke is blocked by unavailable credentials or runtime process state, treat it as a real blocker and record:

- what unit/integration proof already passed
- what exact dependency is unavailable
- what command should be rerun once unblocked

## Completion Criteria

This plan is complete in implementation when all of the following are true:

1. `ToolFollowupRender` and `ToolFollowupFragment` exist and are used in the runtime loop
2. `recovery_fragment` remains runtime-only and stays out of provider payloads and durable session replay
3. `RuntimeLoop` performs one bounded `finalization_retry` with no tools and no forced `tool_choice`
4. `openai_compat` treats `finalization_retry` as interactive-class for timeout and retry budgeting
5. degraded-final detection uses exact normalized ordered fragment blocks only
6. deterministic fallback aggregates safe fragments in execution order
7. fixed ordered helper code and its privileged tests are deleted
8. existing single-tool direct-render and terminal paths still pass
9. focused, adjacent, syntax, and diff checks pass
10. docs and `STATUS.md` describe the new contract accurately

## Anti-Drift Review Before Execution Ends

Before claiming the work is done, re-open:

- `docs/2026-04-22-generic-loop-finalization-contract-design.md`
- this implementation plan
- `STATUS.md`

Then confirm:

- no chunk introduced a new host-side intent router
- no chunk reintroduced a fixed tool-name sequence helper
- no chunk widened `llm_request_instructions.py` into a routing layer
- no chunk leaked fragment metadata into provider prompts or durable history
- no chunk replaced generic tests with one brittle prose snapshot
