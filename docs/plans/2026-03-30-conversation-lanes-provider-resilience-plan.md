# Conversation Lanes And Provider Resilience Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Phase 1 conversation queueing and stronger LLM/provider resilience without converting `marten-runtime` into a durable worker platform.

**Architecture:** Keep the existing synchronous main chain intact, but change interactive entrypoints from busy-reject to per-conversation in-memory FIFO queueing. Lane state stays in-memory for this phase. Strengthen provider retry/error normalization and expose real diagnostics for active and queued work. Do not introduce durable jobs, worker pools, automation scheduler rewrites, or distributed coordination in this plan.

**Tech Stack:** Python, FastAPI, Pydantic, unittest

---

## Execution Guardrails

- Do not introduce durable queue tables or worker polling in this plan.
- Do not move runtime execution out of the current request/event path.
- Do not add GitHub-specific or Feishu-specific hardcoded business routing.
- Do not expand into session persistence or distributed locks.
- Keep user-facing fallback text stable unless a test explicitly requires a contract update.

## File Structure

### Create

- `src/marten_runtime/runtime/lanes.py`
- `tests/test_runtime_lanes.py`
- `docs/2026-03-30-conversation-lanes-provider-resilience-design.md`

### Modify

- `src/marten_runtime/interfaces/http/bootstrap.py`
- `src/marten_runtime/interfaces/http/app.py`
- `src/marten_runtime/channels/feishu/service.py`
- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/llm_client.py`
- `src/marten_runtime/runtime/provider_retry.py`
- `tests/test_feishu.py`
- `tests/test_runtime_loop.py`
- `tests/test_provider_retry.py`
- `tests/test_contract_compatibility.py`
- `tests/test_gateway.py`
- `STATUS.md`
- `/Users/litiezhu/workspace/code/STATUS.md`

## Chunk 1: Conversation Lane Core

### Task 1: Add lane manager primitives

**Files:**
- Create: `src/marten_runtime/runtime/lanes.py`
- Create: `tests/test_runtime_lanes.py`

- [ ] **Step 1: Write the failing tests for same-lane queueing and independent-lane success**

Add tests that assert:
- same `channel_id + conversation_id` is executed FIFO rather than rejected
- marking one item finished allows the next queued item to start
- different conversations can hold claims at the same time

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_lanes -v`
Expected: FAIL because `marten_runtime.runtime.lanes` or its lane manager types do not exist yet.

- [ ] **Step 3: Implement the minimal lane manager**

Create:
- `LaneKey`
- `LaneClaim`
- `ConversationLaneManager`

Required behavior:
- in-memory per-lane queue registry
- `enqueue(...)` / `mark_started(...)` / `mark_finished(...)` support FIFO progression
- finishing is idempotent
- `stats()` returns active lane summaries plus queue counters
- key shape stays minimal: `channel_id + conversation_id`

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_lanes -v`
Expected: PASS, with explicit coverage for queue ordering and finish behavior.

## Chunk 2: HTTP Admission Control

### Task 2: Queue `/messages` by conversation lane

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `tests/test_gateway.py`
- Modify: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Write failing tests for same-conversation HTTP overlap queueing**

Add tests that simulate:
- one active request already holds the lane
- a second `/messages` request on the same conversation is queued and eventually completes normally
- another conversation still proceeds normally

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_gateway tests.test_contract_compatibility -v`
Expected: FAIL because the app still has no queueing semantics for overlapping same-conversation requests.

- [ ] **Step 3: Wire the lane manager into bootstrap runtime state**

In `bootstrap.py`:
- instantiate one shared `ConversationLaneManager`
- expose it on the assembled runtime object

In `app.py`:
- resolve lane key before executing the runtime turn
- enqueue same-lane overlap instead of returning `409`
- ensure queued requests wake and execute in FIFO order
- always advance the lane in `finally`

- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python -m unittest tests.test_gateway tests.test_contract_compatibility -v`
Expected: PASS, and contract tests confirm same-conversation overlap now queues and returns a normal `200` response in order.

## Chunk 3: Feishu Admission Control

### Task 3: Queue Feishu inbound turns with the same lane manager

**Files:**
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `tests/test_feishu.py`

- [ ] **Step 1: Write failing tests for Feishu same-chat queueing**

Add tests that simulate:
- one lane already active for a Feishu chat
- a second inbound event for the same chat is queued behind the first
- queued overlap does not create a busy visible reply
- a different chat still runs successfully

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: FAIL because Feishu currently has no explicit lane-based queue handling.

- [ ] **Step 3: Implement Feishu queue handling**

Required behavior in `service.py`:
- compute the same lane key shape used by HTTP
- enqueue before invoking `runtime_handler`
- same-chat events execute serially in FIFO order
- do not emit busy visible replies
- advance the lane after the runtime/delivery path completes

- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: PASS, including a case where queued overlap does not create a channel-visible busy fallback reply.

## Chunk 4: Provider Retry Hardening

### Task 4: Expand retry classification and bounded backoff

**Files:**
- Modify: `src/marten_runtime/runtime/provider_retry.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Modify: `tests/test_provider_retry.py`

- [ ] **Step 1: Write failing tests for retryable HTTP status codes**

Add tests that assert:
- `provider_http_error:429:*` is retryable
- `provider_http_error:502:*`, `503`, `504` are retryable
- `401/403` remain fail-fast
- response/schema errors remain fail-fast

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_provider_retry -v`
Expected: FAIL because current normalization does not classify those HTTP codes as retryable.

- [ ] **Step 3: Implement retry classification and jitter**

In `provider_retry.py`:
- normalize retryable upstream statuses
- preserve existing timeout/transport retry
- add small bounded jitter to backoff
- keep `max_attempts`, `base_backoff_seconds`, and `max_backoff_seconds` configurable

In `llm_client.py`:
- preserve use of `with_retry(...)`
- ensure normalized provider errors propagate with stable error codes

- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python -m unittest tests.test_provider_retry -v`
Expected: PASS, showing transient upstream failures retry and auth/config failures do not.

## Chunk 5: Runtime Error Surface

### Task 5: Preserve normalized provider error codes in runtime history and events

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `tests/test_runtime_loop.py`
- Modify: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Write failing tests for provider-specific runtime failure codes**

Add tests that assert:
- exhausted provider timeout becomes an `error` event with provider-specific code
- run history stores the same normalized code
- non-provider runtime exceptions can still use `RUNTIME_LOOP_FAILED`

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility -v`
Expected: FAIL because current runtime loop collapses most provider failures into `RUNTIME_LOOP_FAILED`.

- [ ] **Step 3: Implement selective error downgrade behavior**

In `loop.py`:
- catch normalized provider errors separately
- emit stable provider-facing codes in error events/history
- preserve current fallback text unless tests require otherwise
- leave unknown internal exceptions mapped to `RUNTIME_LOOP_FAILED`

- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility -v`
Expected: PASS, confirming provider-specific error codes are now observable without breaking event-shape compatibility.

## Chunk 6: Diagnostics Sync

### Task 6: Replace fake queue diagnostics with real lane diagnostics

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `tests/test_contract_compatibility.py`
- Modify: `tests/test_gateway.py`

- [ ] **Step 1: Write failing tests for lane diagnostics**

Add tests that assert:
- `/diagnostics/queue` reflects lane mode rather than fake zero values
- runtime diagnostics include lane summary and provider retry policy
- queue counters increment after overlap enqueue

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_gateway tests.test_contract_compatibility -v`
Expected: FAIL because `/diagnostics/queue` still returns static placeholder data.

- [ ] **Step 3: Implement diagnostics**

Required fields:
- `mode = "conversation_lanes"`
- `active_lane_count`
- `active_lanes`
- `queued_lane_count`
- `queued_items_total`
- `max_queue_depth`
- `last_enqueued_lane`
- `provider_retry_policy`

Do not expose secrets, prompt bodies, or raw user text.

- [ ] **Step 4: Run targeted tests**

Run: `PYTHONPATH=src python -m unittest tests.test_gateway tests.test_contract_compatibility -v`
Expected: PASS, and diagnostics expose real contention state.

## Chunk 7: Focused Regression Sweep

### Task 7: Re-run all touched surfaces together

**Files:**
- Modify: `STATUS.md`
- Modify: `/Users/litiezhu/workspace/code/STATUS.md`

- [ ] **Step 1: Run the focused suite**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_lanes tests.test_gateway tests.test_feishu tests.test_provider_retry tests.test_runtime_loop tests.test_contract_compatibility -v`
Expected:
- PASS
- lane queueing, provider retry, and diagnostics coverage all green

- [ ] **Step 2: Run the broader regression suite**

Run: `PYTHONPATH=src python -m unittest -v`
Expected:
- PASS
- no previously green runtime/tool/skill/automation tests regress

- [ ] **Step 3: Run local HTTP smoke**

Run: `PYTHONPATH=src python -m uvicorn marten_runtime.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8030`
Expected:
- server starts successfully

Run: `curl -sS http://127.0.0.1:8030/healthz`
Expected:
- `{"status":"ok"}`

Run: `curl -sS http://127.0.0.1:8030/diagnostics/queue`
Expected:
- JSON response showing `mode = "conversation_lanes"`

- [ ] **Step 4: Run overlapping HTTP contention smoke**

Use two requests against the same conversation with one request artificially held by a test double or controlled hook.
Expected:
- one request completes normally
- the second waits in queue and then returns normal `200` after the first completes

- [ ] **Step 5: Update continuity files**

Required updates:
- repo `STATUS.md`
- workspace `/Users/litiezhu/workspace/code/STATUS.md`

Record:
- conversation lanes phase-1 design/plan complete
- implementation not yet started, if still at planning stage
- next action is executing this plan chunk by chunk

## Phase 1 Exit Criteria

- [ ] same conversation overlap is serialized in FIFO order rather than rejected
- [ ] different conversations still execute independently
- [ ] Feishu overlap queues without creating extra busy visible replies
- [ ] provider timeout and retryable upstream failures recover when possible
- [ ] exhausted provider failures preserve normalized error codes
- [ ] `/diagnostics/queue` no longer returns fake placeholder data
- [ ] focused suite green
- [ ] full suite green

## Phase 2 Follow-On, Not In Scope Here

After Phase 1 is green, a separate plan may introduce:

- durable inbound jobs
- worker-owned lane execution
- dead-letter for runtime jobs
- cross-process lane coordination
