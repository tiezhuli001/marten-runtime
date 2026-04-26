# Session Switch Compaction And Replay Policy Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** implement switch-triggered source-session compaction and bounded restore replay so resumed sessions consistently restore through `prompt base + compacted summary + recent 8 user turns + recent 3 tool outcome summaries + thin memory`, with one bounded overlap guard: if a widened replay window re-enters the summarized range for the current request, skip compacted-summary reinjection for that request and rely on the widened raw replay instead.

**Architecture:** keep the existing thin runtime path and SQLite session store. Replace message-count replay with user-turn replay, align compacted-tail semantics to user turns, and route `session.new` / `session.resume` through one narrow transition helper that performs inline best-effort compaction before rebinding. Expose the restore policy through narrow diagnostics instead of adding a new context engine.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, unittest

---

## Source Documents

- Design source of truth:
  - `docs/2026-04-21-session-switch-compaction-and-replay-policy-design.md`
- Plan style references:
  - `docs/2026-04-20-thin-multi-provider-openai-compat-implementation-plan.md`
  - `docs/2026-04-19-session-continuity-catalog-memory-implementation-plan.md`
- Existing implementation entry points:
  - `src/marten_runtime/config/platform_loader.py`
  - `src/marten_runtime/session/replay.py`
  - `src/marten_runtime/runtime/context.py`
  - `src/marten_runtime/runtime/loop.py`
  - `src/marten_runtime/session/compacted_context.py`
  - `src/marten_runtime/session/compaction_runner.py`
  - `src/marten_runtime/tools/builtins/session_tool.py`
  - `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - `src/marten_runtime/tools/builtins/runtime_tool.py`
  - `src/marten_runtime/interfaces/http/runtime_diagnostics.py`

## Locked Invariants

- keep the runtime center at `channel -> binding -> runtime context -> LLM -> builtin/MCP/skill -> LLM -> channel`
- keep SQLite as the session backend in this slice
- keep restore bounded and deterministic; do not inject raw full-history prompt state
- default restore shape is fixed to:
  - prompt base
  - compacted summary
  - recent `8` user turns
  - recent `3` tool outcome summaries
  - thin memory
- when a wider replay window overlaps the summarized prefix for the current request:
  - prefer widened raw replay
  - skip compacted-summary reinjection for that request
  - avoid summary/raw duplication in the live prompt
- replay policy has exactly one new operator knob:
  - `runtime.session_replay_user_turns`
  - `SESSION_REPLAY_USER_TURNS`
- carry replay policy through the current runtime path as one integer
- do not add a standalone replay-policy service, manager, or dataclass in this slice
- switch-triggered compaction runs inline and best-effort on:
  - `session.new`
  - `session.resume`
- switch-triggered compaction never blocks the switch result
- source session is compacted; target session is created or rebound
- tool transcript policy stays thin:
  - same-turn followup may use raw tool result
  - cross-turn restore uses `ToolOutcomeSummary`
- this slice excludes:
  - file-based session storage
  - background compaction workers
  - subagent-owned archival flow
  - pluggable context-engine expansion
  - replaying whole historical transcripts into the live prompt

## File / Module Map

- `src/marten_runtime/config/platform_loader.py`
  - add the runtime replay-turn config field and env override
- `config/platform.example.toml`
  - document the default replay-turn knob
- `src/marten_runtime/session/replay.py`
  - own the user-turn replay selector and replay-window helpers
- `src/marten_runtime/runtime/context.py`
  - assemble context with user-turn replay and compact-summary reuse
  - disable compact-summary reinjection on requests where widened replay overlaps the summarized prefix
- `src/marten_runtime/runtime/loop.py`
  - pass the replay policy into context assembly and proactive compaction
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - resolve the configured replay policy at turn entry and pass it into the runtime loop
- `src/marten_runtime/session/compacted_context.py`
  - move compacted-tail semantics from message count to user-turn count with legacy compatibility
- `src/marten_runtime/session/compaction_runner.py`
  - compact prefixes by user turns, exclude the current switch request, and preserve the same tail width as replay
- `src/marten_runtime/session/transition.py`
  - new narrow helper for switch-intent orchestration and source-session compaction
- `src/marten_runtime/tools/builtins/session_tool.py`
  - keep the builtin thin and delegate new/resume work to the transition helper
- `src/marten_runtime/tools/builtins/runtime_tool.py`
  - expose replay policy and compact-summary reuse in `runtime.context_status`
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - hold a narrow in-process snapshot of the latest session-transition compaction result for diagnostics
- `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
  - pass narrow transition-recording callbacks into the session builtin when needed
- `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
  - expose runtime replay policy, latest switch-compaction result, and compacted-session visibility
- `docs/CONFIG_SURFACES.md`
  - document the new replay-turn config surface
- `tests/test_platform.py`
  - lock config defaults and env override behavior
- `tests/test_runtime_context.py`
  - lock the replay contract and compact-summary restore behavior
- `tests/test_context_governance.py`
  - guard bounded restore behavior
- `tests/test_compaction_runner.py`
  - lock turn-based compaction and current-message exclusion
- `tests/tools/test_session_tool.py`
  - lock builtin switch semantics and non-blocking compaction behavior
- `tests/test_gateway.py`
  - lock exclusive rebinding and next-turn routing behavior
- `tests/test_acceptance.py`
  - lock end-to-end restore behavior after `session.new` and `session.resume`
- `tests/test_session_restart_integration.py`
  - lock restart-safe restore with compacted artifacts
- `tests/test_http_runtime_diagnostics.py`
  - lock runtime diagnostics additions
- `tests/tools/test_runtime_and_skill_tools.py`
  - lock `runtime.context_status` visibility for replay and checkpoint state

## Delivery Order

Implement in five strict chunks:

1. replay policy config and user-turn replay foundation
2. compacted-context contract and turn-based compaction
3. session transition helper and switch-path integration
4. diagnostics and `runtime.context_status` visibility
5. integration regressions, doc sync, and final anti-drift verification

Do not start a later chunk until the current chunk passes its chunk verification and still matches the design doc.

## Chunk 1: Replay Policy Foundation

### Task 1: Add the runtime replay-turn config surface

**Files:**
- Modify: `src/marten_runtime/config/platform_loader.py`
- Modify: `config/platform.example.toml`
- Modify: `tests/test_platform.py`

**Constraints:**
- default must be `8`
- the field belongs under `runtime`, not `server`
- env override name must be `SESSION_REPLAY_USER_TURNS`
- the new field must be validated as a positive integer
- do not introduce a second replay knob for tool summaries or compacted tails

- [ ] **Step 1: Write failing config tests**

Lock:

- default platform config yields `runtime.session_replay_user_turns == 8`
- explicit TOML value overrides the default
- `SESSION_REPLAY_USER_TURNS` overrides TOML
- zero or negative values fail validation

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_platform
```

Expected:

- new assertions fail because the field does not exist yet

- [ ] **Step 3: Implement the config field**

Required shape:

```python
class RuntimeConfig(BaseModel):
    mode: str
    session_replay_user_turns: int = 8
```

Required behavior:

- default to `8`
- read TOML `[runtime].session_replay_user_turns`
- apply env override after file load
- validate `> 0`

- [ ] **Step 4: Document the example config**

`config/platform.example.toml` must include:

```toml
[runtime]
mode = "rewrite-first"
session_replay_user_turns = 8
```

- [ ] **Step 5: Re-run config tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_platform
```

**Done means:**

- one narrow replay-turn knob exists
- default is `8`
- invalid values are rejected early

### Task 2: Replace message-count replay with user-turn replay

**Files:**
- Modify: `src/marten_runtime/session/replay.py`
- Modify: `src/marten_runtime/runtime/context.py`
- Modify: `tests/test_runtime_context.py`
- Modify: `tests/test_context_governance.py`

**Constraints:**
- replay budget counts user turns, not message count
- selected replay must include assistant replies that belong to selected user turns
- the current inbound user message must be excluded when it is already appended
- noisy-assistant trimming remains a guardrail and cannot become the primary replay budget
- replay stays bounded to replayable `user` and `assistant` messages

- [ ] **Step 1: Write failing replay tests**

Lock:

- recent `N` user turns are selected even when assistant messages are verbose
- assistant replies that belong to those turns remain in replay
- current inbound user message is excluded
- replay with a compacted summary still uses the recent user-turn tail
- bounded replay does not rehydrate the compacted prefix into the live prompt

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_runtime_context tests.test_context_governance
```

Expected:

- assertions that still assume `replay_limit` in message units fail

- [ ] **Step 3: Implement turn-based replay selection**

Implementation notes:

- add a helper that walks backward across replayable history
- count only `user` messages as turn boundaries
- once `N` user turns are selected, slice forward from the earliest included user message
- include assistant replies inside that selected window
- preserve the existing noisy-assistant suppression only as a secondary trim guard

Recommended surface:

```python
def replay_session_messages(
    messages: list[SessionMessage],
    *,
    current_message: str | None = None,
    user_turns: int = 8,
) -> list[SessionMessage]:
    ...
```

- [ ] **Step 4: Update runtime-context assembly**

Required changes:

- rename `replay_limit` to `replay_user_turns`
- when compacted context exists, use:
  - `max(replay_user_turns, compacted_context.preserved_tail_user_turns_or_default(...))`
- keep tool-summary injection and working-context derivation on the replay source only
- when widening replay reaches back into the summarized prefix, skip compacted-summary reinjection for that request so the same turns are not present in both summary and raw replay

- [ ] **Step 5: Re-run the focused replay tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_runtime_context tests.test_context_governance
```

**Done means:**

- replay semantics are user-turn-based everywhere in context assembly
- the public code surface no longer implies message-count replay
- restore remains bounded and deterministic

### Task 3: Wire the configured replay policy into runtime execution

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `tests/runtime_loop/test_context_status_and_usage.py`

**Constraints:**
- the configured replay-turn value must flow from platform config to both:
  - runtime context assembly
  - proactive compaction tail preservation
- keep this as thin plumbing through existing call sites
- do not introduce a new replay-policy object layer unless the implementation grows beyond one integer in this same slice
- do not add global mutable state for replay configuration
- preserve the current `recent_tool_outcome_summaries(limit=3)` behavior

- [ ] **Step 1: Write failing runtime-loop coverage**

Lock:

- `RuntimeLoop.run(...)` receives the configured replay-turn budget
- both `assemble_runtime_context(...)` calls use the same budget
- proactive compaction uses the same tail width

- [ ] **Step 2: Thread the config through the runtime turn path**

Required call-site changes:

- `bootstrap_handlers._run_turn(...)` resolves:
  - `state.platform_config.runtime.session_replay_user_turns`
- `RuntimeLoop.run(...)` accepts `session_replay_user_turns`
- both initial and post-reactive-compaction context assembly paths use that value

- [ ] **Step 3: Re-run the runtime-loop tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.runtime_loop.test_context_status_and_usage
```

**Done means:**

- runtime turns use one consistent replay policy
- replay budget and compacted-tail budget are aligned at call sites

## Chunk 2: Compacted Context Contract

### Task 4: Move compacted-tail semantics to user-turn units

**Files:**
- Modify: `src/marten_runtime/session/compacted_context.py`
- Modify: `tests/test_session.py`
- Modify: `tests/test_sqlite_session_store.py`
- Modify: `tests/test_runtime_context.py`

**Constraints:**
- canonical field name becomes `preserved_tail_user_turns`
- persisted legacy artifacts with `preserved_tail_count` must still load
- absence of the new field must fall back to the runtime default replay policy
- no migration step is required for existing SQLite rows in this slice

- [ ] **Step 1: Write failing contract tests**

Lock:

- a new compacted context serializes `preserved_tail_user_turns`
- a legacy payload with `preserved_tail_count` still loads
- runtime context falls back to the replay default when the field is absent

- [ ] **Step 2: Implement the compatibility contract**

Required behavior:

- accept legacy input on load
- emit the new field on dump
- keep `source_message_range`, `created_at`, `next_step`, `open_todos`, and `pending_risks`
- add one helper for “resolved preserved tail turns” so call sites stay thin

- [ ] **Step 3: Re-run compacted-context contract tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session tests.test_sqlite_session_store tests.test_runtime_context
```

**Done means:**

- compacted artifacts express tail width in user turns
- stored legacy artifacts still deserialize cleanly

### Task 5: Rewrite compaction prefix selection to use user turns

**Files:**
- Modify: `src/marten_runtime/session/compaction_runner.py`
- Modify: `tests/test_compaction_runner.py`

**Constraints:**
- compactable prefix selection must exclude the current switch request when already appended
- compaction eligibility and prefix slicing operate on replayable `user` and `assistant` messages only
- preserved tail width must equal the runtime replay budget unless the caller overrides it explicitly
- do not compact when replayable user turns are `<= replay_user_turns`

- [ ] **Step 1: Write failing compaction-runner tests**

Lock:

- compacting a history with more than `8` user turns preserves the most recent `8` user turns
- source prefix end index aligns with the selected prefix length
- the current inbound switch request is excluded from the compacted prefix
- compaction returns `None` when there is no prefix worth summarizing

- [ ] **Step 2: Implement user-turn prefix slicing**

Required helper behavior:

- walk replayable messages backward
- hold the last `N` user turns as the preserved tail
- return `(prefix, tail)` using message indices so `source_message_range` remains correct

Recommended helper surface:

```python
def build_compactable_prefix(
    session_messages: list[SessionMessage] | None,
    *,
    current_message: str,
    preserved_tail_user_turns: int = 8,
) -> tuple[list[SessionMessage], list[SessionMessage], int]:
    ...
```

The third value is the compacted prefix end index in full `session_messages` coordinates. Do not use replayable-only coordinates here because `assemble_runtime_context(...)` slices the full session history.

- [ ] **Step 3: Update `run_compaction(...)`**

Required behavior:

- accept `preserved_tail_user_turns`
- persist `source_message_range` that matches the actual compacted prefix
- emit `CompactedContext.preserved_tail_user_turns`

- [ ] **Step 4: Re-run compaction tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_compaction_runner tests.test_runtime_context
```

**Done means:**

- compaction boundaries use the same mental model as restore replay
- compacted summary reuse and preserved tail stay aligned

## Chunk 3: Session Transition Helper And Switch Integration

### Task 6: Add a narrow session transition helper

**Files:**
- Create: `src/marten_runtime/session/transition.py`
- Create: `tests/test_session_transition.py`

**Constraints:**
- helper owns only switch orchestration:
  - eligibility
  - best-effort compaction
  - create or bind mutation
- helper must not become a new generic workflow service
- compaction failure must be reported as metadata, not raised as a switch failure
- source and target session equality must skip compaction

- [ ] **Step 1: Write failing transition tests**

Lock:

- `session.new` compacts the source session when eligible
- `session.resume` compacts the source session when eligible
- a compaction error leaves the old compacted artifact untouched
- no compaction runs when:
  - source and target are the same session
  - source session has `<= replay_user_turns` replayable user turns
  - source session has no new compactable prefix beyond the latest artifact

- [ ] **Step 2: Implement the transition helper**

Recommended surface:

```python
def execute_session_transition(
    *,
    action: Literal["new", "resume"],
    session_store: SessionStore,
    source_session_id: str,
    channel_id: str,
    conversation_id: str,
    current_user_id: str,
    current_message: str,
    llm: LLMClient | None,
    replay_user_turns: int,
    target_session_id: str | None = None,
) -> SessionTransitionResult:
    ...
```

Recommended result shape:

- `session`
- `compaction_attempted`
- `compaction_succeeded`
- `compaction_reason`

Keep it internal. The builtin may choose to omit most of that detail from the user-facing payload.

- [ ] **Step 3: Implement staleness evaluation**

Required rule:

- if no `latest_compacted_context` exists, source is eligible
- if `latest_compacted_context.source_message_range[1]` is older than the current compactable prefix end, source is eligible
- otherwise skip

- [ ] **Step 4: Re-run the transition tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session_transition
```

**Done means:**

- switch orchestration exists in one thin helper
- compaction eligibility is explicit, local, and test-locked

### Task 7: Route `session.new` and `session.resume` through the helper

**Files:**
- Modify: `src/marten_runtime/tools/builtins/session_tool.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
- Modify: `tests/tools/test_session_tool.py`
- Modify: `tests/test_gateway.py`
- Modify: `tests/test_acceptance.py`

**Constraints:**
- `run_session_tool(...)` stays small
- `session.list` and `session.show` stay read-only and never trigger compaction
- `session.new` preserves the current active agent on the created session
- `session.resume` keeps exclusive rebinding semantics across conversations
- tool-context enrichment belongs in `runtime.loop` and builtin registration, not in `bootstrap_handlers.py`
- tool context must provide the transition helper with:
  - `channel_id`
  - `conversation_id`
  - `session_id`
  - `user_id`
  - current inbound user message text
  - resolved LLM client
  - replay-turn budget

- [ ] **Step 1: Write failing switch-path tests**

Lock:

- current active agent survives `session.new` and the next inbound turn stays on that agent
- `session.resume` detaches the old conversation from the target session
- switch success still returns when compaction generation fails
- `session.show` can report compact-summary availability after switch-away compaction

- [ ] **Step 2: Pass switch-specific tool context**

Required changes:

- in the tool resolution path, include:
  - `message`
  - `llm_client`
  - `session_replay_user_turns`
- keep the context narrow; do not pass the whole runtime state

- [ ] **Step 3: Replace inline create/bind logic in `session_tool.py`**

Required behavior:

- `new` and `resume` delegate to `execute_session_transition(...)`
- `list` and `show` keep their current direct path
- payload shape remains backward-compatible for existing callers

- [ ] **Step 4: Re-run switch-path tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.tools.test_session_tool \
  tests.test_gateway.GatewayTests.test_http_session_resume_detaches_old_conversation_from_target_session \
  tests.test_acceptance.AcceptanceTests.test_http_session_new_keeps_next_turn_routed_to_current_active_agent
```

**Done means:**

- the builtin path stays thin
- switch-triggered compaction is integrated without widening the harness
- next-turn routing and resume rebinding remain correct

## Chunk 4: Diagnostics And Restore Visibility

### Task 8: Expose replay policy and compact-summary reuse in runtime diagnostics

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `tests/test_http_runtime_diagnostics.py`

**Constraints:**
- diagnostics must expose replay policy and compact-summary state
- diagnostics should expose the latest in-process switch-compaction result when one exists
- absence of a latest switch-compaction snapshot after cold start is acceptable
- runtime diagnostics remain process-scoped
- per-session “using compact summary” state belongs in session diagnostics and `runtime.context_status`
- diagnostics must not expose secrets or raw tool payloads
- the new fields must be additive

- [ ] **Step 1: Write failing diagnostics tests**

Lock:

- runtime diagnostics include `session_replay_user_turns`
- runtime diagnostics include a stable restore contract summary:
  - replay user turns
  - tool summary limit `3`
- after one `session.new` or `session.resume`, runtime diagnostics include the latest switch-compaction outcome:
  - `action`
  - `source_session_id`
  - `target_session_id`
  - `compaction_attempted`
  - `compaction_succeeded`
- diagnostics remain free of secret values

- [ ] **Step 2: Implement the runtime-diagnostics additions**

Required fields:

- under `sessions` or `runtime`:
  - `session_replay_user_turns`
  - `recent_tool_outcome_summary_limit`
- under a narrow `latest_session_transition` block when present:
  - `action`
  - `source_session_id`
  - `target_session_id`
  - `compaction_attempted`
  - `compaction_succeeded`
  - `compaction_reason`
- keep provider and server diagnostics unchanged

- [ ] **Step 3: Re-run diagnostics tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_runtime_diagnostics
```

**Done means:**

- operators can inspect the active replay budget from runtime diagnostics

### Task 9: Tighten `runtime.context_status` and session surfaces

**Files:**
- Modify: `src/marten_runtime/tools/builtins/runtime_tool.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
- Modify: `src/marten_runtime/tools/builtins/session_tool.py`
- Modify: `tests/tools/test_runtime_and_skill_tools.py`
- Modify: `tests/test_session_catalog.py`

**Constraints:**
- `runtime.context_status` should explain session-level restore policy, not imply raw full-history replay
- tool output stays concise and operational
- session list remains lightweight; richer compact metadata belongs in `session.show` and diagnostics
- do not add raw transcript excerpts to runtime or session tool output

- [ ] **Step 1: Write failing surface tests**

Lock:

- `runtime.context_status` returns:
  - replay user-turn budget
  - latest checkpoint availability
  - whether the session is currently restoring through compact-summary reuse
- `session.show` returns compact-summary metadata:
  - `has_compacted_context`
  - `compacted_at`
  - `compacted_prefix_end`
  - `preserved_tail_user_turns`

- [ ] **Step 2: Pass the replay budget and current compacted context into runtime-tool context**

Required additions to tool context:

- `session_replay_user_turns`
- `compacted_context`

- [ ] **Step 3: Implement concise status output**

Required result fields in `runtime.context_status`:

- `replay_user_turns`
- `recent_tool_outcome_summary_limit`
- `latest_checkpoint`
- `compaction_status`
- `using_compacted_context`

Keep the human-readable `summary` short and factual.

- [ ] **Step 4: Implement richer `session.show` compact metadata**

Required behavior:

- list path keeps the existing compact payload shape
- show path adds metadata fields without dumping raw history

- [ ] **Step 5: Re-run surface tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.tools.test_runtime_and_skill_tools \
  tests.test_session_catalog
```

**Done means:**

- runtime and session surfaces expose the restore policy clearly
- restored-session behavior is observable without widening the runtime path

## Chunk 5: Integration, Doc Sync, And Final Verification

### Task 10: Add restart and switch integration regressions

**Files:**
- Modify: `tests/test_acceptance.py`
- Modify: `tests/test_session_restart_integration.py`
- Modify: `tests/runtime_loop/test_context_status_and_usage.py`

**Constraints:**
- end-to-end tests must prove the restore contract, not only unit helpers
- restart tests must continue using SQLite-backed repo fixtures
- tool-summary replay budget remains fixed at `3`

- [ ] **Step 1: Add failing end-to-end tests**

Lock:

- after `session.new`, switching away from a long session produces a compacted artifact on the source session
- after `session.resume`, the next turn restores through:
  - compact summary
  - recent `8` user turns
  - recent `3` tool outcome summaries
- restart preserves the compacted artifact and replay behavior
- current-message switch requests are excluded from the compacted source prefix

- [ ] **Step 2: Run the focused failing integration tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_acceptance \
  tests.test_session_restart_integration \
  tests.runtime_loop.test_context_status_and_usage
```

Expected:

- new integration assertions fail before the implementation is complete

- [ ] **Step 3: Implement any missing wiring revealed by integration**

Possible final touch points:

- `runtime_loop.run(...)` reactive compaction branch
- session diagnostics payload shape
- context-status summary wording

Keep changes local. Do not introduce a sixth subsystem just to satisfy a test.

- [ ] **Step 4: Re-run the integration proof**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_acceptance \
  tests.test_gateway \
  tests.test_session_restart_integration \
  tests.test_http_runtime_diagnostics \
  tests.test_platform \
  tests.test_session \
  tests.test_sqlite_session_store \
  tests.test_session_transition \
  tests.test_session_catalog \
  tests.tools.test_session_tool \
  tests.tools.test_runtime_and_skill_tools \
  tests.test_runtime_context \
  tests.test_context_governance \
  tests.test_compaction_runner \
  tests.runtime_loop.test_context_status_and_usage
```

**Done means:**

- unit, surface, and restart regressions all pass
- switch-triggered compaction and restore replay are proven end to end

### Task 11: Sync config docs and perform anti-drift review

**Files:**
- Modify: `docs/CONFIG_SURFACES.md`
- Optional if wording drifts: `README.md`
- Optional if wording drifts: `README_CN.md`

**Constraints:**
- document only the new replay-turn surface and restore contract
- keep the docs aligned with the design doc
- do not document file-storage or context-engine features that are still out of scope

- [ ] **Step 1: Update config-surface docs**

Document:

- `runtime.session_replay_user_turns`
- `SESSION_REPLAY_USER_TURNS`
- fixed restore contract:
  - compacted summary
  - recent `8` user turns
  - recent `3` tool outcome summaries
  - thin memory

- [ ] **Step 2: Run the doc drift checks**

Run:

```bash
git diff --check -- \
  docs/2026-04-21-session-switch-compaction-and-replay-policy-implementation-plan.md \
  docs/CONFIG_SURFACES.md
```

- [ ] **Step 3: Perform final design-vs-implementation review**

Checklist:

- does the code still restore with recent `8` user turns by default
- does switch-triggered compaction run only on `session.new` and `session.resume`
- does compaction stay inline and best-effort
- does the session backend remain SQLite
- does the replay policy still have one knob only
- do runtime and session surfaces expose the state without replaying raw history

**Done means:**

- code, docs, and design agree on the restore contract
- the implementation stays on the thin-harness path

## Final Done Criteria

The slice is complete when all of the following are true:

- `runtime.session_replay_user_turns` exists, defaults to `8`, and supports `SESSION_REPLAY_USER_TURNS`
- runtime context assembly replays recent user turns, not recent message count
- `CompactedContext` uses `preserved_tail_user_turns` and still loads legacy rows
- `run_compaction(...)` and switch-triggered compaction preserve the same tail width as replay
- `session.new` and `session.resume` compact the source session when eligible and keep working when compaction fails
- resumed-session restore uses:
  - prompt base
  - compacted summary
  - recent `8` user turns
  - recent `3` tool outcome summaries
  - thin memory
- runtime diagnostics and `runtime.context_status` expose the replay budget and checkpoint state
- restart integration confirms persisted compacted artifacts still restore correctly
- config docs reflect the new surface and do not promise any excluded feature

## Explicit Non-Goals

- switching session storage from SQLite to filesystem
- replaying the full transcript into the model prompt
- adding job queues, background workers, or subagent compaction flows
- introducing semantic retrieval, embeddings, or context-engine plugins
- widening tool-summary replay beyond the fixed recent `3` summaries
