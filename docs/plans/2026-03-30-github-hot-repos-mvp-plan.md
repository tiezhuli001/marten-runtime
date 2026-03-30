# GitHub Hot Repos Digest MVP Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one MVP path where a user can ask the main agent in chat to register a recurring GitHub hot-repos digest at a user-chosen time, and the resulting automation runs as an isolated proactive turn, depends on a configured GitHub MCP server, activates a dedicated skill, and sends one final digest to the configured target channel.

**Architecture:** Keep the platform thin. Reuse the existing `automation/` skeleton as a narrow scheduler bridge, add a chat-to-automation registration path on the main agent, route scheduled runs into the existing `channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel` spine, and keep the repo-discovery and summarization logic inside a dedicated skill. Do not add queue-first execution, generic workflow orchestration, or platform-specific GitHub business logic beyond the minimum automation and delivery wiring.

**Tech Stack:** Python, FastAPI, SQLite, unittest, existing runtime/session/skills/MCP integration

---

## MVP Boundaries

- Hard requirement: a GitHub MCP server must already be configured and discovered by the runtime.
- If GitHub MCP repo-discovery tools are unavailable, this feature is explicitly unsupported and should fail in a controlled way.
- MVP target is **today's** hot repos at a user-configured time, not yesterday's trending snapshot.
- MVP output is one final visible digest with top 10 repos and a short Chinese summary for each item.
- MVP delivery target is explicit in the automation record created from chat.
- MVP does not require full durable session persistence.
- MVP does require:
  - chat-based automation registration
  - automation persistence
  - due-window dispatch
  - dispatch idempotency
  - isolated proactive run wiring
  - target-scoped duplicate suppression

## Success Criteria

- A user can register one daily automation job by chatting with the main agent.
- The automation stores the user-selected schedule and timezone.
- At the configured time in the configured timezone, the job dispatches once for that day.
- The dispatch enters the normal runtime loop as an isolated automation turn.
- The turn explicitly activates a GitHub hot-repos digest skill.
- The skill uses GitHub MCP repo-discovery capability to gather candidates and produce a top-10 digest.
- Feishu receives exactly one final visible reply for a successful run.
- Repeating the same scheduled window does not send duplicates.
- If GitHub MCP is missing or lacks the required repo-discovery tool, the run is marked unsupported without spamming delivery retries.

## File Structure

### Create

- `src/marten_runtime/config/automations_loader.py`
- `src/marten_runtime/automation/clock.py`
- `src/marten_runtime/automation/sqlite_store.py`
- `src/marten_runtime/automation/dispatch.py`
- `src/marten_runtime/automation/history.py`
- `src/marten_runtime/tools/builtins/register_automation_tool.py`
- `skills/github_hot_repos_digest.md`
- `tests/test_automation_store.py`
- `tests/test_automation_dispatch.py`
- `tests/test_github_hot_repos_digest.py`

### Modify

- `src/marten_runtime/automation/models.py`
- `src/marten_runtime/automation/store.py`
- `src/marten_runtime/automation/scheduler.py`
- `src/marten_runtime/interfaces/http/bootstrap.py`
- `src/marten_runtime/interfaces/http/app.py`
- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/skills/service.py`
- `src/marten_runtime/skills/selector.py`
- `src/marten_runtime/tools/registry.py`
- `src/marten_runtime/channels/feishu/delivery.py`
- `docs/CONFIG_SURFACES.md`
- `README.md`
- `README_CN.md`
- `STATUS.md`
- `tests/test_automation.py`
- `tests/test_runtime_loop.py`
- `tests/test_feishu.py`
- `tests/test_contract_compatibility.py`
- `tests/test_skills.py`
- `tests/test_tools.py`

## Chunk 1: GitHub MCP Capability Gate

### Task 1: Prove the runtime can support this feature with the configured GitHub MCP

**Files:**
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `docs/CONFIG_SURFACES.md`

- [ ] **Step 1: Record the hard prerequisite**
  - Document that this feature requires a configured GitHub MCP server and is unsupported otherwise.
- [ ] **Step 2: Define the minimum MCP capability contract**
  - Required: at least one repo-discovery tool that can return repository metadata suitable for ranking and summarization.
  - Preferred: `search_repositories` or equivalent.
- [ ] **Step 3: Document the MVP semantic**
  - Use today's hot repos at a user-configured time.
  - Do not promise an exact reproduction of `github.com/trending` unless the configured MCP server exposes an appropriate capability.
- [ ] **Step 4: Verification**
  - Run: `curl -sS http://127.0.0.1:8014/diagnostics/runtime`
  - Expected:
    - diagnostics show the GitHub MCP server as connected or discovered
    - diagnostics remain compatible with current runtime behavior
- [ ] **Step 5: Verify repo-discovery capability, not just connectivity**
  - Run:
    - one live MCP probe against the configured GitHub server for repo discovery, such as `search_repositories`
  - Expected:
    - the MCP server exposes at least one repo-discovery tool
    - the tool returns repository metadata suitable for ranking and summarization
    - if this fails, the feature is treated as unsupported under the current MCP setup

## Chunk 2: Chat Registration And Automation Persistence

### Task 2: Add MVP automation persistence model and loader support

**Files:**
- Create: `src/marten_runtime/config/automations_loader.py`
- Modify: `src/marten_runtime/automation/models.py`
- Modify: `tests/test_automation.py`

- [ ] **Step 1: Write the failing persistence and loader test**
  - Cover:
    - storing one enabled daily job
    - storing user-selected schedule and timezone
    - storing delivery target and explicit `skill_id`
- [ ] **Step 2: Extend `AutomationJob` with MVP-only fields**
  - `name`
  - `schedule_kind`
  - `schedule_expr`
  - `timezone`
  - `session_target`
  - `delivery_channel`
  - `delivery_target`
  - `skill_id`
  - `prompt_template`
  - `enabled`
- [ ] **Step 3: Keep optional loader support for repo-local bootstrap data**
  - This is for seeded examples and tests only, not the primary user registration path.
- [ ] **Step 4: Wire automation storage into bootstrap without forcing live execution**
- [ ] **Step 5: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_automation -v`
  - Expected:
    - `test_store_reads_enabled_daily_job ... ok`
    - `test_loader_supports_seed_data ... ok`

### Task 3: Add durable automation definition storage and dispatch history

**Files:**
- Create: `src/marten_runtime/automation/sqlite_store.py`
- Create: `src/marten_runtime/automation/history.py`
- Modify: `src/marten_runtime/automation/store.py`
- Modify: `tests/test_automation.py`
- Create: `tests/test_automation_store.py`

- [ ] **Step 1: Write failing tests for persistence across store re-instantiation**
  - Cover:
    - save/load automation definitions
    - persist one dispatched window record
    - duplicate window suppression
- [ ] **Step 2: Implement SQLite-backed automation store**
  - Keep interface narrow:
    - save automation
    - list enabled automations
    - create automation from chat registration payload
    - record dispatched window
    - query existing dispatched window
- [ ] **Step 3: Keep in-memory store as compatibility/simple test path**
- [ ] **Step 4: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_automation tests.test_automation_store -v`
  - Expected:
    - persistence tests pass
    - duplicate dispatch window is reported as already recorded

### Task 4: Let the main agent register recurring jobs from chat

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Create: `src/marten_runtime/tools/builtins/register_automation_tool.py`
- Modify: `src/marten_runtime/tools/registry.py`
- Modify: `tests/test_runtime_loop.py`
- Modify: `tests/test_contract_compatibility.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests for chat-driven automation registration**
  - Cover:
    - user asks for a daily GitHub hot-repos digest
    - main agent invokes one narrow builtin automation-registration tool
    - automation store receives a saved recurring job with user-selected time and target
- [ ] **Step 2: Add one thin registration path via builtin tool**
  - Preferred MVP:
    - a builtin tool such as `register_automation`
  - Constraints:
    - no generic workflow builder
    - no broad automation DSL
    - no separate planner layer
- [ ] **Step 3: Restrict the registration contract**
  - required fields:
    - schedule time
    - timezone
    - target channel
    - target conversation/chat id
    - `skill_id = github_hot_repos_digest`
- [ ] **Step 4: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility tests.test_tools -v`
  - Expected:
    - chat registration creates one recurring automation record
    - malformed registration is rejected cleanly
    - builtin tool registration is visible in the runtime tool surface

## Chunk 3: Due Dispatch Into The Existing Runtime Spine

### Task 5: Convert scheduler tick into a due-window dispatcher

**Files:**
- Create: `src/marten_runtime/automation/clock.py`
- Create: `src/marten_runtime/automation/dispatch.py`
- Modify: `src/marten_runtime/automation/scheduler.py`
- Create: `tests/test_automation_dispatch.py`

- [ ] **Step 1: Write failing tests for due-window evaluation**
  - Cover:
    - no dispatch before the configured time
    - one dispatch at or after the configured time
    - no second dispatch for the same day
- [ ] **Step 2: Implement timezone-aware daily due-window calculation**
- [ ] **Step 3: Emit one internal automation dispatch envelope**
  - include:
    - `automation_id`
    - `scheduled_for`
    - `skill_id`
    - `delivery_channel`
    - `delivery_target`
    - `session_target = isolated`
- [ ] **Step 4: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_automation_dispatch -v`
  - Expected:
    - `test_not_due_before_configured_window ... ok`
    - `test_dispatches_once_for_due_window ... ok`
    - `test_same_day_window_is_idempotent ... ok`

### Task 6: Route automation dispatches through the normal runtime loop

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `tests/test_runtime_loop.py`
- Modify: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Write failing tests for an automation-triggered isolated turn**
  - Cover:
    - synthetic event enters the runtime loop
    - explicit `skill_id` is visible to skill selection
    - delivery target metadata survives to the delivery layer
- [ ] **Step 2: Add one internal automation-trigger entrypoint**
  - Prefer a narrow operator-only path or in-process call
  - Do not create a generic job platform
- [ ] **Step 3: Reuse existing runtime path**
  - avoid new prompt orchestration branch
  - avoid new agent execution engine
- [ ] **Step 4: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_runtime_loop tests.test_contract_compatibility -v`
  - Expected:
    - automation runs complete through the same runtime path as user turns
    - existing HTTP contracts remain green

## Chunk 4: Explicit Skill Activation And Duplicate Suppression

### Task 7: Add the dedicated GitHub hot-repos skill

**Files:**
- Create: `skills/github_hot_repos_digest.md`
- Modify: `src/marten_runtime/skills/service.py`
- Modify: `src/marten_runtime/skills/selector.py`
- Modify: `tests/test_skills.py`
- Create: `tests/test_github_hot_repos_digest.py`

- [ ] **Step 1: Write failing tests for automation-specified skill activation**
  - Cover:
    - skill activates from explicit `skill_id`
    - skill is not activated for unrelated turns
- [ ] **Step 2: Author the skill**
  - Requirements:
    - use GitHub MCP repo-discovery capability
    - if unavailable, return a controlled unsupported result
    - rank and summarize 10 repos
    - produce one final Chinese digest
    - avoid exposing intermediate tool chatter in final output
- [ ] **Step 3: Allow the runtime to pass automation metadata into the skill path**
  - at minimum:
    - report date
    - ranking size
    - delivery channel hint
    - configured schedule context
- [ ] **Step 4: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_skills tests.test_github_hot_repos_digest -v`
  - Expected:
    - explicit activation tests pass
    - unsupported-MCP path is controlled
    - supported path yields one digest payload shape

### Task 8: Add target-scoped duplicate suppression for automation delivery

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Modify: `tests/test_feishu.py`

- [ ] **Step 1: Write failing tests for same-window duplicate delivery suppression**
  - Cover:
    - same automation window + same target does not send twice
    - unrelated user conversations are unaffected
- [ ] **Step 2: Add a minimal lane/dedupe guard**
  - Key on:
    - `delivery_channel`
    - `delivery_target`
    - `scheduled_for`
- [ ] **Step 3: Reuse current single-final-visible-reply semantics**
- [ ] **Step 4: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
  - Expected:
    - automation delivery emits one final visible reply
    - duplicate window delivery is suppressed

## Chunk 5: MVP Operator Surface And Full Verification

### Task 9: Add the smallest useful operator surface

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `docs/CONFIG_SURFACES.md`
- Modify: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Add a manual trigger endpoint for one automation**
  - Goal: enable live debugging without waiting for the configured time.
- [ ] **Step 2: Add a recent-run inspection endpoint**
  - Goal: show whether a day-window was dispatched, succeeded, or was blocked as unsupported.
- [ ] **Step 3: Keep the surface narrow and operator-only**
- [ ] **Step 4: Verification**
  - Run: `PYTHONPATH=src python -m unittest tests.test_contract_compatibility -v`
  - Expected:
    - new endpoints are covered
    - existing contract coverage stays green

### Task 10: Full regression and live-chain debug

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: Run the targeted MVP suite**
  - Run:
    - `PYTHONPATH=src python -m unittest tests.test_automation tests.test_automation_store tests.test_automation_dispatch tests.test_runtime_loop tests.test_skills tests.test_github_hot_repos_digest tests.test_feishu tests.test_contract_compatibility -v`
  - Expected:
    - all targeted MVP tests pass
- [ ] **Step 2: Run the full suite**
  - Run:
    - `PYTHONPATH=src python -m unittest -v`
  - Expected:
    - full suite green with no regressions in the current runtime spine
- [ ] **Step 3: Run live diagnostics**
  - Run:
    - `curl -sS http://127.0.0.1:8014/healthz`
    - `curl -sS http://127.0.0.1:8014/diagnostics/runtime`
  - Expected:
    - service healthy
    - GitHub MCP discovered
    - automation config visible if diagnostics expose it
- [ ] **Step 4: Register one automation by chat**
  - Register one automation by chat with:
    - a user-chosen daily time
    - local timezone
    - `skill_id = github_hot_repos_digest`
    - explicit Feishu delivery target
- [ ] **Step 5: Manually trigger the automation**
  - Run:
    - `curl -sS -X POST http://127.0.0.1:8014/automations/<automation_id>/trigger`
  - Expected:
    - one run record is created
    - one isolated runtime turn starts
- [ ] **Step 6: Trace the end-to-end run**
  - Confirm in logs or diagnostics:
    - automation selected
    - synthetic event created
    - skill activated
    - GitHub MCP tool called
    - final digest assembled
    - final Feishu delivery succeeded
- [ ] **Step 7: Validate user-visible result**
  - Expected:
    - Feishu receives exactly one final digest
    - digest includes 10 repos
    - each repo has a short Chinese summary
    - no intermediate tool chatter is visible
- [ ] **Step 8: Re-trigger the same day-window**
  - Expected:
    - duplicate delivery is suppressed
- [ ] **Step 9: Update `STATUS.md` with latest commands and outcomes**

## First Execution Order

1. Chunk 1 Task 1
2. Chunk 2 Task 2
3. Chunk 2 Task 3
4. Chunk 2 Task 4
5. Chunk 3 Task 5
6. Chunk 3 Task 6
7. Chunk 4 Task 7
8. Chunk 4 Task 8
9. Chunk 5 Task 9
10. Chunk 5 Task 10

## Explicit Non-Goals

- No generic workflow engine
- No planner/swarm feature work
- No queue-first cutover
- No broad multi-channel automation product surface
- No built-in GitHub-specific ranking engine in the platform core
- No promise of exact `github.com/trending` parity unless the configured GitHub MCP can actually provide it
