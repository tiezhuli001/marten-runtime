# Session Continuity, Catalog, And Thin Memory Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add restart-safe session continuity first, then explicit session catalog and resume, then opt-in thin user memory, while preserving the thin harness boundary.

**Architecture:** implement the work in three strict stages. Stage 1 adds a SQLite-backed session store and binding restore without changing the runtime center. Stage 2 adds explicit session catalog and resume surfaces on top of the durable store. Stage 3 adds a tiny file-based user memory layer gated by explicit user intent and stable `user_id`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, unittest

---

## Invariants

- keep the runtime center at `channel -> binding -> agent -> runtime context -> LLM -> builtin/MCP/skill -> LLM -> channel`
- Stage 1 is the immediate priority and must land cleanly before Stage 2 or Stage 3 work starts
- preserve `SessionStore` as the in-memory fallback used by focused tests
- preserve current HTTP and Feishu conversation continuity semantics
- preserve replay + compaction as the only prompt-entry path for restored sessions
- do not add session search, embeddings, or semantic retrieval in the current scope
- thin memory stays opt-in and file-based; do not add automatic memory extraction by default
- title/preview generation is a one-shot lightweight summary at session creation, with first-user-message truncation as fallback
- the current Stage 2 target is session list, session show, session new, and session resume

## Chunk 1: Stage 1 Durable Session Continuity

### Task 1: Lock the current session-store contract with targeted tests

**Files:**
- Modify: `tests/test_session.py`
- Create: `tests/test_sqlite_session_store.py`

- [ ] **Step 1: Extend the in-memory contract tests before writing SQLite code**

Add tests that define the shared contract both stores must satisfy:

- create a session and freeze snapshot ids
- append messages and mark runs
- persist compacted context
- persist latest actual usage
- persist recent tool outcome summaries
- create child sessions with lineage fields

- [ ] **Step 2: Add the new SQLite round-trip test module**

Write focused tests for:

- create session, close store, reopen store, get same session
- append history, close store, reopen store, preserve message order
- persist compacted context and usage as structured data
- persist recent tool summaries across reopen
- restore `conversation_id -> session_id` mapping across reopen
- preserve child-session lineage across reopen

- [ ] **Step 3: Run the targeted failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session tests.test_sqlite_session_store
```

Expected:

- `tests.test_session` still passes or shows only failures caused by the new contract additions
- `tests.test_sqlite_session_store` fails because the implementation does not exist yet

### Task 2: Implement `SQLiteSessionStore` with the current mutator contract

**Files:**
- Create: `src/marten_runtime/session/sqlite_store.py`
- Modify: `src/marten_runtime/session/store.py`
- Modify: `src/marten_runtime/session/models.py`
- Modify: `src/marten_runtime/session/compacted_context.py`
- Modify: `src/marten_runtime/session/tool_outcome_summary.py`
- Modify: `src/marten_runtime/runtime/usage_models.py`

- [ ] **Step 1: Add serialization-safe helpers where needed**

Ensure the session-adjacent models can be converted to and from JSON payloads without ad-hoc logic spread across the codebase.

Required outcomes:

- `CompactedContext` round-trips cleanly
- `NormalizedUsage` round-trips cleanly
- `ToolOutcomeSummary` round-trips cleanly
- `SessionMessage` timestamps survive SQLite persistence

- [ ] **Step 2: Implement the SQLite schema and store methods**

Implement `SQLiteSessionStore` with:

- `sessions`
- `session_messages`
- `session_tool_outcome_summaries`
- `session_bindings`

Implementation details:

- store `latest_compacted_context` and `latest_actual_usage` as JSON text fields on `sessions`
- store ordered messages in `session_messages` with monotonically increasing `message_index`
- store bounded tool summaries in `session_tool_outcome_summaries`
- keep `session_bindings` as the active source of truth for `channel_id + conversation_id -> session_id`
- preserve the existing public mutator semantics where practical

- [ ] **Step 3: Preserve the in-memory fallback without widening the abstraction surface**

Keep `SessionStore` usable by tests and small unit surfaces. Do not introduce a large new base class unless the final shape actually needs one.

- [ ] **Step 4: Run the focused store tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session tests.test_sqlite_session_store
```

Expected:

- all session-store contract tests pass

### Task 3: Wire the durable session store into bootstrap and runtime flows

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime_support.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`

- [ ] **Step 1: Extend `build_stateful_stores()` to construct the session store**

Implementation details:

- add `data/sessions.sqlite3`
- return the session store beside automation and self-improve stores
- keep initialization local-first and deterministic

- [ ] **Step 2: Replace direct `SessionStore()` construction in `build_http_runtime()`**

Use the constructed durable store in the runtime state. Keep the rest of runtime ownership unchanged.

- [ ] **Step 3: Make inbound session resolution binding-aware**

Update the session resolution path used by `bootstrap_handlers`:

- first check `session_bindings`
- then fall back to the legacy direct conversation lookup for compatibility
- create a new session only when neither path resolves

- [ ] **Step 4: Keep diagnostics meaningful after restart**

Add or update runtime diagnostics fields so operators can see that session continuity is durable.

Minimum fields:

- session store kind or storage path
- durable session count
- session binding count

- [ ] **Step 5: Replace `app.py`’s direct `_items` length dependency**

`/sessions` currently reaches into `runtime.session_store._items`. Remove that in favor of a public count or explicit helper so the route works for both in-memory and SQLite stores.

- [ ] **Step 6: Run targeted diagnostics and runtime tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_runtime_diagnostics tests.contracts.test_runtime_contracts tests.test_acceptance
```

Expected:

- runtime diagnostics tests pass
- no regression in acceptance coverage that depends on compaction and session state

### Task 4: Add restart-proof integration coverage

**Files:**
- Modify: `tests/test_acceptance.py`
- Create: `tests/test_session_restart_integration.py`
- Modify: `tests/http_app_support.py`

- [ ] **Step 1: Add a repo-backed app helper that preserves `data/` across runtime rebuilds**

This helper should let tests:

- build runtime A
- send messages
- tear it down
- build runtime B against the same repo/data dir
- verify the session still exists

- [ ] **Step 2: Add restart integration tests**

Required scenarios:

- message history survives runtime rebuild
- compacted context survives runtime rebuild
- tool outcome summaries survive runtime rebuild
- diagnostics for a restored session remain meaningful

- [ ] **Step 3: Run the Stage 1 integration proof**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session_restart_integration tests.test_acceptance
```

Expected:

- restart integration tests pass
- existing acceptance compaction paths still pass

## Chunk 2: Stage 2 Session Catalog And Explicit Resume

### Task 5: Extend session metadata for listing and readable switching

**Files:**
- Modify: `src/marten_runtime/session/models.py`
- Modify: `src/marten_runtime/session/store.py`
- Modify: `src/marten_runtime/session/sqlite_store.py`
- Create: `src/marten_runtime/session/title_summary.py`
- Modify: `tests/test_session.py`
- Modify: `tests/test_sqlite_session_store.py`

- [ ] **Step 1: Add metadata fields needed by the catalog**

Add and persist:

- `channel_id`
- `user_id`
- `agent_id`
- `session_title`
- `session_preview`
- `message_count`

- [ ] **Step 2: Implement one-shot lightweight title/preview generation**

Implementation details:

- generate one short topic-style title and one short sentence preview only when a session is first created
- keep the prompt tiny and deterministic in output shape
- use a minimal helper module so the generation logic does not spread into handlers
- if generation fails, degrade to first-user-message truncation
- do not regenerate titles every turn

- [ ] **Step 3: Add metadata persistence tests**

Cover:

- one-shot generation path
- fallback truncation path
- SQLite persistence of title and preview

- [ ] **Step 4: Run the focused metadata tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session tests.test_sqlite_session_store
```

Expected:

- all metadata and fallback tests pass

### Task 6: Add session catalog store methods and diagnostics endpoints

**Files:**
- Modify: `src/marten_runtime/session/store.py`
- Modify: `src/marten_runtime/session/sqlite_store.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Create: `tests/test_session_catalog.py`

- [ ] **Step 1: Add store methods for catalog operations**

Required methods:

- `list_sessions(...)`
- `bind_conversation(...)`
- `resolve_session_for_conversation(...)`

Behavior constraints:

- listing is ordered by `last_event_at` descending
- default listing returns metadata only, not raw transcripts

- [ ] **Step 2: Add operator-facing HTTP endpoints**

Suggested endpoints:

- `GET /diagnostics/sessions`

Keep the existing `/diagnostics/session/{session_id}` endpoint unchanged for full inspection.

- [ ] **Step 3: Add focused catalog tests**

Cover:

- list ordering
- rebinding current conversation to an existing session
- preserving discoverability of previously bound sessions

- [ ] **Step 4: Run the catalog proof**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session_catalog tests.test_http_runtime_diagnostics
```

Expected:

- session catalog tests pass
- runtime diagnostics tests still pass

### Task 7: Add builtin `session` tool support

**Files:**
- Create: `src/marten_runtime/tools/builtins/session_tool.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
- Modify: `src/marten_runtime/runtime/capabilities.py`
- Modify: `config/agents.toml`
- Create: `tests/tools/test_session_tool.py`
- Modify: `tests/contracts/test_runtime_contracts.py`

- [ ] **Step 1: Implement the `session` family tool**

First actions:

- `list`
- `show`
- `new`
- `resume`

Behavior constraints:

- `new` creates a fresh session and binds the current conversation to it
- `resume` rebinds the current conversation to an existing session
- the current running turn keeps its original `session_id`; the new binding applies from the next inbound turn
- `show` returns session metadata and a compact summary, not full raw history by default

- [ ] **Step 2: Register the capability and tool**

Update:

- capability declaration
- tool registration
- default main-agent allowed tools

- [ ] **Step 3: Add tool contract tests**

Cover:

- `session.list`
- `session.show`
- `session.new`
- `session.resume`

- [ ] **Step 4: Run the tool proof**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.tools.test_session_tool tests.contracts.test_runtime_contracts
```

Expected:

- tool tests pass
- runtime capability contract tests still pass

## Chunk 3: Stage 3 Thin File-Based User Memory

### Task 8: Add a tiny file-based memory service

**Files:**
- Create: `src/marten_runtime/memory/service.py`
- Create: `src/marten_runtime/memory/models.py`
- Create: `src/marten_runtime/memory/render.py`
- Create: `tests/test_memory_service.py`

- [ ] **Step 1: Define the tiny memory contract**

Required behaviors:

- resolve memory path from stable `user_id`
- treat missing files as empty memory
- support capped entry rendering for prompt injection
- reject oversized writes

- [ ] **Step 2: Implement file-oriented read/write helpers**

First operations:

- load full memory
- render capped entry text
- append entry
- replace section
- delete section or entry

- [ ] **Step 3: Add memory service tests**

Cover:

- stable user-id path resolution
- empty-memory fallback
- capped rendering
- append/replace/delete
- oversized-write rejection

- [ ] **Step 4: Run the focused memory service proof**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_memory_service
```

Expected:

- memory service tests pass

### Task 9: Add builtin `memory` tool support and runtime gating

**Files:**
- Create: `src/marten_runtime/tools/builtins/memory_tool.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime_support.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_tool_registration.py`
- Modify: `src/marten_runtime/runtime/capabilities.py`
- Modify: `config/agents.toml`
- Create: `tests/tools/test_memory_tool.py`
- Modify: `tests/test_runtime_context.py`

- [ ] **Step 1: Build runtime-owned memory service wiring**

Implementation details:

- initialize the memory service from the repo root
- make memory available only when a stable `user_id` exists
- keep missing files and missing stable user ids as empty-memory cases

- [ ] **Step 2: Add the `memory` family tool**

First actions:

- `get`
- `append`
- `replace`
- `delete`

Behavior constraints:

- writes require explicit user-intent paths
- prompt injection uses only the capped entry text, not full file content

- [ ] **Step 3: Inject tiny memory entry text into runtime context**

Do this with the smallest possible surface:

- pass a pre-rendered tiny memory block into existing runtime context assembly or prompt assembly
- keep full file reads out of the default prompt path

- [ ] **Step 4: Add tool and context tests**

Cover:

- memory tool actions
- no-memory behavior when `user_id` is unstable or missing
- capped memory block injection into runtime context

- [ ] **Step 5: Run the Stage 3 proof**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_memory_service tests.tools.test_memory_tool tests.test_runtime_context
```

Expected:

- all memory tests pass
- runtime context tests still pass

## Chunk 4: Final Verification And Sync

### Task 10: Run milestone regressions in order

**Files:**
- Modify: `STATUS.md`
- Modify: `docs/2026-04-19-session-catalog-and-thin-memory-design.md` when implementation reality requires precise sync
- Modify: `docs/README.md` and `docs/ARCHITECTURE_CHANGELOG.md` only when the implemented slices change entry-path or architecture truth

- [ ] **Step 1: Run the Stage 1 regression set after Stage 1 lands**

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session tests.test_sqlite_session_store tests.test_session_restart_integration tests.test_http_runtime_diagnostics tests.test_acceptance
```

Expected:

- all Stage 1 continuity and diagnostics tests pass

- [ ] **Step 2: Run the Stage 2 regression set after Stage 2 lands**

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session_catalog tests.tools.test_session_tool tests.test_http_runtime_diagnostics tests.contracts.test_runtime_contracts tests.test_acceptance
```

Expected:

- all Stage 2 catalog and tool tests pass

- [ ] **Step 3: Run the Stage 3 regression set after Stage 3 lands**

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_memory_service tests.tools.test_memory_tool tests.test_runtime_context tests.contracts.test_runtime_contracts tests.test_acceptance
```

Expected:

- all Stage 3 memory and runtime regression tests pass

- [ ] **Step 4: Run the strongest practical combined proof at the end**

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_session tests.test_sqlite_session_store tests.test_session_restart_integration tests.test_session_catalog tests.tools.test_session_tool tests.test_memory_service tests.tools.test_memory_tool tests.test_http_runtime_diagnostics tests.test_runtime_context tests.test_acceptance tests.contracts.test_runtime_contracts
```

Expected:

- the combined targeted suite passes cleanly

- [ ] **Step 5: Sync continuity and architecture-facing docs**

Required outcomes:

- `STATUS.md` reflects what landed and what is still pending
- the design doc no longer describes completed work as future work
- `docs/README.md` is updated only if the new docs become part of the recommended reading path
- `docs/ARCHITECTURE_CHANGELOG.md` gains an entry only when implemented slices actually shift the active architecture truth

## Plan Sanity Checks

Before implementation starts, confirm all of the following:

- Stage 1 can land independently and produce restart-safe session continuity
- Stage 2 depends on Stage 1 but does not require Stage 3
- Stage 3 depends on stable `user_id` and remains optional for channels that lack one
- no current task requires embeddings, vector search, distributed coordination, or planner infrastructure
- no current task includes session search of any kind
- no test relies on hidden mutable internals such as `session_store._items`
- title/preview generation stays one-shot and cheap
- restored sessions still use replay + compaction instead of raw full-history prompt injection

## Execution Notes For Coding Agents

- land each stage behind passing tests before starting the next stage
- do not collapse Stage 1, Stage 2, and Stage 3 into one giant patch
- keep public behavior backwards-compatible when no explicit session rebinding or user memory is used
- prefer adding focused helper modules over inflating `bootstrap_handlers.py` or `runtime_diagnostics.py`
- when a new helper is added, keep it narrow and test it directly
