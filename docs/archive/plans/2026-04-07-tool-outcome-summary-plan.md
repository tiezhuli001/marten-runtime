# Tool Outcome Summary Implementation Plan

> **Status:** historical rules-first baseline. The current source of truth for this slice is `docs/2026-04-07-llm-tool-episode-summary-design.md` + `docs/2026-04-07-llm-tool-episode-summary-plan.md`.


> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin cross-turn `tool outcome summary` / `durable facts` layer so multi-turn tool and MCP workflows can preserve critical tool results without replaying raw tool transcripts into later LLM requests.

**Architecture:** Keep the current runtime thin: same-turn tool follow-up remains unchanged and still uses full `assistant.tool_calls + tool` messages; the persisted chat-history replay layer continues to store only `user/assistant` in session history, **but the effective cross-turn context must now be `user/assistant replay + tool outcome summary reinjection` rather than `user/assistant replay` alone**. Add one small session sidecar for recent tool-outcome summaries, extract concise durable facts after successful tool execution, and selectively reinject a budgeted summary block into the next request near the existing `working_context` boundary.

**Tech Stack:** Python, unittest, existing `marten-runtime` runtime/session/bootstrap path, Pydantic session models, current context assembly and compaction pipeline, existing `/messages` + diagnostics live probes

---

## Scope Guardrails

Before touching code, treat these as hard constraints:

- Do **not** introduce:
  - raw tool transcript replay across turns
  - vector retrieval / embeddings
  - cross-session memory
  - planner / orchestrator layers
  - host-side semantic search over prior tool results
  - background summarization workers
- Keep the current runtime correctness boundary intact:
  - same-turn tool follow-up must still use full tool results
  - the persisted chat-history replay layer must still only replay `user/assistant`
  - the next-turn effective context must include the new summary sidecar when relevant and within budget
  - `runtime.context_status` contract must remain thin and query-only
  - compaction boundaries must remain unchanged
- The new layer must be a **small continuity sidecar**, not a general memory platform.
- The new layer must be **budgeted and truncatable**.
- The new layer must be **summary-first**:
  - preserve key facts
  - suppress protocol noise
  - never store full MCP/tool payloads as durable cross-turn memory

---

## Non-Goals

The following are explicitly out of scope for this plan:

- auto-generating long-form summaries for every turn
- LLM-generated long-term memory extraction
- durable storage beyond current session state
- semantic retrieval over historical tool outputs
- summarizing arbitrary assistant text into memory facts
- compacting skill bodies or tool schemas into this feature

---

## Problem Statement For Implementers

The current runtime makes an intentional trade-off:

- **same turn:** tool outputs are preserved and reinjected into the tool follow-up request
- **next turn, before this feature:** only `user/assistant` text is replayed

This keeps the main agent from being flooded by tool/MCP transcript noise, but it also means a later turn can lose critical structured facts when the prior assistant message did not fully restate them.

This plan adds the smallest useful correction:

- after a successful tool call, extract a **very small** `tool outcome summary`
- persist only the most recent summaries in session state
- inject a concise rendered block into future turns when budget allows

After this slice, the intended cross-turn model-visible continuity shape is:

- persisted replay history: `user/assistant` only
- sidecar continuity memory: recent `tool outcome summaries`
- effective next-turn request context: `user/assistant replay + tool outcome summary block + existing working_context/compact summary scaffolding`

This distinction is critical:

- **session history semantics stay thin**
- **cross-turn tool continuity becomes stronger**

This should improve multi-turn tool continuity without drifting into a memory subsystem.

Implementation shorthand for coding agents:

- **Do not read this plan as “cross-turn context remains user/assistant only.”**
- Read it as:
  - `history replay` remains `user/assistant` only
  - **cross-turn effective context no longer remains `user/assistant` only**
  - the new summary sidecar is specifically being added to solve the multi-turn tool continuity gap

---

## File Responsibility Map

### New files

- `src/marten_runtime/session/tool_outcome_summary.py`
  - Pydantic models for the new continuity sidecar
  - summary truncation helpers
  - token-estimate helper for rendered summary text
- `src/marten_runtime/runtime/tool_outcome_extractor.py`
  - rules-based extraction of concise tool outcome summaries from builtin / MCP / generic tool results
- `tests/test_tool_outcome_extractor.py`
  - focused extractor behavior tests
- `tests/test_tool_outcome_summary.py`
  - summary model, truncation, de-duplication, and rendering budget tests

### Modified files

- `src/marten_runtime/session/models.py`
  - add recent tool-outcome-summary state to `SessionRecord`
- `src/marten_runtime/session/store.py`
  - persist / update / trim / dedupe recent tool outcome summaries
- `src/marten_runtime/runtime/context.py`
  - accept recent tool outcome summaries, render a compact reinjection block, and place it near `working_context`
- `src/marten_runtime/runtime/llm_client.py`
  - extend `LLMRequest` with `tool_outcome_summary_text`
  - include the summary block in outbound message assembly
- `src/marten_runtime/runtime/loop.py`
  - extract summaries after successful tool execution
  - carry them through the turn for persistence
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - persist summaries at turn finalization and pass them into next-turn context assembly
- `src/marten_runtime/tools/registry.py`
  - use tool metadata where needed for source-kind classification only if current call sites cannot supply enough context directly
- `tests/test_runtime_context.py`
  - verify reinjection placement, budgeting, and interaction with working-context + compaction
- `tests/test_runtime_loop.py`
  - verify summaries are produced and persisted after successful tool calls
- `tests/test_models.py`
  - verify outbound message assembly includes summary text without disturbing same-turn tool follow-up semantics
- `tests/test_session.py`
  - verify session persistence, trimming, and dedupe
- `tests/test_acceptance.py`
  - verify end-to-end continuity behavior via HTTP path
- `docs/README.md`
  - mention the new thin continuity layer if the docs index tracks current architecture slices
- `STATUS.md`
  - sync completed work and verification results

---

## Data Model Contract

### Summary object shape

Create a small internal model that can be safely persisted and safely rendered.

Minimum required fields:

- `summary_id`
- `run_id`
- `tool_name`
- `source_kind` (`builtin` | `mcp` | `skill` | `automation` | `other`)
- `created_at`
- `user_visible_summary`
- `facts`
- `token_estimate`

Suggested supporting fields:

- `server_id` optional
- `relevance_hint` optional
- `truncated` boolean

### Facts contract

Facts should be intentionally narrow:

- each fact is one `key/value` pair
- values should be short strings
- total facts per summary should be capped
- facts should prefer IDs, names, statuses, timestamps, and small numeric results

Do **not** persist:

- full tool payloads
- full tool results
- large arrays
- large markdown/html blocks
- raw `result_text` when it is long

---

## Reinjection Contract

The rendered text block must be concise and separable from other runtime scaffolding.

Recommended rendered shape:

```text
Recent tool outcome summaries:
- runtime.context_status: 当前估算 2694/245760 tokens，本轮峰值约 14034，峰值主要来自工具结果注入后。
- mcp.github_search: 找到 repo=openai/codex，branch=main，issue_count=12。
```

Rules:

- one heading only when there is at least one kept summary
- one short line per summary
- no raw JSON dumps
- no code fences
- no more than the configured summary budget

Placement rule:

- inject the rendered block **alongside** current context assembly
- it must not replace:
  - `system_prompt`
  - `compact_summary_text`
  - `working_context_text`
  - skill bodies
  - capability catalog
  - tool schema exposure

Recommended placement order in outbound system scaffolding:

1. `system_prompt`
2. skill heads / capability catalog (existing rules unchanged)
3. always-on skill text
4. compact summary text
5. **tool outcome summary text**
6. working context text
7. follow-up instruction / activated skill bodies / replay / current user message

This keeps it in the continuity layer rather than the immutable base prompt.

---

## Summary Selection Rules

### Keep very little

Initial implementation limits:

- at most **3 summaries** in session state for reinjection purposes
- at most **3 facts** per summary
- rendered reinjection target budget: **~120-240 tokens** total

### Prefer recent and high-value summaries

Ranking order for v1:

1. more recent summaries first
2. summaries from the immediately previous tool-bearing turn first
3. summaries with structured facts over summaries with only generic text
4. shorter summaries preferred when close to budget

### De-duplication

If two consecutive summaries are effectively the same tool outcome:

- keep the newest one
- drop the older one

A pragmatic v1 dedupe key is acceptable, for example:

- `(tool_name, source_kind, normalized fact keys, normalized summary text)`

### Expiry / trimming

Trim on write so session state stays bounded.

Recommended v1 policy:

- keep only the most recent 5 stored summaries total
- render at most the most recent 3 summaries

---

## Extraction Rules

Use **rules-based extraction first**. Do not depend on an extra LLM call.

### Builtin tool extraction

Implement explicit extractors for high-value builtins.

#### `runtime` / `context_status`

Extract only the fields most useful for follow-up continuity:

- `estimated_usage`
- `effective_window`
- `peak_stage`
- `peak_input_tokens_estimate`
- maybe `estimate_source` if short

The rendered summary should remain short and user-readable.

#### `automation`

If applicable, extract small operational facts such as:

- `action`
- `automation_id`
- `status`
- `next_run`
- `count`

#### `skill`

Only summarize result facts like:

- `action=load`
- `skill_id`
- `loaded=true`

Do **not** store the skill body in durable facts.

### MCP extraction

This is the most important path.

Rules for v1:

- prefer top-level short fields from the result
- optionally inspect a small allowlist of keys inside nested dicts
- prefer identifiers and status over descriptive prose
- never store large `result_text` verbatim
- if the result is too large or too unstructured, fall back to a generic one-line summary

Suggested high-value keys:

- `id`
- `name`
- `title`
- `status`
- `type`
- `repo`
- `branch`
- `count`
- `url`
- `timestamp`
- `created_at`
- `updated_at`

### Generic fallback extractor

If there is no specialized extractor:

- create a short one-line summary using tool name + a tiny fact selection
- if no trustworthy facts are extractable, return `None` rather than storing noise

---

## Failure / Safety Rules

- If extraction fails, do **not** fail the turn. Skip summary generation.
- If extraction produces only noisy content, drop it.
- If the rendered summary block would exceed the allowed budget, trim or omit lower-priority summaries.
- Never let this feature change the same-turn tool follow-up request semantics.
- Never let this feature alter `SessionMessage` replay semantics.

---

## Chunk 1: Freeze The Boundary With Failing Tests

### Task 1: Lock the intended architecture boundary before implementation

**Files:**
- Modify: `tests/test_runtime_context.py`
- Modify: `tests/test_runtime_loop.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_session.py`

- [ ] **Step 1: Add failing tests proving cross-turn replay still excludes raw tool transcript**

Suggested tests:
- `test_replay_session_messages_still_only_replays_user_and_assistant_after_summary_feature`
- `test_runtime_context_injects_tool_outcome_summary_text_without_replaying_tool_transcript`

- [ ] **Step 2: Add failing tests proving same-turn tool follow-up is unchanged**

Suggested tests:
- `test_openai_client_tool_followup_keeps_tool_history_messages_and_adds_summary_only_as_system_context`
- `test_runtime_tool_summary_feature_does_not_replace_same_turn_tool_result_followup`

- [ ] **Step 3: Add failing tests proving session state uses a sidecar instead of mutating message history semantics**

Suggested tests:
- `test_session_store_persists_recent_tool_outcome_summaries_separately_from_history`

- [ ] **Step 4: Run focused tests to confirm they fail for the intended reasons**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_context tests.test_runtime_loop tests.test_models tests.test_session -v`
Expected: FAIL on missing summary sidecar fields / missing reinjection behavior

- [ ] **Step 5: Re-check design drift**

Confirm none of the failing tests require:
- raw transcript replay
- planner logic
- retrieval infra
- new builtin families

---

## Chunk 2: Add The Sidecar Data Model And Persistence

### Task 2: Create a bounded session-side summary model

**Files:**
- Create: `src/marten_runtime/session/tool_outcome_summary.py`
- Modify: `src/marten_runtime/session/models.py`
- Modify: `src/marten_runtime/session/store.py`
- Test: `tests/test_tool_outcome_summary.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write failing model tests**

Cover:
- summary creation with required fields
- fact count trimming
- summary text truncation
- token estimate population
- dedupe key stability

Suggested tests:
- `test_tool_outcome_summary_trims_fact_count_and_summary_length`
- `test_tool_outcome_summary_computes_stable_token_estimate`
- `test_tool_outcome_summary_builds_stable_dedupe_key`

- [ ] **Step 2: Implement `ToolOutcomeFact` and `ToolOutcomeSummary` models**

Requirements:
- all fields serializable in current session store
- helper constructors for concise summary creation
- helper for trimming overlong fact values
- helper for estimating rendered token size using the existing estimator where practical

- [ ] **Step 3: Extend `SessionRecord` with recent summary sidecar storage**

Requirements:
- add a dedicated field such as `recent_tool_outcome_summaries`
- keep `history` shape unchanged

- [ ] **Step 4: Add store helpers**

Minimum methods:
- `append_tool_outcome_summary(session_id, summary)`
- `list_recent_tool_outcome_summaries(session_id, limit=...)`

Behavior:
- dedupe on write
- trim on write
- preserve most recent ordering

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_tool_outcome_summary tests.test_session -v`
Expected: PASS

---

## Chunk 3: Implement Rules-Based Extraction

### Task 3: Extract concise durable facts from tool results

**Files:**
- Create: `src/marten_runtime/runtime/tool_outcome_extractor.py`
- Modify: `src/marten_runtime/tools/registry.py` (only if tool metadata access is necessary)
- Test: `tests/test_tool_outcome_extractor.py`
- Test: `tests/test_runtime_loop.py`

- [ ] **Step 1: Write failing extractor tests for builtin, MCP, and generic paths**

Suggested tests:
- `test_extract_runtime_context_status_summary_keeps_only_key_usage_fields`
- `test_extract_mcp_summary_prefers_small_high_value_fields_and_drops_large_result_text`
- `test_extract_generic_tool_summary_returns_none_when_noisy_or_unstructured`
- `test_extract_skill_summary_does_not_persist_skill_body`

- [ ] **Step 2: Implement explicit builtin extractors**

Support at least:
- `runtime`
- `automation` when there is an obvious stable result shape
- `skill` for lightweight load metadata only

- [ ] **Step 3: Implement MCP extractor**

Requirements:
- accept `tool_name`, `tool_payload`, `tool_result`, and optional tool metadata
- inspect top-level dict first
- allow a tiny nested-field scan only when bounded
- never dump long strings verbatim
- cap fact count and value size

- [ ] **Step 4: Implement generic fallback extractor**

Requirements:
- return a compact single-line summary or `None`
- prefer silence over noisy memory

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_tool_outcome_extractor tests.test_runtime_loop -v`
Expected: PASS

---

## Chunk 4: Wire Extraction Into The Runtime Loop Without Changing Same-Turn Semantics

### Task 4: Generate summaries after successful tool execution

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Add failing tests for runtime-loop summary generation**

Suggested tests:
- `test_runtime_generates_tool_outcome_summary_after_successful_tool_call`
- `test_runtime_does_not_generate_tool_outcome_summary_for_failed_tool_call`
- `test_runtime_keeps_same_turn_tool_followup_payload_intact_after_summary_generation`

- [ ] **Step 2: Extend `LLMRequest` with `tool_outcome_summary_text`**

Requirements:
- field is optional
- same-turn request building remains backward compatible

- [ ] **Step 3: In `RuntimeLoop.run()`, call the extractor after successful tool execution**

Requirements:
- do this after the tool result exists
- do not let extractor failure break the run
- collect produced summaries for session persistence

- [ ] **Step 4: Ensure same-turn follow-up still uses full `tool_history` / `tool_result`**

This is a hard invariant:
- the summary feature may add cross-turn context
- it must not replace same-turn tool follow-up messages

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_models -v`
Expected: PASS

---

## Chunk 5: Reinject Summary Text Into Future Turns

### Task 5: Assemble and budget the reinjection block

**Files:**
- Modify: `src/marten_runtime/runtime/context.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Test: `tests/test_runtime_context.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Add failing tests for reinjection placement and budgeting**

Suggested tests:
- `test_assembler_renders_recent_tool_outcome_summaries_into_dedicated_context_block`
- `test_assembler_trims_tool_outcome_summary_block_to_budget`
- `test_openai_client_includes_tool_outcome_summary_text_between_compact_summary_and_working_context`
- `test_compacted_context_and_tool_outcome_summary_can_coexist_without_overwrite`

- [ ] **Step 2: Extend `RuntimeContext` with `tool_outcome_summary_text`**

Requirements:
- optional field
- no impact when absent

- [ ] **Step 3: Build a renderer that converts recent summaries into one compact block**

Rules:
- include heading only when non-empty
- render recent summaries newest-first or oldest-first consistently; pick one and lock with tests
- enforce the configured budget
- degrade gracefully by dropping lower-priority summaries first

- [ ] **Step 4: Inject the new block into outbound messages**

Recommended placement:
- after `compact_summary_text`
- before `working_context_text`

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_context tests.test_models -v`
Expected: PASS

---

## Chunk 6: Persist At Turn Finalization And Feed The Next Turn

### Task 6: Complete HTTP/session wiring

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/session/store.py`
- Test: `tests/test_acceptance.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Add failing end-to-end tests for session persistence across turns**

Suggested tests:
- `test_http_messages_persists_tool_outcome_summary_after_tool_turn`
- `test_followup_turn_reinjects_recent_tool_outcome_summary_without_replaying_raw_tool_messages`

- [ ] **Step 2: Persist collected summaries when the turn finalizes**

Requirements:
- append to session sidecar after successful runs
- avoid persisting on failed tool paths unless there is a deliberate safe summary worth keeping (v1: skip failures)

- [ ] **Step 3: Feed recent summaries into `assemble_runtime_context()` on the next turn**

Requirements:
- use session-side recent summaries only
- do not mutate replay history

- [ ] **Step 4: Run focused end-to-end tests**

Run: `PYTHONPATH=src python -m unittest tests.test_session tests.test_acceptance -v`
Expected: PASS

---

## Chunk 7: Add Live Verification For Multi-Turn Tool Continuity

### Task 7: Prove the feature helps real multi-turn behavior without exploding context

**Files:**
- Modify: `STATUS.md`
- Modify: `docs/README.md` if architecture index changed materially

- [ ] **Step 1: Add or update live-probe helpers if needed**

Keep helpers minimal and local to tests / scripts already used in the repo.

- [ ] **Step 2: Run a plain control probe**

Target:
- plain turn
- follow-up turn

Expect:
- no tool outcome summary injected
- no behavior regression

- [ ] **Step 3: Run a builtin continuity probe**

Target:
- first turn calls `runtime.context_status`
- second turn asks a follow-up like “刚才峰值为什么高”

Expect:
- next-turn request contains a compact runtime summary block
- final answer can reference prior tool facts without re-fetching unnecessarily

- [ ] **Step 4: Run an MCP-heavy continuity probe**

Target:
- first turn calls a mocked heavy MCP result
- second turn asks to continue from the prior MCP result

Expect:
- no raw MCP transcript replay in session history
- next-turn request includes only the small summary block
- cross-turn answer stability improves
- `initial` rises modestly, not explosively

- [ ] **Step 5: Re-run context-pressure probes**

Confirm the new summary layer does not destroy current pressure behavior:
- plain
- builtin
- MCP-heavy
- skill-heavy

Capture at least:
- `initial_preflight_input_tokens_estimate`
- `peak_preflight_input_tokens_estimate`
- `peak_preflight_stage`
- `actual_input_tokens`
- `actual_total_tokens`

- [ ] **Step 6: Sync docs and status**

Update:
- `STATUS.md`
- `docs/README.md` if needed

Include:
- what was implemented
- what is intentionally not implemented
- verification commands and live probe results

---

## Test Matrix

The implementation is not complete unless these behavior classes are covered.

### Unit

- summary model validation
- fact trimming and token budgeting
- extractor behavior for builtin / MCP / generic
- dedupe and trimming behavior

### Runtime integration

- successful tool call generates summary
- failed tool call does not poison session summary state
- same-turn tool-followup remains unchanged
- reinjection text is included only on later turns

### Context assembly

- summary block placement is stable
- summary block coexists with compact summary and working context
- summary block is omitted when empty
- summary block is trimmed when over budget

### HTTP / end-to-end

- a tool-bearing turn persists a summary
- the next turn receives the summary block
- session history still contains only `user/assistant`

### Live verification

- plain control
- builtin continuity
- MCP-heavy continuity
- context-pressure regression comparison

---

## Implementation Notes For Coding Agents

- Prefer **small focused commits per chunk**.
- Do **not** start by editing `RuntimeLoop` first; lock the boundary with tests and the sidecar model before wiring.
- Reuse current rendering and context-assembly patterns instead of introducing a new prompt subsystem.
- Keep rendering logic deterministic and testable.
- Do not use an extra provider call to summarize tool results in v1.
- Do not attempt clever semantic ranking in v1; recency + bounded facts is enough.
- If a result shape is too noisy, skip it rather than storing junk.
- If you discover a tempting memory/retrieval extension, record it in docs but keep it out of this slice.

---

## Verification Commands

Run these at the indicated checkpoints.

### After Chunk 1

`PYTHONPATH=src python -m unittest tests.test_runtime_context tests.test_runtime_loop tests.test_models tests.test_session -v`

### After Chunk 2

`PYTHONPATH=src python -m unittest tests.test_tool_outcome_summary tests.test_session -v`

### After Chunk 3

`PYTHONPATH=src python -m unittest tests.test_tool_outcome_extractor tests.test_runtime_loop -v`

### After Chunk 4

`PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_models -v`

### After Chunk 5

`PYTHONPATH=src python -m unittest tests.test_runtime_context tests.test_models -v`

### After Chunk 6

`PYTHONPATH=src python -m unittest tests.test_session tests.test_acceptance -v`

### Final targeted regression

`PYTHONPATH=src python -m unittest tests.test_tool_outcome_summary tests.test_tool_outcome_extractor tests.test_runtime_context tests.test_runtime_loop tests.test_models tests.test_session tests.test_acceptance -v`

### Final broader regression

`PYTHONPATH=src python -m unittest tests.test_usage_estimator tests.test_runtime_usage tests.test_runtime_capabilities tests.test_runtime_context tests.test_runtime_loop tests.test_models tests.test_tools tests.test_session tests.test_acceptance -v`

---

## Done Criteria

This plan is complete only when all of the following are true:

- recent tool outcome summaries are persisted separately from session history
- same-turn tool follow-up remains unchanged and tested
- cross-turn raw transcript replay is still absent and tested
- the next turn can receive a small rendered summary block
- MCP-heavy follow-up continuity improves without large context explosion
- summary storage and reinjection are bounded, deduped, and truncatable
- focused and broader regression suites pass
- live probes capture before/after continuity behavior
- `STATUS.md` is updated with exact verification evidence

---

## Explicit Anti-Drift Checklist

If an implementation does any of the following, it is wrong and must be corrected:

- stores full tool result payloads as durable cross-turn memory
- replays `role=tool` or `assistant.tool_calls` in later turns
- leaves next-turn effective context as only `user/assistant` replay without adding the approved summary sidecar
- replaces same-turn tool follow-up with summary text
- injects tool summaries into the immutable base system prompt instead of the continuity layer
- adds semantic retrieval / planner logic in the name of relevance
- stores skill bodies as durable facts
- allows summary injection to grow without a hard budget
