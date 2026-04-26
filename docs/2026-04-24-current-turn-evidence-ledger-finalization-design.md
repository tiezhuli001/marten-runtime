Date: 2026-04-24
Status: Draft for review
Scope: design only; implementation stays for the next stage after design review

# Current-Turn Evidence Ledger Finalization Design

## Goal

Strengthen multi-tool finalization in `marten-runtime` by making the model finalize against one explicit, runtime-built **current-turn evidence ledger** instead of relying only on raw tool transcript plus thin generic followup wording.

This design targets the specific failure class where:

- tool selection is already correct
- tool execution already succeeds
- the final assistant answer is too thin
- the final answer omits one or more required current-turn results
- the runtime should have enough evidence to force a complete answer without introducing host-side natural-language routing

The target outcome is:

1. preserve ADR 0004 LLM-first tool routing
2. make finalization quality depend on clearer current-turn evidence, not host-side request classification
3. keep deterministic fallback bounded and truthful
4. improve observability so live acceptance/retry mismatches are diagnosable from one run record

## Design Outcome

This design targets six concrete outcomes:

1. Multi-tool finalization gets one explicit **current-turn evidence ledger** assembled from executed tool history and loop metadata.
2. Followup and finalization-retry prompts receive both the canonical tool transcript and one structured evidence summary of what must be covered.
3. The model stays responsible for the final answer wording and synthesis.
4. The runtime keeps one bounded last-line contract check for omission, empty final text, and false execution claims.
5. Thin final answers that omit required current-turn results trigger one visible, explainable retry/recovery path.
6. Diagnostics expose whether finalization failed because of prompt quality, model output quality, or recovery-path execution drift.

## Current Repository Baseline

The current repository already has the right low-level seams:

1. `loop.py`
   - owns the iterative `LLM -> tool -> LLM` cycle
   - already distinguishes normal followup from `finalization_retry`

2. `llm_message_support.py`
   - serializes tool transcript as canonical assistant tool-call + tool-result messages
   - already keeps the user message as the final user turn in the request

3. `tool_followup_support.py`
   - already normalizes tool results into `ToolExchange`
   - already carries deterministic `recovery_fragment`

4. `recovery_flow.py`
   - already has bounded acceptance / degraded / unrecoverable assessment
   - already has fragment coverage checks for some current-turn result requests

5. `llm_request_instructions.py`
   - already owns generic prompt contracts for followup and finalization retry

This means the repository already has:

- canonical transcript replay
- a finalization retry mode
- a recovery fragment seam
- a contract checker

The remaining gap is that the model still receives the current-turn evidence in a weak form:

- tool transcript is present
- prompt hints exist
- required result coverage is checked afterward
- but the model is not given one explicit runtime-built summary of **which current-turn evidence items matter for this answer**

## Problem Statement

The live failure shape is now narrower and clearer than before.

The problem is no longer primarily tool selection.

The current failure class is:

1. the user asks for a multi-step current-turn chain
2. the model selects the right tools
3. the runtime executes them successfully
4. the model emits a thin final answer like “链路已完成，发生了多次往返”
5. the answer omits one or more tool results the user explicitly asked to summarize

That means the weak point sits in **finalization evidence presentation and enforcement**, not in first-turn routing.

The design therefore should improve:

- what the model sees at finalization time
- how the runtime communicates current-turn obligations
- how the runtime diagnoses acceptance / retry / recovery decisions

The design should avoid:

- host-side natural-language family routing
- new regex-based request classification
- tool-specific summary hardcoding
- channel-specific answer logic

## Reference Comparison

Local reference repositories converge on one shared pattern.

### `nanobot`

Relevant files:

- `/Users/litiezhu/workspace/github/nanobot-main/nanobot/agent/runner.py`
- `/Users/litiezhu/workspace/github/nanobot-main/nanobot/session/manager.py`
- `/Users/litiezhu/workspace/github/nanobot-main/nanobot/providers/openai_responses/converters.py`

Observed pattern:

- session history preserves user / assistant / tool transcript explicitly
- tool calls and tool results remain first-class conversation members
- send-time governance repairs malformed transcript boundaries
- final answer generation still depends on the model reading canonical transcript

### `openclaw`

Relevant files:

- `/Users/litiezhu/workspace/github/openclaw-main/src/agents/transcript-policy.ts`
- `/Users/litiezhu/workspace/github/openclaw-main/src/agents/pi-embedded-helpers/turns.ts`
- `/Users/litiezhu/workspace/github/openclaw-main/src/agents/openai-ws-message-conversion.ts`

Observed pattern:

- provider-specific shapes are normalized into one legal transcript contract
- orphan tool results, tool ids, reasoning replay, and turn ordering are runtime-owned concerns
- once transcript legality is restored, the model still performs final synthesis

### `opencode`

Relevant files:

- `/Users/litiezhu/workspace/code/ai/opencode/packages/opencode/src/session/message-v2.ts`
- `/Users/litiezhu/workspace/code/ai/opencode/packages/opencode/src/session/processor.ts`
- `/Users/litiezhu/workspace/code/ai/opencode/packages/opencode/src/session/prompt.ts`

Observed pattern:

- tool execution is stored as structured message parts
- `toModelMessages()` reconstructs model-visible transcript from durable structured parts
- tool result state stays explicit and model-readable
- final answer remains model-authored from current-turn transcript state

### Design Implication

These references do **not** solve the problem by adding host-side natural-language routing.

They solve it by improving one or both of these:

1. transcript quality
2. current-turn execution-state visibility to the model

`marten-runtime` already has the transcript piece.

This design therefore adds the missing **current-turn evidence visibility** piece.

## Constraints

- preserve ADR 0004:
  - free-form tool family selection stays with the model
- preserve the thin harness boundary:
  - no host-side natural-language router
  - no request-keyword dispatch table for ordinary user text
- keep the runtime spine unchanged:
  - `channel -> binding -> runtime loop -> builtin/MCP/skill -> finalization -> delivery`
- keep deterministic recovery bounded:
  - at most one explicit finalization retry after tools have already succeeded
- keep recovery truthful:
  - recovery may only use executed tool results and runtime-owned loop metadata
- keep the design channel-agnostic:
  - Feishu is one delivery surface, not a special finalization owner
- keep tool result ownership local:
  - tool-specific rendering stays in tool-local direct-render / fragment seams
- avoid new broad structured-output mandates for all model replies
- keep the implementation local to runtime finalization surfaces

## Non-Goals

This slice does not:

- redesign first-turn tool choice
- add host-side routing for time / runtime / session / mcp / subagent requests
- replace canonical assistant/tool transcript replay
- require every final answer to be fully structured JSON
- add workflow/planner orchestration
- add a new provider protocol
- bind finalization correctness to Feishu-specific rendering rules

## Approaches Considered

### Approach A — keep current transcript + strengthen only post-hoc validator

Pros:

- smallest code change
- keeps current prompt surface almost unchanged

Cons:

- model still sees weak current-turn evidence organization
- validator catches failures late
- repeated retry/recovery pressure remains high

### Approach B — current-turn evidence ledger + existing validator as last line

Pros:

- keeps the model in charge of synthesis
- improves current-turn evidence visibility before the answer is generated
- aligns with reference repos: better transcript/state, not host-side routing
- keeps deterministic validator as a bounded safety layer
- generalizes across builtin, MCP, skill, subagent, session, runtime, and time tools

Cons:

- adds one new runtime-owned prompt input surface
- requires small refactoring across prompt assembly, loop, and diagnostics

### Approach C — full structured final-answer schema with machine-verified per-field coverage

Pros:

- strongest enforcement
- easiest machine verification

Cons:

- much larger product and provider surface
- overreaches for this failure class
- widens the harness beyond the current repository goal

### Recommendation

Use **Approach B**.

This gives `marten-runtime` one stronger LLM-first finalization contract:

- runtime structures current-turn evidence
- model writes the answer
- runtime validates and retries only when needed

## Proposed Design

## 1. Canonical Finalization Model

Finalization should operate on three layers of evidence, in this order:

1. **current user message**
   - source of task scope for this turn
2. **canonical current-turn tool transcript**
   - assistant tool call + tool result messages
3. **current-turn evidence ledger**
   - runtime-built compact summary of which executed results matter for finalization

The ledger does not replace transcript replay.

It supplements transcript replay with one more explicit model-facing surface.

## 2. Current-Turn Evidence Ledger

### 2.1 Purpose

The ledger exists to answer one question for the model:

**For this turn, what evidence has already been obtained, and what evidence must the final answer cover?**

### 2.2 Canonical shape

Illustrative shape:

```python
class FinalizationEvidenceItem(BaseModel):
    ordinal: int
    tool_name: str
    tool_action: str | None = None
    payload_summary: str | None = None
    result_summary: str
    required_for_user_request: bool = True
    evidence_source: Literal["tool_result", "loop_meta"] = "tool_result"


class FinalizationEvidenceLedger(BaseModel):
    user_message: str
    tool_call_count: int
    model_request_count: int | None = None
    requires_result_coverage: bool = False
    requires_round_trip_report: bool = False
    items: list[FinalizationEvidenceItem] = Field(default_factory=list)
```

This shape is intentionally runtime-owned and small.

### 2.3 Ledger assembly rules

The runtime assembles the ledger only from current-turn execution state:

1. iterate `tool_history` in execution order
2. for each successful tool step, generate one compact evidence item
3. generate one extra loop-meta evidence item when round-trip reporting is relevant
4. mark whether the current user message explicitly requires:
   - per-result coverage
   - round-trip statement

The required-coverage flags in the ledger are intentionally narrow runtime contract state, not a new host-side intent router.

- `required_for_user_request`
- `requires_result_coverage`
- `requires_round_trip_report`

These fields may only be derived from:

- existing generic finalization-contract signals already owned by the runtime
- structured request state such as `tool_followup` / `finalization_retry`
- executed current-turn tool history and runtime-owned loop metadata

These fields must not be derived by adding new free-form natural-language routing logic for ordinary user text.

In particular, ledger assembly must not:

- introduce new keyword / regex / phrase tables for general user intent classification
- assign tool-family ownership for ordinary natural-language requests
- grow into a second request router under the name of “coverage detection”

### 2.4 Allowed evidence sources

Only these sources may feed the ledger:

- `ToolExchange.tool_name`
- `ToolExchange.tool_payload`
- `ToolExchange.tool_result`
- `ToolExchange.recovery_fragment`
- runtime-owned counts such as `model_request_count` and `tool_call_count`

The ledger must not use:

- previous-turn summaries as current-turn facts
- channel-rendered text as evidence
- host-side inferred tool-family intent beyond current runtime contract checks

### 2.5 Evidence summary generation rule

Each evidence item should be generated from the same deterministic source already used for recovery fragments when available.

Priority:

1. `recovery_fragment.text`
2. direct deterministic tool render text
3. one thin runtime-owned synthetic summary derived from the tool result structure

This keeps one source of truth across:

- retry prompt input
- degraded fallback
- diagnostics

## 3. Prompt Contract Changes

## 3.1 Followup requests

For tool followup requests, keep the current transcript injection and add one new system block:

- current-turn evidence ledger
- coverage instruction for required items
- explicit statement of whether the user asked for round-trip reporting

Example shape:

```text
Current-turn evidence ledger:
1. time -> 现在是北京时间 2026年4月24日 21:23
2. runtime.context_status -> 当前上下文使用详情 ...
3. mcp.list(github) -> 当前可用 MCP 服务共 2 个 ...
4. loop_meta -> 本次请求共发生 4 次模型请求和 3 次工具调用，属于多次模型/工具往返。

Finalization requirements:
- You must cover every required evidence item above.
- The user explicitly asked for whether this request involved multiple model/tool round trips.
- Do not call a new tool when the existing evidence already answers the current turn.
```

## 3.2 Finalization retry requests

For `request_kind == "finalization_retry"`:

- remove available tool definitions as today
- keep canonical transcript as today
- inject the same evidence ledger block
- make the instruction stronger:
  - all required evidence items are already available
  - no new tool call is allowed
  - final answer must cover each required item

## 3.3 Current-turn scope rule

The existing current-turn priority contract remains.

The new ledger strengthens it by anchoring the final answer to this turn’s executed evidence instead of allowing the model to summarize at a higher, vaguer level.

## 4. Contract Enforcement Changes

## 4.1 Role of `recovery_flow.py`

`recovery_flow.py` should remain the last-line validator.

Its job becomes:

1. reject false execution claims
2. reject empty or generic tool-failure final text
3. reject omission of required evidence coverage
4. decide between:
   - `accepted`
   - `retryable_degraded`
   - `unrecoverable`

It should not become the primary place where semantic synthesis is reconstructed.

## 4.2 Coverage rule

Required coverage should be computed from the same ledger assembly rule.

That keeps one consistent source for:

- prompt input
- validator expectations
- degraded recovery fragments

## 4.3 Recovery path

When finalization still degrades after one retry:

- reuse the same required evidence items
- render bounded deterministic recovery text from those items in order
- include loop meta only when the current user request requires it

This keeps fallback truthful and aligned with the same evidence the model was asked to cover.

## 5. Observability Contract

The current mismatch between live behavior and offline replay shows that finalization needs clearer diagnostics.

### 5.1 Required diagnostics fields

For each finalized run, capture:

- `finalization.assessment`
  - `accepted | retryable_degraded | unrecoverable`
- `finalization.request_kind`
  - `conversation | tool_followup | finalization_retry | contract_repair`
- `finalization.required_evidence_count`
- `finalization.missing_evidence_items`
  - ordered short summaries
- `finalization.retry_triggered`
- `finalization.recovered_from_fragments`
- `finalization.invalid_final_text`
  - bounded/truncated for diagnostics only

### 5.2 Why this is required

These fields make it possible to distinguish:

1. the model produced a thin answer
2. the validator accepted when it should have retried
3. the retry path was never entered
4. the retry path entered and still failed
5. live service code drifted from local source

## 6. File-Level Design Boundaries

This slice should stay local to these files.

### `src/marten_runtime/runtime/tool_followup_support.py`

Owns:

- ledger assembly helpers
- deterministic evidence item generation from tool history

Must avoid:

- host-side user-intent routing
- channel-specific wording branches

### `src/marten_runtime/runtime/llm_client.py`

Owns:

- new request/response data models for evidence ledger

Must avoid:

- provider-specific finalization logic

### `src/marten_runtime/runtime/llm_message_support.py`

Owns:

- serializing evidence ledger into a model-visible system block

Must avoid:

- semantic routing decisions

### `src/marten_runtime/runtime/llm_request_instructions.py`

Owns:

- generic wording for evidence-ledger followup contract
- generic wording for no-new-tools finalization retry contract

Must avoid:

- request regex routing for free-form natural language
- tool-family forcing based on ordinary user text

### `src/marten_runtime/runtime/recovery_flow.py`

Owns:

- ledger-driven coverage validation
- degraded fallback eligibility

Must avoid:

- becoming a tool-name-specific answer generator library

### `src/marten_runtime/runtime/loop.py`

Owns:

- wiring ledger generation into followup and finalization-retry requests
- recording finalization diagnostics

Must avoid:

- host-side user-language routing tables

## 7. Boundary Rules

This design adds three durable rules.

### Rule 1 — transcript remains canonical

The evidence ledger is additive.

The model must still see the canonical assistant tool-call + tool-result transcript.

### Rule 2 — ledger stays execution-derived

The runtime may summarize executed evidence.

The runtime may not invent unexecuted facts or infer new task branches from free-form user language.

The ledger may carry narrow required-coverage flags, but those flags stay inside the existing finalization-contract boundary.

They must not become a new host-side natural-language routing surface for deciding which tool family the user intended.

### Rule 3 — validator stays bounded

The validator may enforce coverage and truthfulness.

The validator may not grow into a second answer engine for ordinary success-path finalization.

## 8. Expected Implementation Tasks

This section sets the intended implementation shape.

### Chunk A — introduce evidence-ledger models and builders

Files:

- modify `src/marten_runtime/runtime/llm_client.py`
- modify `src/marten_runtime/runtime/tool_followup_support.py`
- test `tests/runtime_loop/test_tool_followup_support.py`

Target:

- new data models
- deterministic assembly from `tool_history`
- loop-meta evidence support

### Chunk B — inject ledger into prompt assembly

Files:

- modify `src/marten_runtime/runtime/llm_message_support.py`
- modify `src/marten_runtime/runtime/llm_request_instructions.py`
- test `tests/runtime_loop/test_llm_message_support.py`

Target:

- model sees ledger for followup and finalization retry
- prompt language stays generic and LLM-first

### Chunk C — unify validator with ledger

Files:

- modify `src/marten_runtime/runtime/recovery_flow.py`
- test `tests/runtime_loop/test_recovery_flow.py`

Target:

- required coverage derives from the same evidence source injected into prompt
- degraded fallback uses ordered required evidence items

### Chunk D — add loop diagnostics and end-to-end regression coverage

Files:

- modify `src/marten_runtime/runtime/loop.py`
- modify relevant diagnostics surfaces and tests
- test `tests/test_acceptance.py`
- test `tests/test_gateway.py`
- test prompt-size / request-shape regression coverage in the runtime-loop test suite

Target:

- finalization retry / recovery is observable
- live-thin-summary regression becomes reproducible and guarded
- zero-tool, partial-success, and contract-repair edges stay stable

## 9. Test Plan

## 9.1 Unit tests

### Ledger assembly

Cases:

1. one successful builtin tool -> one evidence item
2. multi-tool ordered history -> evidence items preserve execution order
3. loop meta requested -> adds one loop-meta item
4. failed tool result -> excluded from required evidence list when appropriate
5. `recovery_fragment` present -> reused as primary evidence summary

### Prompt assembly

Cases:

1. normal conversation request -> no ledger block
2. tool followup request -> ledger block included
3. finalization retry request -> ledger block included, tools removed
4. ledger wording stays generic and contains no host-side intent routing text
5. `contract_repair` request -> ledger behavior stays inside existing finalization-contract state and introduces no new tool-family routing text
6. prompt-size regression checks:
   - single-tool followup
   - three-tool followup
   - finalization retry
   Each case should assert that ledger injection stays bounded and does not duplicate transcript payload unnecessarily.

### Recovery validator

Cases:

1. final text covers all required evidence -> `accepted`
2. final text omits one required evidence item -> `retryable_degraded`
3. final text includes round-trip statement when required -> accepted
4. final text omits round-trip statement when required -> degraded
5. fallback recovery text renders all required evidence in order
6. partial-success chain -> successful tools remain coverable while failed tools do not become required success evidence
7. `contract_repair` followup still evaluates against the same bounded evidence source instead of a second host-side classification path

## 9.2 Integration tests

### Multi-tool finalization

Replay a run shaped like:

- `time`
- `runtime.context_status`
- `mcp.list`

Assertions:

- followup request contains canonical transcript
- followup request contains current-turn evidence ledger
- thin final answer triggers retry
- retry request contains same evidence ledger
- degraded fallback covers all required results

### Mixed tool families

Cases:

1. builtin + MCP
2. session + runtime
3. spawn_subagent + builtin followup
4. skill + builtin

Assertions:

- no tool-family-specific hardcoding is required for coverage enforcement

### Partial success / tool failure

Replay a run shaped like:

- first tool succeeds
- second tool succeeds
- third tool fails or returns an error result

Assertions:

- ledger retains successful current-turn evidence in order
- failed tool output does not become required success coverage by default
- finalization retry / fallback still answers from successful evidence without inventing success for the failed step

### Contract repair continuity

Replay a run where:

- a post-tool final answer is rejected by the finalization contract
- the loop enters `contract_repair`

Assertions:

- contract repair stays on the existing current-turn evidence boundary
- no new host-side tool-family routing is introduced
- repaired request still uses the same execution-derived evidence source

### Zero-tool plain conversation

Replay a run with:

- no tool calls
- one plain conversational final answer

Assertions:

- evidence-ledger logic does not interfere with plain zero-tool conversation finalization
- no retry or degraded recovery is triggered solely because the ledger feature exists

## 9.3 Acceptance tests

### Regression: thin summary omission

User message shape:

- explicit ordered tool chain
- explicit instruction to summarize each result
- explicit instruction to state whether multiple model/tool round trips occurred

Assertions:

- final answer includes every successful tool’s key result
- final answer includes whether multiple round trips occurred
- raw thin sentence alone is rejected or retried

### Regression: single-tool deterministic direct render

Cases:

- `session.list`
- `time`
- `runtime.context_status`

Assertions:

- `finalize_response=true` single-tool path still works
- evidence ledger does not interfere with one-hop direct render

### Regression: ordinary multi-step request

Case:

- first tool call should not finalize when more work remains

Assertion:

- ledger strengthens final answer completeness without changing first-turn tool routing behavior

### Regression: partial-success finalization

Case:

- user asks for a chained result summary
- some early tool calls succeed
- a later tool call fails

Assertions:

- final answer keeps successful current-turn facts accurate
- the runtime does not silently convert the failed step into a fabricated success summary
- fallback stays truthful to the executed chain

### Regression: zero-tool plain chat

Case:

- ordinary user conversation with no tools

Assertions:

- finalization behavior matches the pre-ledger plain-chat path
- the runtime does not inject ledger-specific retry pressure into zero-tool turns

### Regression: prompt-size stability

Cases:

- single-tool followup
- three-tool followup
- finalization retry

Assertions:

- ledger text remains bounded
- transcript and ledger do not duplicate the same payload in an unbounded way
- token growth stays controlled enough that the feature does not destabilize the normal followup path

## 9.4 Diagnostics tests

Assertions:

- accepted runs record finalization assessment
- degraded runs record missing evidence item summaries
- retry path records `retry_triggered=true`
- recovered runs record `recovered_from_fragments=true`

## 10. Risks And Mitigations

### Risk 1 — ledger becomes a second transcript

Mitigation:

- keep ledger compact
- keep transcript canonical
- ledger only summarizes required current-turn evidence

### Risk 2 — ledger builder starts doing host-side semantic routing

Mitigation:

- derive only from executed tool history and existing runtime contract flags
- prohibit free-form family routing logic in ledger assembly

### Risk 3 — coverage enforcement becomes tool-specific again

Mitigation:

- use generic evidence items
- generate summaries from fragment/direct-render seams already owned by tools
- avoid per-user-phrase tool branches

### Risk 4 — retry path and fallback path diverge

Mitigation:

- use the same evidence ledger source for prompt, validator, and fallback rendering

### Risk 5 — live service drift remains opaque

Mitigation:

- add explicit finalization diagnostics fields
- validate one real multi-tool regression chain after implementation

## 11. Success Criteria

The implementation should be considered correct when all of the following are true:

1. a multi-tool request that explicitly asks to summarize current-turn results yields a final answer that covers those results
2. a thin answer that omits required current-turn evidence triggers retry or bounded recovery
3. single-tool `finalize_response=true` direct-render paths still complete in one hop
4. no new host-side natural-language routing helper is introduced
5. diagnostics make finalization acceptance and retry decisions inspectable from one run record

## 12. Open Questions For Implementation Review

These are implementation-stage checks, not design blockers.

1. whether the ledger should be attached as one new `LLMRequest` field or rendered on demand from `tool_history`
2. whether loop-meta evidence should always be assembled or only when explicitly requested
3. how much of the missing-evidence list should be persisted in diagnostics before truncation

The preferred implementation direction is:

- explicit `LLMRequest` ledger field
- loop-meta assembled only when relevant
- bounded diagnostics strings with deterministic truncation
