# Lightweight Subagent Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Ship a thin async background subagent capability for `marten-runtime` that lets the main agent delegate bounded work to isolated child sessions, keep the service substrate restricted-by-default while allowing constrained product-level profile inference, and expose enough diagnostics to prove parent -> task -> child session -> child run traceability.

**Architecture:** Keep the harness thin. Do not turn subagents into a workflow system or planner runtime. Implement one parent-triggered async child task model backed by a narrow `SubagentService`, a bounded task store, isolated child sessions, structured status/result events, and explicit diagnostics. Child execution reuses `RuntimeLoop.run(...)` as the execution engine but keeps lifecycle/orchestration concerns outside `RuntimeLoop`.

**Tech Stack:** Python 3.11+, unittest, existing runtime loop/session/run-history infrastructure, FastAPI diagnostics routes, Markdown continuity docs

---

## Global implementation constraints

These rules apply to every chunk below.

- Child tasks are **single-level only** in Phase 1; no nested spawn.
- Child execution is **async background only**; do not implement sync wait semantics in this plan.
- Service/substrate default child `tool_profile` is `restricted`.
- Product entry may infer child `tool_profile = standard` when the user explicitly requests subagent/background execution or when the delegated task clearly needs broader generic tool access.
- Product-level inference must remain generic and must not special-case one MCP/tool vendor.
- Effective child permissions must never exceed the parent agent's ceiling.
- Child transcript/tool noise must not be automatically appended to the parent session transcript.
- Parent/child lineage must be explicit at both levels: `SessionRecord.parent_session_id` and `RunRecord.parent_run_id`.
- Phase 1 completion sink is fixed: one concise `SessionMessage.system(...)` is appended to the parent session on child terminal state; no transcript replay is allowed.
- Child tool profiles must compile down to the existing `allowed_tools` / `ToolRegistry.build_snapshot()` selector model.
- Background child tasks must be tracked and drained/cancelled by one service-owned lifecycle path; no scattered fire-and-forget tasks.
- Every module change must have targeted tests before the module is considered done.
- No chunk is complete until its proof command passes.
- `STATUS.md` must be updated when the implementation milestone is complete.

---

## Chunk 1: Lock the subagent contract with failing tests

### Task 1: Add task-store and lifecycle contract tests before implementation

**Files:**
- Create: `tests/test_subagent_store.py`
- Create: `tests/test_subagent_service.py`
- Inspect: `src/marten_runtime/runtime/history.py`
- Inspect: `src/marten_runtime/session/models.py`
- Inspect: `src/marten_runtime/interfaces/http/app.py`
- Inspect: `src/marten_runtime/runtime/loop.py`

- [x] **Step 1: Add failing tests for the `SubagentTask` model + store lifecycle**

Cover:
- task creation stores parent session id, label, status `queued`, requested profile, context mode
- child session creation persists `parent_session_id`, `session_kind="subagent"`, and incremented `lineage_depth`
- state transitions `queued -> running -> succeeded|failed|cancelled|timed_out`
- child session id is persisted at create time
- child run id can be added later
- list/get surfaces return stable structured state

Done when:
- tests clearly define the store API and state expectations
- tests fail because the store/model do not exist yet

- [x] **Step 2: Add failing tests for `SubagentService.spawn()` acceptance behavior**

Cover:
- accepted payload includes `task_id`, `child_session_id`, `status`, and effective profile
- `parent_run_id` is captured from spawn call context
- service default profile is `restricted`
- product entry inference to `standard` is separately covered when explicit user intent / broader-tool hints are present
- queue state reflects immediate-start vs queued cases
- invalid profile or missing task input is rejected cleanly

Done when:
- spawn acceptance contract is explicit in tests
- tests fail because no service exists yet

- [x] **Step 3: Add failing tests for background completion state updates**

Cover:
- success path updates `status`, `started_at`, `finished_at`, `result_summary`
- failure path updates `status`, `error_text`
- timeout path updates `status = timed_out`
- cancellation path updates `status = cancelled`

Done when:
- the service's end-state contract is pinned in tests
- tests fail for missing implementation

- [x] **Step 4: Run targeted tests and confirm expected red state**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_store tests.test_subagent_service
```
Expected: FAIL because the new subagent modules are not implemented yet.

---

## Chunk 2: Implement the subagent state model and in-memory store

### Task 2: Add the minimal `SubagentTask` model and store

**Files:**
- Create: `src/marten_runtime/subagents/models.py`
- Create: `src/marten_runtime/subagents/store.py`
- Modify: `src/marten_runtime/session/store.py`
- Test: `tests/test_subagent_store.py`

- [x] **Step 1: Implement `SubagentTask` and status enums/constants**

Required fields:
- `task_id`, `label`, `status`
- `parent_session_id`, `parent_run_id`, `parent_agent_id`
- `child_session_id`, `child_run_id`
- `app_id`, `agent_id`
- `tool_profile`, `effective_tool_profile`, `context_mode`
- `task_prompt`, `notify_on_finish`
- `result_summary`, `error_text`
- `created_at`, `started_at`, `finished_at`

Constraint:
- keep the model narrow; do not add generic job-system metadata

- [x] **Step 2: Extend `SessionStore` with one narrow child-session creation helper**

Required behavior:
- create child sessions with `parent_session_id`, `session_kind="subagent"`, and derived `lineage_depth`
- avoid duplicating raw `SessionRecord(...)` construction outside the session store

Constraint:
- child-session lineage rules must live in one place

- [x] **Step 3: Implement an in-memory subagent store with explicit transition helpers**

Required operations:
- create task
- get task
- list tasks
- mark running
- mark succeeded
- mark failed
- mark cancelled
- mark timed out
- attach child run id
- update terminal summary/error

Constraint:
- illegal transitions should be rejected or guarded consistently in one place

- [x] **Step 4: Re-run targeted store tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_store
```
Expected: PASS.

Done when:
- all task model/store tests pass
- state transitions are explicit, deterministic, and narrow

---

## Chunk 3: Implement `SubagentService` spawn/queue/run lifecycle

### Task 3: Add the thin background execution service

**Files:**
- Create: `src/marten_runtime/subagents/service.py`
- Modify: `src/marten_runtime/session/store.py`
- Modify: `src/marten_runtime/runtime/history.py`
- Test: `tests/test_subagent_service.py`

- [x] **Step 1: Implement `spawn()` with acceptance semantics**

Responsibilities:
- validate spawn request
- resolve effective profile
- read `session_id` / `run_id` from the spawning tool call context
- create child conversation/session id
- create child session via the session-store helper
- create task record in `queued`
- start immediately or enqueue based on concurrency cap
- return accepted payload

Constraint:
- child session ids must be deterministic enough for diagnostics correlation
- `spawn()` must return immediately; it must not block waiting for child completion

- [x] **Step 2: Implement background worker execution using `RuntimeLoop.run(...)`**

Responsibilities:
- mark task running
- build child request/context
- invoke runtime loop with `request_kind="subagent"`
- propagate `parent_run_id` into child run history
- capture child run id if emitted
- summarize success/failure
- append one concise terminal `SessionMessage.system(...)` to the parent session

Constraint:
- lifecycle logic belongs in the service, not in `RuntimeLoop`
- service must not append child transcript to the parent session automatically

- [x] **Step 3: Implement timeout and cancellation support**

Cover:
- configured child timeout
- task-level cancellation API
- running task cancel propagation
- queued task cancellation before start

Constraint:
- cancellation must leave a durable final state

- [x] **Step 4: Implement simple FIFO queueing + concurrency cap**

Constraint:
- Phase 1 queueing remains simple; no priorities, no starvation policy design

- [x] **Step 5: Add tracked service lifecycle / shutdown-drain behavior**

Cover:
- service owns the background task set
- shutdown drains or cancels outstanding child tasks deterministically

Constraint:
- no scattered fire-and-forget tasks outside the service-owned lifecycle

- [x] **Step 6: Re-run targeted service tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_service
```
Expected: PASS.

Done when:
- spawn acceptance, queueing, completion, timeout, and cancellation tests all pass
- the service remains thin and does not become a general async job orchestrator

---

## Chunk 4: Lock tool-profile and permission-ceiling behavior with tests

### Task 4: Add failing tests for child tool-profile enforcement

**Files:**
- Create: `tests/test_subagent_permissions.py`
- Inspect: `src/marten_runtime/tools/registry.py`
- Inspect: `src/marten_runtime/agents/specs.py`

- [x] **Step 1: Add failing tests for substrate default `restricted` child profile and product entry inference**

Cover:
- omitted profile at the service/profile-resolution layer resolves to `restricted`
- product entry may infer `standard` when explicit subagent intent / broader-tool hints are present
- restricted child snapshot excludes high-risk tools
- restricted profile remains usable for safe runtime/read-only work

- [x] **Step 2: Add failing tests for parent ceiling enforcement**

Cover:
- parent requesting `standard` or `elevated` does not exceed its own allowed surface
- child may be downgraded when parent lacks requested access
- child may not gain spawn capability in Phase 1
- profile resolution compiles to explicit allowed-tool selectors compatible with `ToolRegistry.build_snapshot()`

- [x] **Step 3: Run targeted tests and confirm failure before implementation**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_permissions
```
Expected: FAIL until profile enforcement exists.

### Task 5: Implement child tool-profile resolution and snapshot building

**Files:**
- Modify: `src/marten_runtime/tools/registry.py`
- Modify: `src/marten_runtime/subagents/service.py`
- Possibly create: `src/marten_runtime/subagents/tool_profiles.py`
- Test: `tests/test_subagent_permissions.py`

- [x] **Step 1: Add explicit child profile definitions**

Required profiles:
- `restricted`
- `standard`
- `elevated` (modeled conservatively)

Constraint:
- definitions must be explicit and readable; avoid hidden magic inheritance
- definitions must resolve into the repo's current allowed-tool selector scheme rather than a parallel permission format

- [x] **Step 2: Implement effective-profile resolution against parent ceiling**

Constraint:
- `effective child <= parent ceiling` is mandatory and must be enforced in one narrow place

- [x] **Step 3: Ensure child snapshots exclude recursive spawn capability in Phase 1**

Constraint:
- single-level child task invariant must be preserved by the tool snapshot, not just by prompt wording

- [x] **Step 4: Re-run targeted permission tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_permissions
```
Expected: PASS.

Done when:
- profile tests pass
- substrate default, product-level constrained inference, and parent-ceiling behavior are all proven by tests

---

## Chunk 5: Add the builtin spawn/cancel tool surface

### Task 6: Add failing tests for subagent builtin tools

**Files:**
- Create: `tests/tools/test_subagent_tools.py`
- Inspect: `src/marten_runtime/tools/builtins/runtime_tool.py`
- Inspect: `src/marten_runtime/interfaces/http/bootstrap.py`
- Inspect: `src/marten_runtime/runtime/loop.py`

- [x] **Step 1: Add failing tests for `spawn_subagent` tool schema and acceptance behavior**

Cover:
- required/optional parameters
- default values
- spawn handler reads `tool_context.session_id` and `tool_context.run_id`
- successful spawn returns accepted payload
- validation errors are surfaced predictably

- [x] **Step 2: Add failing tests for `cancel_subagent` behavior**

Cover:
- cancelling queued task
- cancelling running task
- unknown task id failure path

- [x] **Step 3: Run targeted tool tests and confirm failure before implementation**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.tools.test_subagent_tools
```
Expected: FAIL until builtin tools are wired.

### Task 7: Implement builtin tool registration and execution

**Files:**
- Create: `src/marten_runtime/tools/builtins/spawn_subagent_tool.py`
- Create: `src/marten_runtime/tools/builtins/cancel_subagent_tool.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_tool_registration.py` if needed
- Test: `tests/tools/test_subagent_tools.py`

- [x] **Step 1: Implement `spawn_subagent` builtin tool**

Constraint:
- tool returns immediately; no waiting for child completion
- tool contract must expose effective profile and child session id

- [x] **Step 2: Implement `cancel_subagent` builtin tool or equivalent narrow admin surface**

Constraint:
- cancellation remains task-scoped; do not introduce generic job management concepts

- [x] **Step 3: Register the new tool(s) in bootstrap/runtime wiring**

Constraint:
- only intended agents should see the tool surface
- child snapshots must not expose `spawn_subagent`
- parent-run/session correlation must be forwarded from tool context into the service unchanged

- [x] **Step 4: Re-run targeted tool tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.tools.test_subagent_tools
```
Expected: PASS.

Done when:
- spawn/cancel builtin tools are available in runtime wiring
- tool tests prove immediate acceptance and correct cancellation semantics

---

## Chunk 6: Add child request-kind handling and context isolation behavior

### Task 8: Add failing tests for child request/context behavior

**Files:**
- Create: `tests/test_subagent_runtime_loop.py`
- Inspect: `src/marten_runtime/runtime/loop.py`
- Inspect: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`

- [x] **Step 1: Add failing tests for `request_kind="subagent"`**

Cover:
- child requests use subagent request kind
- child prompt/context assembly differs from normal interactive path
- child request can accept `brief_only` and `brief_plus_snapshot`

- [x] **Step 2: Add failing tests proving parent transcript isolation**

Cover:
- child tool exchanges do not appear in parent session history by default
- parent only receives later status/summary surfaces

- [x] **Step 3: Run targeted runtime-loop tests and confirm failure before implementation**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_runtime_loop
```
Expected: FAIL until child request handling exists.

### Task 9: Implement child request-kind and context assembly support

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py` (only if parent-facing delivery hooks are needed here)
- Possibly create: `src/marten_runtime/subagents/context.py`
- Test: `tests/test_subagent_runtime_loop.py`

- [x] **Step 1: Add explicit `subagent` request-kind handling to runtime loop support**

Constraint:
- keep `RuntimeLoop` execution-oriented; do not move lifecycle orchestration here

- [x] **Step 2: Implement `brief_only` child context assembly**

Required contents:
- task brief
- high-signal constraints
- success criteria

Constraint:
- full parent transcript must not be included by default

- [x] **Step 3: Implement `brief_plus_snapshot` child context assembly**

Constraint:
- use only narrow compacted/high-signal parent state
- do not accidentally fork the full conversation

- [x] **Step 4: Re-run targeted runtime-loop tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_runtime_loop
```
Expected: PASS.

Done when:
- child request-kind is handled cleanly
- transcript isolation is proven by tests

---

## Chunk 7: Add parent-visible completion events and diagnostics

### Task 10: Add failing tests for completion events and diagnostics surfaces

**Files:**
- Create: `tests/contracts/test_subagent_contracts.py`
- Modify or inspect: `tests/contracts/test_runtime_contracts.py`
- Inspect: `src/marten_runtime/interfaces/http/app.py`

- [x] **Step 1: Add failing diagnostics tests for subagent list/detail endpoints**

Cover:
- `/diagnostics/subagents`
- `/diagnostics/subagent/{task_id}`
- stable fields: task id, status, parent session id, parent run id, child session id, child run id, timestamps, profiles, summary/error
- parent session contains one concise terminal system message after child completion/failure

- [x] **Step 2: Add failing tests for parent-visible completion/failure status events**

Cover:
- successful child execution produces structured completion status
- failed/timed-out child execution produces structured failure status
- diagnostics references are included or derivable

- [x] **Step 3: Run targeted diagnostics/contract tests and confirm failure before implementation**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.contracts.test_subagent_contracts
```
Expected: FAIL until endpoints/events are wired.

### Task 11: Implement diagnostics endpoints and parent-visible event surface

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/subagents/service.py`
- Possibly modify: `src/marten_runtime/interfaces/http/channel_event_serialization.py`
- Test: `tests/contracts/test_subagent_contracts.py`

- [x] **Step 1: Add diagnostics endpoints for subagent state**

Required endpoints:
- `/diagnostics/subagents`
- `/diagnostics/subagent/{task_id}`

- [x] **Step 2: Emit parent-visible structured completion/failure status events**

Constraint:
- return summary/status only; do not replay child transcript
- Phase 1 parent-visible sink is a concise `SessionMessage.system(...)`, not a second hidden event bus requirement

- [x] **Step 3: Ensure task state links cleanly to existing session/run diagnostics**

Constraint:
- parent session -> task -> child session -> child run correlation must be inspectable without reading logs

- [x] **Step 4: Re-run targeted diagnostics/contract tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.contracts.test_subagent_contracts
```
Expected: PASS.

Done when:
- diagnostics endpoints pass tests
- structured completion/failure visibility is proven

---

## Chunk 8: End-to-end runtime integration and regression proof

### Task 12: Add integration tests for the full async child flow

**Files:**
- Create: `tests/test_subagent_integration.py`
- Modify: `tests/test_gateway.py` or `tests/test_acceptance.py` if needed
- Inspect: `src/marten_runtime/interfaces/http/bootstrap.py`
- Inspect: `src/marten_runtime/interfaces/http/app.py`

- [x] **Step 1: Add a failing end-to-end test for spawn -> child run -> completion**

Cover:
- parent tool call spawns child
- child session exists independently with `parent_session_id` set
- child run completes with `parent_run_id` linked
- task state updates to success/failure
- parent session receives one concise terminal system message
- diagnostics show linked ids

- [x] **Step 2: Add a failing test for queue-limit / concurrency behavior**

Cover:
- second child is queued when cap is reached
- queued child starts after capacity frees up

- [x] **Step 3: Add failing tests for cancel/timeout through the integrated runtime path**

Cover:
- a spawned running child can be cancelled through the runtime-facing path and stays cancelled even if child execution resolves later
- timeout through the HTTP/runtime path lands in `timed_out` and emits the parent-visible terminal summary/notification surface

- [x] **Step 4: Run targeted integration tests and confirm failure before last-mile fixes**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_integration
```
Expected: FAIL until full wiring is complete.

### Task 13: Fix last-mile integration gaps and prove the slice

**Files:**
- Modify only the minimal affected runtime wiring files
- Test: `tests.test_subagent_integration`
- Modify: `STATUS.md`

- [x] **Step 1: Complete the remaining runtime wiring for the full async child flow**
- [x] **Step 2: Re-run targeted integration tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_subagent_integration
```
Expected: PASS.

- [x] **Step 3: Run the Phase 1 focused regression suite**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v \
  tests.test_subagent_store \
  tests.test_subagent_service \
  tests.test_subagent_permissions \
  tests.tools.test_subagent_tools \
  tests.test_subagent_runtime_loop \
  tests.contracts.test_subagent_contracts \
  tests.test_subagent_integration
```
Expected: PASS.

- [x] **Step 4: Run broader regression on touched runtime surfaces**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v \
  tests.runtime_loop.test_automation_and_trending_routes \
  tests.runtime_loop.test_context_status_and_usage \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.runtime_loop.test_forced_routes \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.test_gateway \
  tests.test_acceptance \
  tests.contracts.test_runtime_contracts \
  tests.contracts.test_gateway_contracts
```
Expected: PASS.

- [x] **Step 5: Update `STATUS.md` with implementation summary and proof results**

Done when:
- focused and broader regression suites pass
- `STATUS.md` records the completed implementation state and verification evidence

---

## Final done criteria

Phase 1 is done only if all of the following are true:

- [x] `spawn_subagent` exists and is wired into the main runtime tool surface
- [x] accepted spawn calls return immediately with task + child-session identifiers
- [x] spawn captures parent session + parent run lineage from tool context
- [x] child work executes in isolated child sessions using async background workers
- [x] child session records persist `parent_session_id`, `session_kind="subagent"`, and lineage depth
- [x] child run records persist `parent_run_id`
- [x] child tool noise does not auto-pollute parent session history
- [x] parent session receives only one concise terminal system summary per child terminal state
- [x] service/substrate default child profile is restricted and enforced by tests
- [x] product-level constrained inference to `standard` is covered by tests without breaking parent-ceiling limits
- [x] child permissions cannot exceed parent ceiling
- [x] queueing, timeout, cancellation, and service shutdown-drain are all covered by tests
- [x] diagnostics expose task detail and parent/child/run linkage
- [x] focused regression suite passes
- [x] broader touched-surface regression passes
- [x] `STATUS.md` is synchronized with the new reality

## Explicit out-of-scope reminder for implementers

Do **not** treat any of the following as part of this plan unless the user explicitly expands scope:

- sync wait-style orchestration
- nested child spawn
- full parent-context fork
- generic workflow graph semantics
- planner/swarm decomposition
- transcript replay into parent history
