# LLM Tool Episode Summary Implementation Plan

> Status: implemented and revalidated on 2026-04-07; keep this as the executed plan baseline and use `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md` for the latest live verification details.

> **For agentic workers:** REQUIRED: use the existing thin runtime boundaries. Do not widen this slice into memory systems, orchestration layers, or tool-specific parser sprawl. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current rules-first cross-turn tool summary extraction path with a thin **LLM tool-episode summary** path that preserves what a tool-bearing turn accomplished while still preventing raw tool transcript replay across later turns.

**Architecture:** Keep same-turn tool behavior unchanged. Keep persisted history replay `user/assistant`-only. Preserve the current session sidecar and reinjection boundary, but switch summary generation to:

1. primary: small post-turn LLM summarizer over the completed tool episode
2. fallback: tiny deterministic degraded summary

**Tech Stack:** Python, unittest, existing `marten-runtime` runtime/session/bootstrap path, current context assembly and compaction pipeline, existing provider client, current `/messages` live probes

---

## Scope Guardrails

Before touching code, treat these as hard constraints:

- Do **not** introduce:
  - raw tool transcript replay across turns
  - vector retrieval / embeddings
  - cross-session memory
  - planner / orchestrator layers
  - mandatory subagent execution for tool use
  - a growing family of MCP-specific semantic extractors
  - background summarization jobs
- Keep intact:
  - same-turn tool follow-up semantics
  - `user/assistant`-only replay persistence
  - current compaction boundaries
  - thin `runtime.context_status` contract
- Keep the new feature:
  - session-local
  - budgeted
  - skippable
  - failure-tolerant
  - out-of-band from the user-visible main turn (summary generation must not become a required success condition for replying to the user)

---

## Non-Goals

Explicitly out of scope:

- summarizing plain non-tool turns
- saving long-term memory beyond the session
- storing full tool payloads for future prompt reuse
- tool-by-tool handcrafted semantic extractors
- converting all tool-heavy workflows to subagents in this slice
- a generic memory taxonomy system

---

## Desired End State

After this plan is complete:

- same-turn tool follow-up remains unchanged
- next-turn continuity uses a bounded LLM-generated summary of the previous tool episode
- high-volatility tool results such as `time` are not incorrectly reused
- builtin / MCP / skill multi-turn continuity works without replaying raw tool protocol noise
- the earlier rules-first extractor logic is either removed or reduced to a tiny fallback helper

---

## File Responsibility Map

### New files

- `src/marten_runtime/runtime/tool_episode_summary_prompt.py`
  - dedicated prompt and JSON schema instructions for the post-turn summarizer
- `tests/test_tool_episode_summary_prompt.py`
  - prompt/schema contract tests for the dedicated summarizer prompt and JSON output contract

### Modified files

- `src/marten_runtime/runtime/tool_outcome_extractor.py`
  - shrink from rules-first extractor into tiny deterministic fallback helper or rename responsibility if needed
- `src/marten_runtime/runtime/llm_client.py`
  - add a small summarizer request path or helper method for tool-episode summary generation
- `src/marten_runtime/runtime/loop.py`
  - collect the finished tool episode and invoke summarization after the turn completes
- `src/marten_runtime/runtime/history.py`
  - modify only if the existing diagnostics path truly needs one thin flag; do not widen history persistence just for summarizer telemetry
- `src/marten_runtime/session/tool_outcome_summary.py`
  - adjust model fields to match the smaller LLM-first contract (`summary_text`, `facts`, `volatile`, `keep_next_turn`, `refresh_hint`)
- `src/marten_runtime/session/models.py`
  - keep session sidecar shape aligned with the refined model
- `src/marten_runtime/session/store.py`
  - trim / dedupe / persist the refined summary model
- `src/marten_runtime/runtime/context.py`
  - reinject only non-volatile / budget-fitting summaries
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - wire persistence and carry-forward through the existing request path
- `tests/test_tool_outcome_summary.py`
  - align to refined model and retention rules
- `tests/test_tool_outcome_extractor.py`
  - convert from broad semantic extractor assertions into fallback-only assertions
- `tests/test_runtime_loop.py`
  - verify summarizer path, fallback path, and no-turn-break semantics
- `tests/test_runtime_context.py`
  - verify reinjection, omission of volatile summaries, and budget behavior
- `tests/test_models.py`
  - verify outbound message assembly remains unchanged except for thin reinjection block
- `tests/test_session.py`
  - verify persistence/trim/dedupe of the refined sidecar
- `tests/test_acceptance.py`
  - verify end-to-end continuity through HTTP path
- `docs/README.md`
  - add the new design/plan as current source-of-truth for this slice
- `STATUS.md`
  - sync the new baseline and next steps

---

## Execution Strategy

Implement in small slices. Do not start with live MCP debugging. First freeze the new contract in tests, then simplify the implementation toward it.

---

## Chunk 1: Freeze The New Boundary In Tests

### Task 1.1 — Update the summary model expectations

- [ ] Refine the tests for `session/tool_outcome_summary.py` so they expect the smaller LLM-first fields:
  - `summary_text`
  - `facts`
  - `volatile`
  - `keep_next_turn`
  - `refresh_hint`
- [ ] Remove expectations that depend on broad rules-based semantic extraction of arbitrary tool payloads.

### Task 1.2 — Lock reinjection semantics

- [ ] Add/adjust tests in `tests/test_runtime_context.py` to prove:
  - replay history remains `user/assistant` only
  - summary reinjection stays thin
  - volatile summaries are skipped by default
  - budget trimming still works

### Task 1.3 — Lock loop semantics

- [ ] Add/adjust tests in `tests/test_runtime_loop.py` to prove:
  - summarization only runs after a completed tool-bearing turn
  - summarization failure does not fail the turn
  - fallback can be used when summarizer fails
  - same-turn tool follow-up behavior is unchanged

### Verification

Run a focused test slice after this chunk.

Suggested command:

- `PYTHONPATH=src python -m unittest tests.test_tool_outcome_summary tests.test_runtime_context tests.test_runtime_loop -v`

---

## Chunk 2: Introduce The Dedicated Tool-Episode Summarizer

### Task 2.1 — Add the prompt contract

- [ ] Create `src/marten_runtime/runtime/tool_episode_summary_prompt.py`
- [ ] Keep it small and explicit:
  - summarize only completed tool episodes
  - keep only next-turn-useful outcome
  - mark volatile results
  - never preserve raw payload dumps
  - output strict JSON only

### Task 2.2 — Add a small LLM client helper

- [ ] Add a helper in `src/marten_runtime/runtime/llm_client.py` for running the summarizer against a narrow episode payload
- [ ] Reuse the current provider infrastructure instead of inventing a second client stack
- [ ] Default v1 to the current turn's existing model profile / client path; do not introduce a new dedicated summarizer config surface unless it is already trivial and non-invasive
- [ ] Keep failure handling local and cheap
- [ ] Ensure summarizer calls are out-of-band: they must not be persisted as user/assistant history, must not trigger a second user-visible answer path, and must not recurse into the same summary feature

### Verification

- [ ] Add targeted unit tests around prompt/schema validation and response parsing
- [ ] Run the focused test slice for the new helper

---

## Chunk 3: Replace Rules-First Extraction With LLM-First Summary

### Task 3.1 — Collect the episode in runtime loop

- [ ] In `src/marten_runtime/runtime/loop.py`, capture the minimum finished episode context:
  - user request text
  - assistant tool calls
  - tool results
  - final assistant reply
- [ ] Hard-cap the summarizer input slice so this optimization does not become a second large-context problem:
  - include only the current turn's episode
  - prefer final assistant reply + compact tool-call metadata over full raw payloads when possible
  - truncate oversized tool results before sending them to the summarizer

### Task 3.2 — Generate post-turn summary

- [ ] Invoke the summarizer only when:
  - at least one tool succeeded
  - the assistant completed the turn
- [ ] Validate JSON output and map it into `ToolOutcomeSummary`

### Task 3.3 — Keep a tiny fallback

- [ ] Reduce `tool_outcome_extractor.py` to a minimal degraded path
- [ ] Remove or delete growing MCP-specific semantic extraction branches that are no longer justified
- [ ] Prefer omission over noisy fallback data

### Verification

- [ ] Run targeted unit tests for the loop + fallback path
- [ ] Confirm no same-turn tool behavior changed

Suggested command:

- `PYTHONPATH=src python -m unittest tests.test_tool_outcome_summary tests.test_tool_outcome_extractor tests.test_runtime_loop tests.test_models -v`

---

## Chunk 4: Refine Session Sidecar And Reinjection

### Task 4.1 — Shrink the model to what is actually needed

- [ ] Update `session/tool_outcome_summary.py`, `session/models.py`, and `session/store.py` so the persisted record reflects the refined LLM-first shape
- [ ] Keep retention tiny:
  - persist <= 3 recent summaries
  - render <= 2 summaries

### Task 4.2 — Enforce volatile / next-turn policy

- [ ] In `runtime/context.py`, render only summaries where:
  - `keep_next_turn == true`
  - `volatile == false`
  - summary fits budget
- [ ] If volatile summaries are persisted at all, treat them as diagnostics-only by default; they must not be reinjected as cross-turn truth
- [ ] Allow future extension for short TTL-like logic without implementing a memory subsystem now

### Verification

- [ ] Run session/context tests
- [ ] Verify generated reinjection text is still compact and readable

Suggested command:

- `PYTHONPATH=src python -m unittest tests.test_tool_outcome_summary tests.test_runtime_context tests.test_session -v`

---

## Chunk 5: End-to-End Regression And Thin Live Verification

### Task 5.1 — Local regression

- [ ] Run the focused regression suite covering:
  - summary model
  - fallback path
  - runtime loop
  - context reinjection
  - session persistence
  - acceptance path

Suggested command:

- `PYTHONPATH=src python -m unittest tests.test_tool_outcome_summary tests.test_tool_outcome_extractor tests.test_runtime_context tests.test_runtime_loop tests.test_models tests.test_session tests.test_acceptance -v`

### Task 5.2 — Live provider verification

Run thin live checks against the real `/messages` chain.

Required scenarios:

- [ ] plain 2-turn baseline (no summary expected)
- [ ] builtin 2-turn (`runtime.context_status`) continuity
- [ ] MCP 2-turn continuity with the real configured GitHub MCP (not only mock MCP)
- [ ] skill-triggered continuity
- [ ] `time`-style volatile behavior proving the next turn re-calls the tool instead of reusing stale value

Capture at least:

- first-turn tool use presence
- stored summary text
- second-turn actual reinjection text
- second-turn whether the model answered correctly without raw tool transcript replay

### Task 5.3 — Complexity check

- [ ] Audit the implementation after tests pass
- [ ] Remove leftover rules-first branches or dead helpers
- [ ] Confirm this slice did not widen into a memory platform

---

## Acceptance Criteria

Do not mark this slice complete unless all of the following are true:

- [ ] same-turn tool follow-up behavior is unchanged
- [ ] cross-turn continuity comes primarily from LLM episode summary, not rules-first extraction
- [ ] volatile results are not incorrectly reused
- [ ] fallback exists but remains intentionally thin
- [ ] real `/messages` verification shows summary reinjection on builtin / real GitHub MCP / skill turns
- [ ] the summarizer path remains post-turn and out-of-band rather than mutating the main user-visible answer path
- [ ] no raw tool transcript is replayed across turns
- [ ] the final implementation is simpler than continuing to expand parser rules

---

## Cleanup Guidance

When the implementation is complete, delete or simplify code that no longer fits the refined design:

- rules-first semantic extraction branches for specific MCP result shapes
- unused fact keys that only served the old parser-heavy path
- tests whose only purpose was to freeze parser sprawl

Keep only:

- summary sidecar model/persistence
- summarizer prompt + helper
- minimal fallback
- reinjection and retention logic

---

## Documentation Sync

When implementation progresses, sync at minimum:

- `STATUS.md`
- `docs/README.md`
- this plan file if any execution detail changes materially

If the earlier rules-first plan remains in the repo, mark it as historical or superseded by this LLM-first design so future coding agents do not drift back into parser-heavy work.
