# Context Usage Accuracy Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current rough `runtime.context_status` estimate with a more credible usage model that prefers provider-reported usage, falls back to tokenizer-based outbound-payload estimation, and only uses rough estimation as a last resort.

**Architecture:** Keep the existing thin builtin/runtime boundary and current compaction architecture intact. Improve usage fidelity by normalizing provider usage in the LLM client, adding preflight token estimation against the actual outbound payload, persisting usage metadata in run/session state, and upgrading the `runtime.context_status` builtin to return concise but trustworthy status data.

**Tech Stack:** Python, unittest, existing `marten-runtime` runtime/session/bootstrap path, OpenAI-compatible LLM client abstraction, model-profile metadata

---

## Scope Guardrails

Before touching code, treat these as hard constraints:

- Do **not** introduce:
  - memory platformization
  - vector retrieval / embeddings
  - new planner/orchestrator layers
  - provider-specific parallel subsystems for each model family
  - host-side intent routing for context questions
- Keep the runtime builtin boundary thin:
  - family tool remains `runtime`
  - action remains `context_status`
  - LLM still formulates final natural-language answers
- Keep the current compaction boundary intact:
  - do not compact system prompt / bootstrap prompt / skill scaffolding / capability catalog / tool schemas
- Prefer strong prior-art ideas already validated by OpenCode / Codex / Claude Code:
  - actual usage first
  - estimate actual outbound payload when needed
  - concise user surface, richer diagnostics

---

## File Responsibility Map

### New files

- `src/marten_runtime/runtime/usage_models.py`
  - normalized provider usage and preflight estimate models
- `src/marten_runtime/runtime/token_estimator.py`
  - outbound payload token-estimation abstraction and fallback selection
- `tests/test_usage_estimator.py`
  - estimator behavior and payload-shape coverage
- `tests/test_runtime_usage.py`
  - normalized usage extraction and status-surface coverage

### Modified files

- `src/marten_runtime/runtime/llm_client.py`
  - add provider usage extraction and preflight estimate hooks
- `src/marten_runtime/runtime/history.py`
  - store actual and estimated usage metadata per run
- `src/marten_runtime/runtime/loop.py`
  - pass usage metadata into runtime tool context and persist it
- `src/marten_runtime/session/models.py`
  - add latest actual usage metadata at session scope
- `src/marten_runtime/session/store.py`
  - persist/retrieve latest session usage metadata
- `src/marten_runtime/tools/builtins/runtime_tool.py`
  - return upgraded status payload and confidence-aware summary
- `src/marten_runtime/runtime/tool_calls.py`
  - preserve contract while passing richer host-only tool context
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - wire estimator/runtime dependencies if needed
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - preserve per-session usage state across turns
- `src/marten_runtime/config/models_loader.py`
  - extend model metadata for tokenizer/usage capability hints
- `config/models.toml`
  - add local profile metadata where appropriate
- `tests/test_models.py`
- `tests/test_runtime_loop.py`
- `tests/test_tools.py`
- `tests/test_contract_compatibility.py`
- `tests/test_acceptance.py`
- `docs/README.md`
- `STATUS.md`

---

## Testing Constraints

These constraints define what “done” means for this plan.

### Constraint 1: Primary visible number must stop pretending rough == precise

If the runtime only has rough estimation, builtin output and summary must identify it as rough/degraded confidence.

### Constraint 2: Actual usage wins over local approximation for completed calls

When provider usage exists, run/session diagnostics must preserve it and `runtime.context_status` must surface it as the most trustworthy completed-call metric.

### Constraint 3: Preflight estimate must be computed from final outbound payload shape

Estimate must include at least:

- final `messages`
- tool schema/description
- tool-history follow-up messages
- runtime-injected system scaffolding that actually lands in the payload

### Constraint 4: Existing runtime boundaries must not drift

All of the following must still hold after the change:

- `runtime` remains a family tool with `action=context_status`
- no host-side keyword router is added
- compaction scaffolding boundaries remain unchanged
- same-conversation FIFO behavior remains unchanged

### Constraint 5: Tests must prove provider/estimate fallback order

The implementation is not complete unless tests prove:

- provider actual usage path
- tokenizer estimate fallback path
- rough fallback path
- builtin output differences across these paths

---

## Chunk 1: Freeze Semantics And Prevent Design Drift

### Task 1: Add failing contract tests for upgraded context-status semantics

**Files:**
- Modify: `tests/test_tools.py`
- Modify: `tests/test_contract_compatibility.py`
- Modify: `tests/test_runtime_loop.py`

- [ ] **Step 1: Write failing tests that lock the new semantic contract**

Add tests asserting that `runtime.context_status` can distinguish:

- current preflight estimate
- latest actual usage
- estimate source kind
- effective window vs raw context window

Suggested test names:
- `test_runtime_tool_prefers_actual_usage_and_reports_estimate_source`
- `test_runtime_tool_marks_rough_estimate_as_degraded_confidence`
- `test_http_messages_context_status_contract_includes_effective_window_and_actual_usage_when_available`

- [ ] **Step 2: Run the focused tests to confirm they fail for the intended missing fields**

Run: `PYTHONPATH=src python -m unittest tests.test_tools tests.test_contract_compatibility tests.test_runtime_loop -v`
Expected: FAIL on missing usage fields and summary semantics

- [ ] **Step 3: Re-check against the design boundary**

Verify the failing tests do **not** require:
- new builtin families
- planner behavior
- compaction-boundary changes

---

## Chunk 2: Normalize Provider Usage

### Task 2: Add normalized usage models and provider-usage extraction

**Files:**
- Create: `src/marten_runtime/runtime/usage_models.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Test: `tests/test_runtime_usage.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for normalized usage extraction from OpenAI-compatible responses**

Cover:
- plain text reply with `usage`
- tool-call reply with `usage`
- missing `usage` payload
- optional fields absent without crashing

Suggested test names:
- `test_openai_client_extracts_usage_from_text_reply`
- `test_openai_client_extracts_usage_from_tool_call_reply`
- `test_openai_client_handles_missing_usage_payload`

- [ ] **Step 2: Add minimal normalized usage model**

Required fields:
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `cached_input_tokens` optional
- `reasoning_output_tokens` optional
- `raw_usage_payload` optional

- [ ] **Step 3: Extend `LLMReply` to carry normalized usage without widening the external runtime contract**

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_usage tests.test_models -v`
Expected: PASS

---

## Chunk 3: Preflight Token Estimation Against Final Outbound Payload

### Task 3: Add estimator abstraction and keep rough fallback

**Files:**
- Create: `src/marten_runtime/runtime/token_estimator.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Modify: `src/marten_runtime/config/models_loader.py`
- Test: `tests/test_usage_estimator.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for estimator selection and payload coverage**

Cover:
- OpenAI-compatible payload with tools counts more than messages-only payload
- tool follow-up payload counts more than first-turn payload without tool history
- unknown tokenizer family falls back to rough estimate
- model profile can carry `tokenizer_family` and `supports_provider_usage`

Suggested test names:
- `test_preflight_estimate_counts_tool_schema_and_history`
- `test_preflight_estimate_grows_for_tool_followup_payload`
- `test_estimator_falls_back_to_rough_when_tokenizer_family_unknown`
- `test_rough_estimator_applies_script_aware_payload_formula`
- `test_rough_estimator_uses_stable_payload_serialization`
- `test_rough_estimator_bucket_classification_matches_unicode_ranges`
- `test_models_loader_accepts_usage_accuracy_metadata`

- [ ] **Step 2: Implement a thin estimator abstraction**

Minimum supported families for v1:
- `openai_cl100k`
- `openai_o200k`
- `rough`

Constraint:
- `rough` must use the exact payload-based empirical rule from the design doc instead of `len(text)//4`
- the rough implementation must classify stable-serialized payload characters into:
  - `ascii_text_chars`
  - `cjk_chars`
  - `other_non_ascii_chars`
  - `json_structure_chars`
  - `whitespace_chars`
- the exact bucket rules are:
  - `whitespace_chars`: `space`, `\\t`, `\\r`, `\\n`
  - `json_structure_chars`: one of `{ } [ ] : , "`
  - `ascii_text_chars`: remaining chars with `ord(ch) <= 0x7F`
  - `cjk_chars`: codepoint in `U+3400..U+4DBF`, `U+4E00..U+9FFF`, `U+3040..U+309F`, `U+30A0..U+30FF`, `U+AC00..U+D7AF`
  - `other_non_ascii_chars`: all remaining chars
- the exact v1 fallback formula is:

```text
ceil(
  ascii_text_chars / 4.0
  + cjk_chars / 1.2
  + other_non_ascii_chars / 2.0
  + json_structure_chars / 2.0
  + whitespace_chars / 6.0
)
```

- tests and status surfaces must label `rough` explicitly as fallback-derived
- do **not** attempt universal tokenizer parity for all providers in this chunk

- [ ] **Step 3: Compute preflight estimate from the actual `_build_payload()` result**

Requirement:
- estimation target must be the final payload shape the provider would actually receive

- [ ] **Step 4: Preserve the old rough helper only as a last-resort fallback**

Implementation requirements for this step:
- remove the current `len(text)//4` fallback from the primary estimation path
- replace it with the deterministic script-aware `rough` estimator
- keep fallback source ordering fixed as:
  - provider usage
  - tokenizer family backend
  - `rough`

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_usage_estimator tests.test_models -v`
Expected: PASS

---

## Chunk 4: Persist Usage In Run And Session State

### Task 4: Extend run history and session state for actual + estimated usage

**Files:**
- Modify: `src/marten_runtime/runtime/history.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/session/models.py`
- Modify: `src/marten_runtime/session/store.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write failing tests for run-level usage persistence**

Cover:
- first request preflight estimate stored on run
- provider actual usage stored on run after response
- latest actual usage copied to session state after completed turn

Suggested test names:
- `test_runtime_records_preflight_and_actual_usage_on_run`
- `test_session_store_persists_latest_actual_usage`

- [ ] **Step 2: Extend run diagnostics with explicit usage metadata**

Minimum run-level fields:
- `preflight_input_tokens_estimate`
- `preflight_estimator_kind`
- `actual_input_tokens`
- `actual_output_tokens`
- `actual_total_tokens`

Optional v1 fields:
- `actual_cached_input_tokens`
- `actual_reasoning_output_tokens`
- `preflight_breakdown`

- [ ] **Step 3: Extend session record with latest actual usage snapshot**

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_session -v`
Expected: PASS

---

## Chunk 5: Upgrade `runtime.context_status` Without Widening The Surface

### Task 5: Return concise but trustworthy status fields

**Files:**
- Modify: `src/marten_runtime/tools/builtins/runtime_tool.py`
- Modify: `src/marten_runtime/runtime/tool_calls.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Write failing tests for the new builtin result shape**

Required fields:
- `context_window`
- `effective_window`
- `estimated_current_input`
- `estimated_usage_percent`
- `estimate_source`
- `last_actual_input`
- `last_actual_output`
- `last_actual_total`
- `compaction_status`
- `latest_checkpoint`
- `summary`

Suggested test names:
- `test_runtime_tool_returns_estimate_and_last_actual_usage`
- `test_runtime_tool_summary_reflects_estimate_confidence`

- [ ] **Step 2: Implement concise confidence-aware summary generation**

Summary rules:
- if tokenizer estimate + actual usage available → high-confidence wording
- if only rough estimate available → degraded-confidence wording
- keep summary short and user-readable

- [ ] **Step 3: Ensure host-only metadata continues not to leak into model-visible payloads**

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=src python -m unittest tests.test_tools tests.test_contract_compatibility -v`
Expected: PASS

---

## Chunk 6: Protect Compaction And Runtime Contracts

### Task 6: Make sure improved usage logic does not break compaction or routing boundaries

**Files:**
- Modify: `tests/test_runtime_capabilities.py`
- Modify: `tests/test_runtime_context.py`
- Modify: `tests/test_runtime_loop.py`
- Modify: `tests/test_acceptance.py`

- [ ] **Step 1: Add regression tests proving no scope drift**

Cover:
- runtime natural-language questions still route through `runtime`
- same-conversation serialization still holds
- compaction diagnostics still use model-window-aware thresholds
- compact path still preserves runtime scaffolding

Suggested test names:
- `test_runtime_context_queries_still_use_runtime_family_tool_after_usage_upgrade`
- `test_compaction_path_still_preserves_scaffolding_after_usage_upgrade`

- [ ] **Step 2: Run targeted regression suite**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_capabilities tests.test_runtime_context tests.test_runtime_loop tests.test_acceptance -v`
Expected: PASS

---

## Chunk 7: End-to-End Verification

### Task 7: Local full-suite and live verification

**Files:**
- Modify: `STATUS.md`
- Modify: `docs/README.md`
- Optionally update: `docs/ARCHITECTURE_CHANGELOG.md` only if implementation is completed in a later execution turn

- [ ] **Step 1: Run broad regression suite**

Run: `PYTHONPATH=src python -m unittest -v`
Expected: PASS

- [ ] **Step 2: Run local HTTP smoke for context-status usage semantics**

Suggested smoke goals:
- plain chat turn
- runtime context-status turn
- tool-heavy turn
- follow-up context-status turn

Expected:
- preflight estimate increases on larger/tool-heavy turns
- last actual usage appears when provider/test double returns usage
- rough fallback is only used when richer data is unavailable

- [ ] **Step 3: Run one real provider sequence**

Suggested sequence:
1. ask a tool-light normal question
2. ask `当前上下文窗口多大？`
3. ask a tool-heavy question (GitHub trending / automation list)
4. ask `现在上下文用了多少？`
5. ask `上下文状态怎么样，需不需要压缩？`

Acceptance checks:
- status replies are not topic-polluted
- runtime context queries still call `runtime.context_status`
- tool-heavy turn leads to a noticeably larger preflight estimate than the tool-light baseline
- when provider usage exists, last-actual fields update across turns

- [ ] **Step 4: Sync docs and continuity**

Update:
- `STATUS.md`
- `docs/README.md`
- if implementation is complete in the execution turn, then also `docs/ARCHITECTURE_CHANGELOG.md`

---

## Detailed Test Case Matrix

### Unit cases

1. **Provider usage extraction**
- text reply + usage
- tool-call reply + usage
- no usage payload
- partial usage payload

2. **Estimator selection**
- tokenizer family known
- tokenizer family unknown → rough fallback
- tools included → estimate grows
- tool follow-up included → estimate grows again

3. **Builtin output**
- estimate + actual both present
- estimate only
- rough only
- no checkpoint vs checkpoint available

### Integration cases

4. **Runtime loop persistence**
- run record stores preflight estimate
- run record stores actual usage
- session record stores latest actual usage

5. **Contract compatibility**
- `runtime` family contract unchanged
- model-visible payload not polluted by host-only usage metadata
- existing natural-language runtime queries still route correctly

### Acceptance / end-to-end cases

6. **HTTP chain**
- plain turn
- runtime status turn
- tool-heavy turn
- follow-up runtime status turn

7. **Compaction chain**
- small-window config causes compaction logic to still behave correctly
- improved usage accounting does not break compact-summary reinjection or trigger calculations

---

## Completion Definition

This plan is complete only when all of the following are true:

- `runtime.context_status` no longer relies on rough estimation as its default primary truth when richer data exists
- provider actual usage is normalized and persisted when available
- current-turn preflight input estimate is computed from the real outbound payload shape
- rough estimation remains only as a fallback and is labeled accordingly
- existing runtime/compaction boundaries remain unchanged
- targeted tests, full suite, and end-to-end verification all pass
