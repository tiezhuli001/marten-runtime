# Thin LLM Context Compaction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one thin, model-aware LLM context compaction layer that rewrites only oversized conversation history while preserving runtime scaffolding and long-thread continuity.

**Architecture:** Keep the existing replay + working-context governance as the default path. Add one compact checkpoint path that triggers only under context pressure, generates a Codex-style handoff summary, stores the compact artifact in session state, and assembles the next runtime request as `runtime scaffolding + compact summary + preserved recent tail + current message`.

**Tech Stack:** Python, unittest, existing `marten-runtime` runtime/session/bootstrap path, OpenAI-compatible LLM client abstraction

---

## Scope Guardrails

Before touching code, treat these as hard constraints:

- Do **not** introduce:
  - session-memory files
  - background summarization workers
  - planner/swarm orchestration
  - subagent memory runtime
  - vector memory / retrieval
- Do **not** compact or replace runtime scaffolding:
  - `system_prompt`
  - app/bootstrap prompt assets
  - `AGENTS.md` / `SOUL.md` / `TOOLS.md` assembled startup content
  - visible skill summaries
  - activated skill bodies
  - capability catalog text
  - MCP tool descriptions / tool schema exposure
- The compact path may rewrite only the **conversation history prefix**.
- The compact result must preserve a **recent raw tail**.
- Triggering must be **model-window aware**, with unknown-model fallback defaults.
- First implementation stays thin:
  - require `summary_text`
  - optionally extract `next_step`, `open_todos`, `pending_risks`
  - do not block MVP on a rich structured parser

---

## File Responsibility Map

### New files

- `src/marten_runtime/session/compaction_trigger.py`
  - compute effective context window, pressure ratio, and compact decision
- `src/marten_runtime/session/compaction_prompt.py`
  - build the compact prompt from the approved design baseline
  - wrap/render the compact summary block injected into future turns
- `src/marten_runtime/session/compacted_context.py`
  - Pydantic model for stored compact artifacts
- `src/marten_runtime/session/compaction_runner.py`
  - execute one compact request and parse the returned summary
- `tests/test_compaction_trigger.py`
  - model-window and threshold decision coverage
- `tests/test_compaction_runner.py`
  - prompt + parsing + failure behavior coverage

### Modified files

- `src/marten_runtime/config/models_loader.py`
  - optional model metadata: `context_window_tokens`, `reserve_output_tokens`, `compact_trigger_ratio`
- `src/marten_runtime/runtime/llm_client.py`
  - rough request token estimation helper for prompt/input assembly
- `src/marten_runtime/session/models.py`
  - session-level compact artifact pointers / metadata
- `src/marten_runtime/session/store.py`
  - persist / fetch compact artifact for a session
- `src/marten_runtime/runtime/context.py`
  - assemble post-compact runtime input correctly
- `src/marten_runtime/runtime/loop.py`
  - proactive compact trigger and reactive retry path
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - wire compaction-capable runtime dependencies
- `tests/test_runtime_context.py`
  - post-compact context assembly coverage
- `tests/test_runtime_loop.py`
  - compact trigger / retry / scaffolding preservation coverage
- `tests/test_acceptance.py`
  - end-to-end compact continuation path
- `tests/test_models.py`
  - model config fallback/default coverage if needed
- `docs/README.md`
  - add active plan reference if desired after writing
- `STATUS.md`
  - keep local continuity in sync during execution

---

## Chunk 1: Freeze Contracts And Validate The Design Boundary

### Task 1: Prove the current runtime scaffolding path before compaction changes

**Files:**
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_acceptance.py`
- Test: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Run the current targeted baseline**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_acceptance tests.test_contract_compatibility -v`
Expected: PASS

- [ ] **Step 2: Add failing contract tests that define what compaction must never replace**

Add tests asserting that even on the future compact path, the LLM request still includes:
- selected `system_prompt`
- skill heads text
- activated skill bodies
- capability catalog text
- tool schema / available tools

Suggested test names:
- `test_compact_path_preserves_system_prompt_and_capability_scaffolding`
- `test_compact_path_preserves_skill_heads_and_activated_skill_bodies`
- `test_compact_path_rewrites_history_prefix_but_keeps_available_tools`

- [ ] **Step 3: Run the focused test targets and confirm the new tests fail for the intended missing behavior**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_acceptance -v`
Expected: FAIL on the newly added compact-path assertions

### Task 2: Lock the design boundary in tests before implementation

**Files:**
- Test: `tests/test_runtime_context.py`
- Test: `tests/test_runtime_loop.py`

- [ ] **Step 1: Add a failing test for `summary + preserved recent tail` assembly**

Required assertions:
- compact summary is present
- preserved tail is present
- old noisy prefix is absent
- current user message remains current

Suggested test name:
- `test_assembler_uses_compact_summary_plus_recent_tail`

- [ ] **Step 2: Add a failing test proving compaction rewrites only the history prefix**

Required assertions:
- recent raw tail survives
- runtime scaffolding survives
- old prefix is not replayed verbatim

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_context tests.test_runtime_loop -v`
Expected: FAIL on missing compact-assembly support

---

## Chunk 2: Model-Aware Trigger Plumbing

### Task 3: Add model-window metadata with safe defaults

**Files:**
- Modify: `src/marten_runtime/config/models_loader.py`
- Test: `tests/test_models.py`
- Test: `tests/test_compaction_trigger.py`

- [ ] **Step 1: Write failing tests for optional model metadata and fallback behavior**

Cover:
- explicit `context_window_tokens`
- explicit `reserve_output_tokens`
- explicit `compact_trigger_ratio`
- unknown/missing profile metadata uses fallback defaults

Suggested test names:
- `test_models_loader_accepts_optional_context_window_metadata`
- `test_compaction_trigger_uses_fallback_defaults_when_metadata_missing`

- [ ] **Step 2: Extend `ModelProfile` with optional metadata fields only**

Keep this thin:
- no provider-specific token-accounting engine
- no schema explosion

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_models tests.test_compaction_trigger -v`
Expected: PASS

### Task 4: Add effective-window and trigger decision helpers

**Files:**
- Create: `src/marten_runtime/session/compaction_trigger.py`
- Test: `tests/test_compaction_trigger.py`

- [ ] **Step 1: Write failing tests for trigger zones**

Cover:
- below advisory threshold → no compact
- above proactive threshold with follow-up demand → compact
- above threshold without follow-up demand → no compact or advisory only (choose one stable policy and lock it)
- reactive compact classification for prompt-too-long-like provider errors

Suggested test names:
- `test_decision_returns_none_below_threshold`
- `test_decision_returns_proactive_compact_when_ratio_and_followup_match`
- `test_decision_uses_unknown_model_fallback_window`
- `test_reactive_decision_matches_prompt_too_long_error`

- [ ] **Step 2: Implement only ratio-based helpers and simple continuation heuristics**

Minimal continuation demand signals:
- non-empty `open_todos`
- non-empty `pending_risks`
- active goal differs from a terminal/finished state

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_compaction_trigger -v`
Expected: PASS

---

## Chunk 3: Compact Prompt And Artifact Model

### Task 5: Add the compact artifact model

**Files:**
- Create: `src/marten_runtime/session/compacted_context.py`
- Modify: `src/marten_runtime/session/models.py`
- Modify: `src/marten_runtime/session/store.py`
- Test: `tests/test_compaction_runner.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Add failing tests for storing/retrieving compact artifacts in session state**

Cover:
- setting latest compact artifact
- reading it back by session
- updating `last_compacted_at`
- preserving existing session metadata

Suggested test names:
- `test_session_store_persists_latest_compacted_context`
- `test_session_store_updates_last_compacted_at_without_clobbering_history`

- [ ] **Step 2: Implement the minimal compact artifact shape**

Required now:
- `compact_id`
- `session_id`
- `summary_text`
- `source_message_range`
- `next_step` optional
- `open_todos` optional
- `pending_risks` optional
- `created_at`

Do not over-design a full memory schema in the first pass.

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_session tests.test_compaction_runner -v`
Expected: PASS

### Task 6: Add the approved compact prompt builder and summary wrapper

**Files:**
- Create: `src/marten_runtime/session/compaction_prompt.py`
- Test: `tests/test_compaction_runner.py`

- [ ] **Step 1: Write failing prompt-contract tests**

Required assertions:
- includes the user-provided checkpoint prompt semantics
- explicitly says compacting old conversation history only
- explicitly says not to replace system/skill/MCP/app scaffolding
- output wrapper is concise and reusable in future turns

Suggested test names:
- `test_compaction_prompt_preserves_user_checkpoint_contract`
- `test_compaction_prompt_adds_runtime_boundary_guardrails`
- `test_rendered_compact_summary_block_is_stable_and_concise`

- [ ] **Step 2: Implement the prompt builder and summary renderer**

Keep the renderer stable so future tests can assert on it.

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_compaction_runner -v`
Expected: PASS

### Task 7: Add the compaction runner

**Files:**
- Create: `src/marten_runtime/session/compaction_runner.py`
- Test: `tests/test_compaction_runner.py`

- [ ] **Step 1: Write failing tests using `ScriptedLLMClient`**

Cover:
- successful compact response becomes a stored compact artifact
- parser handles a plain structured text summary without overfitting to rich XML/JSON
- compaction failure surfaces as controlled `None` / no-compact result instead of corrupting session state

Suggested test names:
- `test_compaction_runner_returns_compacted_context_from_summary_text`
- `test_compaction_runner_handles_compaction_failure_without_state_corruption`

- [ ] **Step 2: Implement one thin compaction call path**

Rules:
- text-only summary call
- no tool use
- no second orchestration loop
- no separate process/runtime plane

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_compaction_runner -v`
Expected: PASS

---

## Chunk 4: Post-Compact Runtime Context Assembly

### Task 8: Add token estimation support for LLM request assembly

**Files:**
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Test: `tests/test_compaction_trigger.py`
- Test: `tests/test_runtime_loop.py`

- [ ] **Step 1: Write failing tests for rough request token estimation**

Cover:
- system prompt contributes
- skill/capability text contributes
- conversation messages contribute
- compact summary contributes when present

Suggested test names:
- `test_estimator_counts_scaffolding_and_history_inputs`
- `test_estimator_reflects_compact_summary_in_request_budget`

- [ ] **Step 2: Implement a rough deterministic estimator**

Do not build provider-exact tokenization. A stable rough estimator is enough for this thin slice.

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_compaction_trigger tests.test_runtime_loop -v`
Expected: PASS

### Task 9: Assemble `compact summary + preserved tail + current working context`

**Files:**
- Modify: `src/marten_runtime/runtime/context.py`
- Test: `tests/test_runtime_context.py`

- [ ] **Step 1: Write failing tests for post-compact context assembly**

Cover:
- compact summary is rendered as a dedicated continuation block
- preserved recent tail remains as conversation messages
- older prefix is excluded from replay
- existing `working_context_text` still renders
- current user message is still appended normally by the caller

Suggested test names:
- `test_assembler_injects_compact_summary_without_overwriting_working_context`
- `test_assembler_keeps_recent_tail_after_compaction`
- `test_assembler_does_not_replay_compacted_prefix_verbatim`

- [ ] **Step 2: Implement post-compact assembly without changing the non-compact path**

Keep default behavior unchanged when no compact artifact exists.

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_context -v`
Expected: PASS

---

## Chunk 5: Runtime Loop Integration

### Task 10: Wire proactive compact before the main completion call

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Test: `tests/test_runtime_loop.py`

- [ ] **Step 1: Write failing tests for proactive compaction**

Cover:
- when context pressure crosses threshold, compaction runs before the main completion
- compact artifact is stored
- final LLM request includes compact summary and preserved tail
- runtime scaffolding still appears in the request

Suggested test names:
- `test_runtime_proactively_compacts_when_context_pressure_exceeds_threshold`
- `test_runtime_proactive_compact_keeps_system_skill_and_tool_scaffolding`

- [ ] **Step 2: Implement dependency wiring for compaction helpers**

Keep it thin:
- no separate runtime process
- no new service bus
- use existing llm client/factory path

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop -v`
Expected: PASS

### Task 11: Add one-shot reactive compact and retry

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Test: `tests/test_runtime_loop.py`

- [ ] **Step 1: Write failing tests for provider overflow recovery**

Cover:
- first model call fails with prompt-too-long-like provider error
- runtime compacts once
- runtime retries once
- if retry succeeds, turn succeeds
- if retry fails again, controlled error surfaces cleanly

Suggested test names:
- `test_runtime_reactively_compacts_and_retries_after_prompt_too_long`
- `test_runtime_reactive_compact_retries_only_once`

- [ ] **Step 2: Implement one-shot retry guard**

Do not allow recursive compaction loops.

- [ ] **Step 3: Re-run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop -v`
Expected: PASS

---

## Chunk 6: End-To-End Acceptance And Regression Safety

### Task 12: Acceptance tests for the compact continuation path

**Files:**
- Modify: `tests/test_acceptance.py`
- Modify: `tests/http_app_support.py` if necessary

- [ ] **Step 1: Write failing acceptance tests covering a long-thread compact path**

Required end-to-end scenarios:

#### Scenario A: proactive compact on a long coding thread
- build a temporary repo/app
- create long enough conversation history
- hit proactive compact threshold
- confirm request still targets the selected agent/app/profile
- confirm system/bootstrap prompt is still present
- confirm compact summary is used
- confirm recent tail survives

Suggested test name:
- `test_http_runtime_proactively_compacts_long_thread_without_losing_runtime_scaffolding`

#### Scenario B: reactive compact retry on overflow
- first reply path raises prompt-too-long-like provider failure
- compact + retry recovers
- final response succeeds

Suggested test name:
- `test_http_runtime_reactively_compacts_after_overflow_and_recovers`

- [ ] **Step 2: Run the acceptance suite**

Run: `PYTHONPATH=src python -m unittest tests.test_acceptance -v`
Expected: PASS

### Task 13: Full regression and chain verification

**Files:**
- Test: `tests/`
- Local continuity: `STATUS.md`
- Docs: `docs/README.md`, `docs/ARCHITECTURE_CHANGELOG.md`

- [ ] **Step 1: Run the focused compaction regression pack**

Run: `PYTHONPATH=src python -m unittest tests.test_models tests.test_session tests.test_compaction_trigger tests.test_compaction_runner tests.test_runtime_context tests.test_runtime_loop tests.test_acceptance -v`
Expected: PASS

- [ ] **Step 2: Run the full repository suite**

Run: `PYTHONPATH=src python -m unittest -v`
Expected: PASS

- [ ] **Step 3: Run one explicit chain smoke**

Use a local `TestClient` script that proves all of the following in one flow:
- long conversation triggers compaction
- selected agent/app/profile remain correct
- compact summary replaces old prefix
- recent tail survives
- skill/capability/system/bootstrap scaffolding is still present
- final turn succeeds through HTTP `/messages`

Expected output: one clear `COMPACTION_E2E_OK` marker plus the decisive fields

- [ ] **Step 4: Sync docs and local continuity**

Update as needed:
- `STATUS.md`
- `docs/ARCHITECTURE_CHANGELOG.md` once implementation lands
- `docs/README.md` if the active reading path changes

---

## Definition Of Done

The feature is complete only when all of the following are true:

- model-aware compaction trigger exists and uses effective-window ratio
- unknown model profiles safely fall back to conservative defaults
- the compact prompt follows the approved Codex-style checkpoint contract with runtime-boundary additions only
- compaction rewrites only the conversation history prefix
- runtime scaffolding is preserved on the compact path
- preserved recent tail is present after compaction
- proactive compact works on long sessions
- reactive compact retries once after prompt-too-long-like failure
- focused compaction tests pass
- full repository tests pass
- one explicit end-to-end chain smoke passes
- docs/continuity are synchronized

