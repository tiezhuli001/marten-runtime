Date: 2026-04-22
Status: Draft for review
Scope: design only; implementation stays for the next stage after design review

# Generic Loop Finalization Contract Design

## Goal

Replace the current fixed-sequence ordered-tool recovery with one generic loop finalization contract that:

- keeps free-form tool choice model-driven under ADR 0004
- removes the hardcoded `[time, runtime.context_status, mcp.list]` success-path recovery shape
- preserves the thin harness boundary
- gives the runtime one bounded, truthful fallback path when tools have already succeeded and the provider returns an incomplete final answer

This design also explicitly removes the current fixed-sequence helper and its tests from the target shape. They are temporary drift and should not remain in the repository after implementation.

## Design Outcome

This design targets five concrete outcomes:

1. Multi-tool turns finalize through one generic contract instead of a tool-name-specific stitched text path.
2. Single-tool terminal direct renders remain available for narrow tool results that are already product-approved and user-ready.
3. Successful tool chains gain one bounded finalization retry before the runtime falls back to deterministic fragment aggregation.
4. Recovery stays truthful to executed tool results and execution order.
5. The repository loses the fixed `[time, runtime.context_status, mcp.list]` helper and the tests that lock that sequence.

## Current Repository Baseline

The repository already has three relevant seams:

1. `RuntimeLoop` owns the iterative `LLM -> tool -> LLM` cycle.
2. `tool_followup_support.py` already normalizes tool results and can surface direct followup text.
3. `direct_rendering.py` already owns deterministic last-mile text rendering for a small set of tool results.

The current drift sits across these files:

- `src/marten_runtime/runtime/direct_rendering.py`
- `src/marten_runtime/runtime/recovery_flow.py`
- `src/marten_runtime/runtime/loop.py`

Today the runtime contains a fixed-sequence path that:

- recognizes exactly three tool calls in order:
  - `time`
  - `runtime.context_status`
  - `mcp.list`
- reconstructs one deterministic combined text for that sequence
- treats strict partial matches of that combined text as recoverable success-path degradation

That shape widens a narrow direct-render helper into a generic success-path policy. The loop contract becomes coupled to one specific tool list, one specific order, and one specific wording shape.

## Problem Statement

The current patch fixes one live symptom and leaves the steady-state contract in a poor shape.

The actual design problem is broader:

1. the runtime has no explicit generic finalization contract after one or more successful tool calls
2. the only deterministic multi-step recovery path is hardcoded to one tool sequence
3. the success path now depends on specific tool names instead of generic loop state

This conflicts with:

- ADR 0001 thin-harness ownership
- ADR 0004 LLM-first tool selection
- the repository goal of keeping recovery generic and local instead of growing tool-specific host logic

## Constraints

- preserve ADR 0004:
  - free-form natural-language tool choice stays with the model
- preserve the main runtime path:
  - `channel -> binding -> runtime loop -> builtin/MCP/skill -> delivery`
- keep the harness thin:
  - no new host-side intent router
  - no tool-name-specific success-path orchestrator
- keep recovery bounded:
  - at most one explicit finalization retry after tools have already succeeded
- keep fallback truthful:
  - runtime may aggregate only already-executed tool results and runtime-owned loop facts
- keep scope local:
  - no workflow engine
  - no planner layer
  - no background reconciliation worker
- remove the existing fixed three-step ordered helper and the tests that encode it

## Non-Goals

- changing free-form initial tool selection behavior
- redesigning the provider adapter protocol
- introducing a general host-side natural-language interpretation layer
- adding a product-wide structured response format for every final answer
- making deterministic fallback reproduce every stylistic nuance of a free-form user request

This slice guarantees truthful delivery of already-executed tool results on degraded finalization. It does not guarantee full reproduction of every narrative or analytical flourish when the final fallback path is used.

## Reference Comparison

Local reference repositories converge on the same principle:

1. `nanobot` keeps the loop state generic:
   - assistant produces tool calls
   - runtime executes them
   - next iteration receives tool results
   - run ends with one explicit final content / stop condition

2. `openclaw` exposes generic run-state outcomes:
   - `stopReason`
   - `pendingToolCalls`
   - explicit end-of-run metadata

3. Neither reference implementation hardcodes one specific multi-tool sequence into the loop success path.

The right adaptation for `marten-runtime` is therefore one generic finalization contract with bounded recovery, not a growing library of fixed ordered tool sequences.

## Approaches Considered

### Approach A — Remove the fixed helper and keep only generic failure-copy recovery

Pros:

- smallest code change
- deletes the current drift quickly

Cons:

- multi-tool degraded final text still has no strong recovery path
- truthful tool results can still collapse to an empty or incomplete answer

### Approach B — Generic fragment-based finalization contract

Pros:

- generic for any tool order and any number of successful tool calls
- keeps steady-state answering model-first
- keeps deterministic logic limited to recovery and direct-render seams
- fits the existing `tool_followup_support` and `direct_rendering` boundaries

Cons:

- requires one new explicit followup data model
- requires a small restructuring of direct-render and recovery ownership

### Approach C — Fully structured finalization envelope from the model

Pros:

- strongest machine-verifiable finalization contract
- easiest to reason about in the loop once adopted

Cons:

- broader transport and provider change surface
- larger product decision than this repository slice needs right now

### Recommendation

Use **Approach B**.

It gives `marten-runtime` a general loop finalization contract with minimal architectural expansion and keeps free-form tool selection and normal final answer wording in the model.

## Proposed Design

## 1. Canonical Loop Contract

After this change, the loop should treat “successful tool execution” and “final text finalization” as two distinct stages.

The runtime owns these explicit outcome states:

1. `tool_calls_pending`
   - the model requested one or more tools
2. `tool_results_available`
   - the runtime has executed tools and recorded their results
3. `final_text_accepted`
   - the provider returned a usable final answer
4. `finalization_retry`
   - the provider returned a degraded final answer after successful tools, so the runtime performs one bounded text-only retry
5. `final_text_recovered`
   - the retry still degraded, so the runtime finalizes from deterministic recovery fragments
6. `error`
   - the loop could not produce a visible final answer

This turns the contract into state-based loop ownership instead of tool-name-specific postprocessing.

## 2. Separate Two Surfaces: Terminal Direct Render And Recovery Fragment

The current code path conflates two different ideas:

- “this tool result already is the final answer”
- “this tool result can contribute truthful fallback material if the final answer later degrades”

The new contract should separate them explicitly.

### 2.1 Terminal direct render

This remains a narrow, opt-in seam for tool results that are already complete and product-approved as final user text.

Examples that can stay in this category:

- `runtime.context_status`
- `session.list` / `session.show` / `session.new` / `session.resume`
- `spawn_subagent` accepted / queued acknowledgements
- selected builtin deterministic list/show operations

Terminal direct render stays narrow and tool-local.

### 2.2 Recovery fragment

This is new explicit loop material for degraded finalization.

Each successful tool step may optionally contribute one deterministic fragment that is:

- truthful to the executed tool result
- bounded in size
- stable enough for fallback aggregation
- independent of model stylistic phrasing

Recovery fragments do not short-circuit the loop by themselves.

They exist only so the runtime can recover a truthful final answer when the model has already finished calling tools and then degrades on the last textual answer.

## 3. Data Contract

Add one explicit followup model to the runtime layer.

Illustrative shape:

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

Then extend `ToolExchange` with one optional field:

```python
class ToolExchange(BaseModel):
    tool_name: str
    tool_payload: dict = Field(default_factory=dict)
    tool_result: dict = Field(default_factory=dict)
    recovery_fragment: ToolFollowupFragment | None = None
```

Why this shape:

- it keeps followup recovery material explicit
- it avoids hiding recovery semantics inside one raw string
- it keeps tool history as the single source of truth for executed tool results plus recovery surface
- prompt serialization can continue to expose only `tool_name`, `tool_payload`, and `tool_result` to the model

The model does not need the fragment metadata in its prompt.

`recovery_fragment` is runtime-only metadata.

It should:

- stay on in-memory loop state
- remain available to runtime-owned recovery assessment
- stay out of provider-visible tool call serialization
- stay out of durable session replay and persisted transcript history in this slice

## 4. Rendering Ownership

`direct_rendering.py` should move to one explicit ownership rule:

1. single-step terminal renderers
2. single-step recovery fragment renderers
3. generic fragment aggregation helpers

It should stop owning fixed ordered tool-sequence logic.

### 4.1 Keep

- `render_direct_tool_text(...)` or its equivalent single-tool renderer
- narrow tool-local helpers for:
  - runtime
  - time
  - session
  - automation
  - selected MCP outputs
  - subagent acknowledgement text

### 4.2 Remove

- `render_direct_tool_history_text(...)` in its current fixed-sequence form
- `is_partial_direct_tool_history_text(...)`
- the private helper that recognizes exactly `[time, runtime.context_status, mcp.list]`

### 4.3 Replace with generic helpers

Introduce generic helpers shaped around fragments, for example:

- `render_recovery_fragment(...)`
- `render_recovery_fragments_text(...)`
- `is_partial_fragment_aggregation(...)`

The generic aggregation rule should depend only on ordered fragment blocks, not on specific tool names.

## 5. Generic Finalization Assessment

`recovery_flow.py` should move from fixed-sequence helper calls to one generic finalization assessment contract.

It should classify the post-tool final text into one of these buckets:

1. `accepted`
   - non-empty final text that does not look degraded against the fragment set
2. `retryable_degraded`
   - empty text
   - generic failure-copy text
   - strict ordered subsequence of available recovery fragments
3. `unrecoverable`
   - no fragments available and no acceptable final text

### 5.1 Ordered subsequence rule

The generic subset detector should work on normalized fragment blocks.

Canonical rule:

- normalize each fragment text into one block
- aggregate full fallback text as ordered blocks joined by blank lines
- treat provider final text as degraded when it equals a strict ordered subsequence of those blocks

This is an exact normalized block match, not a fuzzy substring match and not semantic similarity matching.

Examples of degraded matches:

- only the last block
- first and third blocks with the second omitted
- the first two blocks with later blocks omitted

This remains generic for any `N` because it reasons over ordered fragment blocks instead of tool names.

The detector should stay bounded by the existing loop ceiling:

- `RuntimeLoop.max_tool_rounds = 8`

### 5.2 Safety rule

The runtime should only use fragments whose `safe_for_fallback` flag is true.

This keeps the deterministic fallback limited to outputs that tools explicitly marked as safe and user-presentable.

## 6. Finalization Retry Contract

When tools have already succeeded and the provider returns degraded final text, the runtime should perform exactly one explicit finalization retry before deterministic fallback.

### 6.1 Retry shape

The retry should be:

- text-only
- bounded to one additional provider call
- built from the same conversation state and executed tool results
- forbidden from issuing more tools

This contract is important. Once tools have already succeeded and the loop is in finalization recovery, the goal is to produce the final answer from existing results, not to reopen tool selection.

### 6.2 Retry request contract

The retry request should:

- reuse:
  - current user message
  - conversation messages
  - compact summary
  - memory
  - executed tool history
- set `request_kind = "finalization_retry"` so diagnostics and transport tests can distinguish it from ordinary interactive turns
- clear available tools for that retry
- clear:
  - `requested_tool_name`
  - `requested_tool_payload`
  - `tool_result`
- add one narrow system instruction such as:
  - all required tool results are already present
  - produce one final answer from existing results
  - do not call more tools
  - do not omit already-returned successful tool results when they are part of the answer

The retry request remains a tool-followup-shaped prompt because it still carries `tool_history`, but it must expose no callable tools to the provider.

Transport behavior for `finalization_retry` should stay aligned with interactive post-tool turns:

- timeout budget should follow the existing tool-followup timeout class
- retry policy should stay in the interactive family rather than dropping to a background/default class only because the request kind changed for diagnostics

This keeps the recovery generic and loop-owned.

## 7. Deterministic Fallback Contract

If the retry still degrades, the runtime finalizes from fragments.

The fallback should:

- aggregate safe fragments in tool execution order
- skip empty fragments
- keep formatting simple and truthful
- avoid tool-name-specific stitching logic

This fallback is a truth-preserving last-mile recovery seam.

It does not need to reconstruct every higher-level analytical sentence that a strong model answer could provide.

If the product later requires stronger guarantees for analytical or cross-step synthesis, the next step should be a structured finalization envelope. That is outside this slice.

## 8. Loop Algorithm

The runtime loop should follow this algorithm after the change:

1. model asks for a tool
2. runtime executes the tool
3. runtime records:
   - `tool_name`
   - `tool_payload`
   - `tool_result`
   - optional `recovery_fragment`
4. runtime checks for `terminal_text`
   - if present and the tool path is explicitly terminal, finalize immediately
5. runtime continues normal tool-followup iteration
6. model eventually returns `final_text` with no further tool call
7. runtime assesses finalization:
   - accept
   - retry
   - error
8. if retry:
   - issue one text-only finalization retry with no tools
9. assess retry result
10. if still degraded and fragments exist:
   - finalize from aggregated fragments
11. if no accepted text and no safe fragments:
   - use the existing error path

This keeps model synthesis as the primary path and deterministic aggregation as the bounded recovery seam.

## 9. Module-Level Changes

## 9.1 `src/marten_runtime/runtime/llm_client.py`

- add `ToolFollowupFragment`
- extend `ToolExchange` with optional `recovery_fragment`

## 9.2 `src/marten_runtime/runtime/tool_followup_support.py`

- replace the current raw `str | None` followup return with a structured surface
- keep the existing normalization role
- distinguish:
  - `terminal_text`
  - `recovery_fragment`

This file becomes the bridge between tool results and the loop contract.

## 9.3 `src/marten_runtime/runtime/direct_rendering.py`

- keep single-tool terminal renderers
- add single-tool recovery fragment renderers
- add generic fragment aggregation helpers
- delete the fixed `[time, runtime.context_status, mcp.list]` sequence helper path

## 9.4 `src/marten_runtime/runtime/recovery_flow.py`

- replace fixed-sequence recovery with generic fragment-based assessment
- own:
  - degraded-text detection
  - finalization retry eligibility
  - deterministic fragment aggregation

## 9.5 `src/marten_runtime/runtime/loop.py`

- use structured followup render data after each tool call
- store recovery fragments on `tool_history`
- add one bounded text-only finalization retry path
- remove the current call site that upgrades non-empty final text through the fixed three-step helper

## 9.6 `src/marten_runtime/runtime/llm_message_support.py`

- support a finalization-retry request shape with no available tools
- keep ordinary tool-followup request construction unchanged

## 9.7 `src/marten_runtime/runtime/llm_request_instructions.py`

- add one narrow retry-specific instruction helper for `finalization_retry`
- keep it scoped to “all required tool results are already present; answer from them directly”
- do not turn this module into a routing or fallback policy layer

## 9.8 `src/marten_runtime/runtime/llm_adapters/openai_compat.py`

- treat `finalization_retry` as an interactive-class request for timeout and retry budgeting
- keep request-kind diagnostics explicit as `finalization_retry`

## 10. Migration And Deletion Plan

The implementation should treat the current narrow ordered helper as temporary drift and delete it.

Delete from source:

- the fixed ordered-tool history renderer
- the fixed ordered partial-match detector
- any helper whose only job is to recognize `[time, runtime.context_status, mcp.list]`

Delete from tests:

- tests that lock the exact fixed three-step history renderer
- tests that lock the exact fixed partial-sequence recovery behavior

Replace them with generic tests that lock:

- fragment aggregation over arbitrary ordered tool histories
- generic degraded-final-text detection
- one bounded text-only retry before fallback
- richer free-form model answers surviving unchanged

## 11. Edge Cases And Boundaries

### 11.1 Tools with no recovery fragment

Some tools should provide no fragment.

Examples:

- large raw outputs that still require model synthesis
- outputs with unsafe verbosity
- outputs whose truthful deterministic rendering is unclear

In those cases:

- normal model finalization remains the primary path
- deterministic fallback may be partial or unavailable

### 11.2 Mixed histories

A multi-tool turn may contain:

- terminal direct-render-capable tools
- fragment-capable tools
- tools with no fragment support

The contract should allow this mixed history without special casing the tool list.

### 11.3 Provider returns a richer free-form final answer

If the provider returns a complete answer that is richer than the deterministic fragment aggregation, the runtime accepts it.

Fragment recovery exists only for degraded finalization.

### 11.4 Provider returns partial block coverage

If the provider returns text equal to a strict ordered subsequence of the safe fragment blocks, the runtime treats it as degraded and enters retry.

### 11.5 Tool execution failure before finalization

The current earlier-stage failure recovery path can remain:

- if a later tool fails and the runtime already has one earlier truthful terminal render available, it may still deliver that earlier render according to existing behavior

This design slice is focused on successful-tool finalization drift, not on broad failure-mode redesign.

## 12. Test Design

### Focused unit tests

- `tests/test_direct_rendering.py`
  - generic fragment rendering for single tools
  - generic ordered fragment aggregation
  - no fixed sequence helper remains

- `tests/test_recovery_flow.py`
  - empty final text with fragments triggers retry/fallback eligibility
  - generic failure-copy text triggers retry/fallback eligibility
  - strict ordered fragment subsequence triggers retry/fallback eligibility
  - richer non-subsequence free-form text is accepted unchanged

- `tests/test_tool_followup_support.py`
  - tool result normalization returns structured followup surface
  - terminal direct render and recovery fragment stay distinct

### Runtime-loop regressions

- `tests/runtime_loop/test_tool_followup_and_recovery.py`
  - successful multi-tool chain with strong final model text stays model-authored
  - successful multi-tool chain with degraded final text performs one text-only retry
  - retry success returns retry text
  - retry degradation falls back to aggregated fragments
  - retry request carries no tools
  - retry request is recorded as `request_kind = "finalization_retry"`

### Acceptance coverage

- `tests/test_acceptance.py`
  - ordered multi-tool requests still complete end to end without fixed tool-sequence helpers
  - deterministic fallback is truthful to executed results and execution order

### Transport coverage

- `tests/test_llm_transport.py`
  - `finalization_retry` carries no `tools` and no forced `tool_choice`
  - ordinary interactive first-turn behavior stays unchanged

### Deletion assertions

Tests should actively prove removal of the fixed path by ensuring:

- no source helper remains that recognizes the hardcoded three-step sequence
- no test fixture depends on `[time, runtime.context_status, mcp.list]` as a privileged recovery contract

## 13. Completion Criteria

This design is complete in implementation when all of the following are true:

1. the fixed ordered `[time, runtime.context_status, mcp.list]` helper path is deleted from source and tests
2. multi-tool finalization recovery is expressed through generic fragment-aware logic
3. the loop performs one bounded text-only finalization retry before deterministic fallback
4. deterministic fallback aggregates only safe ordered fragments from executed tool results
5. free-form richer model answers still pass through unchanged
6. no host-side free-form intent router is introduced
7. focused unit, runtime-loop, and acceptance tests pass on the new contract

## References

- `docs/architecture/adr/0001-thin-harness-boundary.md`
- `docs/architecture/adr/0004-llm-first-tool-routing-boundary.md`
- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/recovery_flow.py`
- `src/marten_runtime/runtime/direct_rendering.py`
- local reference code:
  - `nanobot-main/nanobot/agent/runner.py`
  - `openclaw-main/src/agents/pi-embedded-runner/run.ts`
