# Session Transition Async Compaction Implementation Plan

> **For agentic workers:** Execute this plan in the current branch and current workspace. Steps use checkbox (`- [x]`) syntax for tracking. Do not commit, do not spawn subagents, and do not widen scope beyond session-transition async compaction, partial persistence, and operator diagnostics unless the user explicitly asks.

**Goal:** Move source-session compaction out of the synchronous `session.new` / `session.resume` path so session switching completes on bind, compaction continues in a dedicated background worker, and operators can see queue / LLM / persist timings for the background job.

**Architecture:** Keep the harness thin and preserve the current LLM-first runtime path. Session transition remains a synchronous session-store operation plus durable compaction job enqueue. A dedicated compaction worker thread drains persisted jobs by calling `run_compaction(...)` directly with an isolated LLM client, then writes compacted context back through a narrow compare-and-set persistence API that cannot overwrite newer session history.

**Tech Stack:** Python 3.11+, unittest, existing `SessionStore` / `SQLiteSessionStore`, existing `run_compaction(...)`, existing HTTP bootstrap / diagnostics stack, existing `CachedLLMClientFactory`

---

## Global implementation constraints

- Preserve the current runtime-owned execution spine: `channel -> binding -> runtime loop -> session tool -> delivery`.
- `session.new` / `session.resume` success is owned by conversation binding and target-session resolution. Compaction becomes background maintenance.
- Background compaction must **not** call `RuntimeLoop.run()` and must **not** reuse subagent execution.
- Keep the queue surface narrow: one dedicated compaction worker, persisted jobs, no generic job framework.
- Prevent stale snapshot overwrite: background writeback must update compacted-context fields only and must reject older or smaller source ranges.
- Background compaction must use an isolated LLM client instance so `last_call_diagnostics` and retry state from foreground runs stay independent.
- Keep direct-render / recovery contracts stable except for additive compaction metadata needed to describe queued background work.
- Keep top-level transition compaction fields decision-scoped. Queue lifecycle details live under `compaction_job` instead of overloading `compaction_reason` with worker state.
- Keep user-facing wording stable unless a changed contract requires one short additive clause.
- Tests stay offline and deterministic; use scripted/fake clients and synchronous worker-drain helpers.
- Full completion requires focused unit coverage, integration coverage, acceptance coverage, and diff hygiene.

---

## Anti-drift execution rules

- Do not route compaction through `RuntimeLoop`, `SubagentService`, or new prompt-level tool calls.
- Do not add host-side natural-language routing logic.
- Do not refactor unrelated diagnostics, runtime followup, or Feishu delivery code.
- Do not redesign the entire session store. Add only the partial-update and job APIs needed for this slice.
- Do not broaden async execution to unrelated tools.
- Do not introduce a second queue backend or separate database unless the current `sessions.sqlite3` path proves insufficient during implementation.
- Prefer additive contract fields over renaming existing fields that many tests already lock.

---

## File structure and responsibility map

### New files

- `src/marten_runtime/session/compaction_job.py`
  - Define persisted compaction job models and timing/result payloads.
- `src/marten_runtime/session/compaction_worker.py`
  - Own the dedicated background worker thread, job claim loop, isolated LLM client acquisition, `run_compaction(...)` invocation, and job lifecycle bookkeeping.
- `tests/test_session_compaction_worker.py`
  - Focused tests for worker execution, isolated LLM usage, timing capture, retry-safe job lifecycle, and compare-and-set writeback.

### Existing files to modify

- `src/marten_runtime/session/transition.py`
  - Replace inline source-session compaction with enqueue-or-skip decision logic and return additive compaction job metadata.
- `src/marten_runtime/session/store.py`
  - Add abstract/narrow store APIs for compaction job persistence and compacted-context compare-and-set writes.
- `src/marten_runtime/session/sqlite_store.py`
  - Implement job persistence in `sessions.sqlite3`, startup recovery for stale running jobs, and partial compacted-context updates that never rewrite message history.
- `src/marten_runtime/tools/builtins/session_tool.py`
  - Preserve transition output shape, add additive compaction job info, and keep session list/show behavior stable.
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - Extend `CachedLLMClientFactory` with isolated-client construction, attach the compaction worker to runtime state, and start it during bootstrap.
- `src/marten_runtime/interfaces/http/app.py`
  - Stop the compaction worker during app shutdown.
- `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
  - Record additive compaction queue/job metadata in `latest_session_transition`.
- `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
  - Expose worker queue depth and latest compaction job diagnostics in the runtime diagnostics payload.
- `tests/test_session_transition.py`
  - Replace inline-compaction expectations with enqueue/skip expectations.
- `tests/tools/test_session_tool.py`
  - Lock additive transition payload fields and no-op behavior.
- `tests/test_sqlite_session_store.py`
  - Cover compaction job persistence, stale-running-job recovery, and compacted-context compare-and-set writes.
- `tests/test_http_runtime_diagnostics.py`
  - Verify runtime diagnostics expose sanitized worker/job metadata.
- `tests/test_acceptance.py`
  - Add a full-chain acceptance proof that `session.resume` returns promptly while background compaction completes separately.

### Existing tests likely needing expectation refresh only

- `tests/test_recovery_flow.py`
- `tests/test_tool_followup_support.py`
- `tests/runtime_loop/test_tool_followup_and_recovery.py`
- `tests/runtime_loop/test_provider_failover.py`

Keep these edits minimal and limited to additive transition metadata or updated compaction reason values if owner tests exercise the real session-tool result.

---

## Chunk 1: Lock the new async contract with failing tests

### Task 1: Redefine the session-transition contract around bind-plus-enqueue

**Files:**
- Modify: `src/marten_runtime/session/transition.py`
- Modify: `tests/test_session_transition.py`
- Modify: `tests/tools/test_session_tool.py`

- [x] **Step 1: Write failing transition tests for bind-first async behavior**

Cover:
- `session.resume` binds the target session immediately and returns a stable deferred decision value in the top-level transition fields when a source prefix needs compaction
- `session.new` keeps the same async rule so both transition actions share one contract
- `same_session` remains a short-circuit with no job enqueue
- `no_prefix` / `up_to_date` still skip compaction work
- enqueue failure keeps the session switch successful and records a stable top-level enqueue-failure decision plus `compaction_job.enqueue_status="failed"`

- [x] **Step 2: Write failing session-tool presentation tests**

Cover:
- transition payload keeps existing keys: `mode`, `binding_changed`, `source_session_id`, `target_session_id`, `compaction_attempted`, `compaction_succeeded`, `compaction_reason`
- transition payload adds one nested additive block such as `compaction_job`, and queued/running/completed worker state is expressed there instead of being copied into top-level transition fields
- no-op same-session resume still renders current-session wording with no fake background job

- [x] **Step 3: Implement the minimal contract change in `transition.py` and `session_tool.py`**

Implementation notes:
- move “should compact?” into a pure decision path
- replace synchronous `run_compaction(...)` with a store enqueue call
- keep compaction metadata additive and machine-readable
- keep top-level `compaction_reason` reserved for transition decisions such as deferred / skipped / enqueue_failed, while worker execution status lives under `compaction_job`
- keep recovery / direct-render behavior driven by existing transition mode, not by new host routing

- [x] **Step 4: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session_transition tests.tools.test_session_tool`

Expected: PASS

- [x] **Step 5: Checkpoint scope**

Confirm:
- no runtime loop / subagent wiring has been touched yet
- no user-visible prompt text changed outside session transition payloads

---

## Chunk 2: Add durable compaction jobs and safe partial persistence

### Task 2: Extend the session store with persisted jobs and compare-and-set compact writes

**Files:**
- Create: `src/marten_runtime/session/compaction_job.py`
- Modify: `src/marten_runtime/session/store.py`
- Modify: `src/marten_runtime/session/sqlite_store.py`
- Modify: `tests/test_sqlite_session_store.py`

- [x] **Step 1: Write failing store tests for compaction job persistence**

Cover:
- enqueue persists a queued compaction job with source-session id, replay window, current message, and snapshot boundary
- claim marks one queued job running and records `started_at`
- success/failure writes `finished_at`, timing fields, and result/error details
- startup recovery moves stale `running` jobs back to `queued`

- [x] **Step 2: Write failing store tests for safe compacted-context writeback**

Cover:
- a worker can update compacted-context fields without deleting or rewriting session messages
- an older/smaller `source_message_range` write is rejected when a newer checkpoint already exists
- a concurrent `append_message(...)` after job enqueue remains present after compacted-context writeback

- [x] **Step 3: Implement the persisted job model and store APIs**

Implementation notes:
- keep jobs in `sessions.sqlite3`
- add one `session_compaction_jobs` table instead of a new database
- add narrow APIs such as `enqueue_compaction_job(...)`, `claim_next_compaction_job(...)`, `complete_compaction_job_* (...)`, `reset_running_compaction_jobs(...)`
- add a narrow partial-write API such as `set_compacted_context_if_newer(...)`

- [x] **Step 4: Run focused store tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_sqlite_session_store`

Expected: PASS

- [x] **Step 5: Checkpoint scope**

Confirm:
- `SQLiteSessionStore` now owns durable compaction-job persistence
- compacted-context writes no longer depend on full-record rewrite semantics for this path

---

## Chunk 3: Build the dedicated background compaction worker

### Task 3: Execute queued compaction jobs off the foreground path

**Files:**
- Create: `src/marten_runtime/session/compaction_worker.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Create: `tests/test_session_compaction_worker.py`

- [x] **Step 1: Write failing worker tests for isolated execution**

Cover:
- worker drains one queued job and calls `run_compaction(...)`
- worker uses an isolated client instance instead of the shared foreground client
- worker records `queue_wait_ms`, `compaction_llm_ms`, and `persist_ms`
- worker marks failures cleanly when LLM generation fails or returns empty output

- [x] **Step 2: Write failing bootstrap/lifecycle tests**

Cover:
- runtime bootstrap creates and starts one compaction worker
- app shutdown stops the worker cleanly
- startup recovery re-queues stale running jobs before the worker starts draining

- [x] **Step 3: Implement the worker and isolated-client acquisition**

Implementation notes:
- worker thread owns a simple wake/sleep loop plus explicit `start()` / `stop()`
- worker calls `run_compaction(...)` directly, never `RuntimeLoop.run()`
- extend `CachedLLMClientFactory` with a narrow uncached/isolation path for background jobs
- keep concurrency at one worker thread for this slice

- [x] **Step 4: Run focused worker tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session_compaction_worker`

Expected: PASS

- [x] **Step 5: Checkpoint scope**

Confirm:
- background execution stays inside dedicated compaction code
- no subagent service or runtime loop coupling was introduced

---

## Chunk 4: Surface operator diagnostics without widening the runtime path

### Task 4: Add narrow diagnostics for queued/running/completed compaction jobs

**Files:**
- Modify: `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `tests/test_http_runtime_diagnostics.py`
- Modify: `tests/test_session_transition.py`
- Modify: `tests/tools/test_session_tool.py`

- [x] **Step 1: Write failing diagnostics tests**

Cover:
- `latest_session_transition` includes additive `compaction_job` metadata for queued transitions
- runtime diagnostics include one narrow worker block with queue depth and latest job timing/result fields
- diagnostics stay sanitized and never leak API keys or raw provider headers

- [x] **Step 2: Implement additive diagnostics fields**

Required fields:
- `job_id`
- `enqueue_status`
- `status`
- `enqueued_at`
- `started_at`
- `finished_at`
- `queue_wait_ms`
- `compaction_llm_ms`
- `persist_ms`
- `snapshot_message_count`
- `prefix_end_index`
- `source_range_end`
- `write_applied`
- `result_reason`
- `error_code` or short `error_text` when failed

- [x] **Step 3: Refresh minimal owner tests that assert transition payload shape**

Targets:
- `tests/test_recovery_flow.py`
- `tests/test_tool_followup_support.py`
- `tests/runtime_loop/test_tool_followup_and_recovery.py`
- `tests/runtime_loop/test_provider_failover.py`

Keep these edits expectation-only unless a real contract failure appears.

- [x] **Step 4: Run focused diagnostics tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_runtime_diagnostics tests.test_recovery_flow tests.test_tool_followup_support tests.runtime_loop.test_tool_followup_and_recovery tests.runtime_loop.test_provider_failover`

Expected: PASS

- [x] **Step 5: Checkpoint scope**

Confirm:
- diagnostics are additive and operator-facing only
- no new user-facing routing or prompt rules were added

---

## Chunk 5: Prove the full chain and protect against regression

### Task 5: Add end-to-end proof and run the regression bundle

**Files:**
- Modify: `tests/test_acceptance.py`
- Modify: `STATUS.md`

- [x] **Step 1: Write failing acceptance coverage**

Cover:
- a session switch completes without waiting for compaction generation
- the foreground response shows the target session immediately
- a background compaction job completes later and updates the source session checkpoint
- diagnostics expose the queued job, its snapshot boundary, and its completion timings

- [x] **Step 2: Implement any remaining glue for acceptance coverage**

Implementation notes:
- prefer a test helper that drains the worker deterministically in-process
- keep acceptance assertions on observable contracts, not thread timing accidents

- [x] **Step 3: Run focused acceptance tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_acceptance`

Expected: PASS

- [x] **Step 4: Run the full regression bundle**

Run:
- `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session_transition tests.tools.test_session_tool tests.test_sqlite_session_store tests.test_session_compaction_worker tests.test_http_runtime_diagnostics tests.test_recovery_flow tests.test_tool_followup_support tests.runtime_loop.test_tool_followup_and_recovery tests.runtime_loop.test_provider_failover tests.test_acceptance`
- `cd /Users/litiezhu/workspace/github/marten-runtime && git diff --check`

Expected:
- all listed tests PASS
- `git diff --check` PASS

- [x] **Step 5: Update continuity**

Update `STATUS.md` with:
- plan location
- current goal
- files touched during implementation
- verification commands and latest results
- any live-runtime follow-up still pending after tests pass

---

## Plan self-check before implementation

- This plan keeps compaction out of `RuntimeLoop.run()` and out of subagent execution.
- This plan keeps the harness boundary thin: synchronous bind, asynchronous maintenance.
- This plan addresses the two concrete risks already identified:
  - stale compacted-context overwrite
  - shared-client diagnostics clobbering
- This plan keeps diagnostics additive and narrow while still carrying enough fields to explain queueing, snapshot scope, LLM time, and writeback outcome.
- This plan keeps tests ahead of implementation in every chunk.
- This plan stays inside the agreed scope: session-transition async compaction, safe persistence, and operator observability.

## Open implementation choice already resolved

- **Queue durability:** use the existing `sessions.sqlite3` store.
- **Execution model:** one dedicated compaction worker thread.
- **LLM path:** direct `run_compaction(...)` with an isolated client instance.
- **Foreground success condition:** bind/target-session success only.
- **Writeback rule:** compacted-context compare-and-set by source range freshness.
