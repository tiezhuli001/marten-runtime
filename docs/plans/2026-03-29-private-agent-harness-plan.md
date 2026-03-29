# Private Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `marten-runtime` from a thin runnable agent runtime into a simplified openclaw-style private-agent harness, while preserving the project principle of `LLM + agent + MCP + skill` first.

**Architecture:** Keep the HTTP and channel harness thin. Build the intelligence spine first: `channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel`. Only after that spine is green should the work move into persistence and concurrency hardening. Add a focused runtime assembly layer between intake/router and provider calls; delay SQLite cutover until the live intelligence path is already working.

**Tech Stack:** Python, FastAPI, Pydantic, SQLite, unittest

---

## Execution Guardrails

- Do not start with SQLite schema work.
- Do not introduce queue-first execution in this program.
- Do not widen scope into heartbeat, cron, memory promotion, or durable delivery outbox.
- Every chunk must improve either:
  - the live `LLM + agent + MCP + skill` path
  - or the safety of that same path
- If a proposed edit does not help the intelligence spine or its immediate stability, it belongs in a later program.

## File Structure

### Create

- `config/bindings.toml`
- `src/marten_runtime/config/bindings_loader.py`
- `src/marten_runtime/agents/bindings.py`
- `src/marten_runtime/runtime/context.py`
- `src/marten_runtime/runtime/provider_retry.py`
- `src/marten_runtime/runtime/lanes.py`
- `src/marten_runtime/skills/service.py`
- `src/marten_runtime/skills/selector.py`
- `src/marten_runtime/session/store_protocol.py`
- `src/marten_runtime/session/in_memory_store.py`
- `src/marten_runtime/session/sqlite_store.py`
- `src/marten_runtime/session/replay.py`
- `tests/test_bindings.py`
- `tests/test_runtime_context.py`
- `tests/test_provider_retry.py`
- `tests/test_runtime_lanes.py`
- `tests/test_session_sqlite.py`

### Modify

- `src/marten_runtime/interfaces/http/bootstrap.py`
- `src/marten_runtime/interfaces/http/app.py`
- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/llm_client.py`
- `src/marten_runtime/agents/router.py`
- `src/marten_runtime/session/store.py`
- `src/marten_runtime/skills/filter.py`
- `tests/test_router.py`
- `tests/test_session.py`
- `tests/test_skills.py`
- `tests/test_runtime_loop.py`
- `tests/test_feishu.py`
- `tests/test_context_engine.py`
- `tests/test_contract_compatibility.py`
- `tests/test_golden_runtime.py`
- `docs/README.md`
- `STATUS.md`

## Milestone A: Intelligence Spine

### Chunk 1: Gateway Binding And Routing

#### Task 1: Add binding config and loader

**Files:**
- Create: `config/bindings.toml`
- Create: `src/marten_runtime/config/bindings_loader.py`
- Create: `src/marten_runtime/agents/bindings.py`
- Test: `tests/test_bindings.py`

- [ ] **Step 1: Write failing tests for binding match precedence**
- [ ] **Step 2: Implement binding model and TOML loader**
- [ ] **Step 3: Support match scopes for `channel_id`, `conversation_id`, `user_id`, `mention_required`, `agent_id`**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_bindings -v`**
- [ ] **Step 5: Verify expected result: all binding precedence tests pass**

#### Task 2: Teach router to resolve agent from binding rules

**Files:**
- Modify: `src/marten_runtime/agents/router.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `tests/test_router.py`
- Modify: `tests/test_feishu.py`

- [ ] **Step 1: Write failing tests for exact conversation binding, exact user binding, and fallback routing**
- [ ] **Step 2: Inject binding registry into router/bootstrap**
- [ ] **Step 3: Preserve existing `active_agent_id` and explicit requested-agent behavior**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_router tests.test_feishu -v`**
- [ ] **Step 5: Verify expected result: bound conversations route deterministically without regressing Feishu inbound handling**

### Chunk 2: Runtime Context Assembly

#### Task 3: Introduce runtime context assembler

**Files:**
- Create: `src/marten_runtime/runtime/context.py`
- Create: `src/marten_runtime/session/replay.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Create: `tests/test_runtime_context.py`
- Modify: `tests/test_runtime_loop.py`

- [ ] **Step 1: Write failing tests for session replay and working-context assembly**
- [ ] **Step 2: Add a context object that carries system prompt, replayed messages, working context, skill context, and tool snapshot**
- [ ] **Step 3: Update `LLMRequest` and `OpenAIChatLLMClient._build_messages(...)` to consume assembled context**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_runtime_context tests.test_runtime_loop -v`**
- [ ] **Step 5: Verify expected result: normal turns now include prior conversation context without breaking multi-step tool loops**

### Chunk 3: Skills First-Class Integration

#### Task 4: Make skills first-class on the live path

**Files:**
- Create: `src/marten_runtime/skills/service.py`
- Create: `src/marten_runtime/skills/selector.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/skills/filter.py`
- Modify: `tests/test_skills.py`
- Modify: `tests/test_runtime_loop.py`

- [ ] **Step 1: Write failing tests for startup skill snapshot, always-on injection, and turn-level skill activation**
- [ ] **Step 2: Build a skill service that discovers, filters, snapshots, and exposes visible skills**
- [ ] **Step 3: Implement lightweight activation rules using explicit mention, skill id/name, and tags**
- [ ] **Step 4: Update runtime loop to pass active skill bodies into the assembled context**
- [ ] **Step 5: Run `PYTHONPATH=src python -m unittest tests.test_skills tests.test_runtime_loop -v`**
- [ ] **Step 6: Verify expected result: LLM requests see skill heads at startup and activated skill bodies when relevant**

### Chunk 4: Provider Resilience

#### Task 5: Add provider retry/backoff wrapper

**Files:**
- Create: `src/marten_runtime/runtime/provider_retry.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Create: `tests/test_provider_retry.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for timeout retry, retryable transport errors, and normalized final failure**
- [ ] **Step 2: Wrap provider transport with retry classifier and bounded backoff**
- [ ] **Step 3: Keep non-retryable auth/config errors fail-fast**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_provider_retry tests.test_models -v`**
- [ ] **Step 5: Verify expected result: transient provider failures retry successfully, permanent failures surface stable error codes**

### Milestone A Exit Criteria

- [ ] Bound conversations and users route to the correct agent
- [ ] LLM requests include replayed session context
- [ ] LLM requests include visible skills and activated skill bodies
- [ ] Existing MCP tool loop still works
- [ ] Transient provider timeout does not randomly break the main chain

## Milestone B: Runtime Hardening

### Chunk 5: Per-Conversation Serialization

#### Task 6: Add per-conversation lane guard

**Files:**
- Create: `src/marten_runtime/runtime/lanes.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Create: `tests/test_runtime_lanes.py`
- Modify: `tests/test_feishu.py`

- [ ] **Step 1: Write failing tests for same-conversation contention and different-conversation concurrency**
- [ ] **Step 2: Implement in-memory lane manager keyed by `channel_id + conversation_id`**
- [ ] **Step 3: Return deterministic busy behavior for HTTP and safe suppression/logging for Feishu**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_runtime_lanes tests.test_feishu -v`**
- [ ] **Step 5: Verify expected result: duplicate in-flight work for one conversation is prevented without blocking unrelated conversations**

### Chunk 6: Session Durability

#### Task 7: Split session store interface from implementations

**Files:**
- Create: `src/marten_runtime/session/store_protocol.py`
- Create: `src/marten_runtime/session/in_memory_store.py`
- Modify: `src/marten_runtime/session/store.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `tests/test_session.py`

- [ ] **Step 1: Write failing tests that assert store contract compatibility across implementations**
- [ ] **Step 2: Move current in-memory behavior into `in_memory_store.py`**
- [ ] **Step 3: Leave `session/store.py` as compatibility entrypoint or factory**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_session -v`**
- [ ] **Step 5: Verify expected result: existing session tests still pass after interface extraction**

#### Task 8: Add SQLite-backed session persistence

**Files:**
- Create: `src/marten_runtime/session/sqlite_store.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Create: `tests/test_session_sqlite.py`
- Modify: `tests/test_context_engine.py`

- [ ] **Step 1: Write failing tests for create/reload/replay behavior across process-like reloads**
- [ ] **Step 2: Implement SQLite schema for session records and message history**
- [ ] **Step 3: Add bootstrap wiring to choose SQLite-backed store in live runtime**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_session_sqlite tests.test_context_engine -v`**
- [ ] **Step 5: Verify expected result: session state and message history survive store re-instantiation**

### Chunk 7: Integration, Diagnostics, And Docs

#### Task 9: Connect diagnostics and preserve live-chain behavior

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap.py`
- Modify: `tests/test_contract_compatibility.py`
- Modify: `tests/test_golden_runtime.py`

- [ ] **Step 1: Write failing tests for runtime diagnostics showing store type, binding status, and lane state**
- [ ] **Step 2: Add minimal diagnostics fields without leaking secrets or internal-only detail**
- [ ] **Step 3: Re-run live-path compatibility tests**
- [ ] **Step 4: Run `PYTHONPATH=src python -m unittest tests.test_contract_compatibility tests.test_golden_runtime -v`**
- [ ] **Step 5: Verify expected result: diagnostics stay useful while existing HTTP/Feishu contracts remain compatible**

#### Task 10: Full regression sweep and docs sync

**Files:**
- Modify: `docs/README.md`
- Modify: `STATUS.md`

- [ ] **Step 1: Run targeted suite for this program**
- [ ] **Step 2: Run full suite**
- [ ] **Step 3: Update docs/status to reflect new harness baseline**
- [ ] **Step 4: Run:
  `PYTHONPATH=src python -m unittest tests.test_bindings tests.test_session tests.test_session_sqlite tests.test_skills tests.test_runtime_context tests.test_runtime_loop tests.test_runtime_lanes tests.test_provider_retry tests.test_router tests.test_feishu -v`**
- [ ] **Step 5: Run:
  `PYTHONPATH=src python -m unittest -v`**
- [ ] **Step 6: Verify expected result:
  - targeted suite all green
  - full suite green
  - existing live chain regressions do not reappear**

## Expected Test Results

After full implementation, the expected outcomes are:

- `tests.test_bindings`: pass
- `tests.test_router`: pass with real binding precedence
- `tests.test_skills`: pass with startup summaries and activation behavior
- `tests.test_runtime_context`: pass with replayed conversation context
- `tests.test_runtime_loop`: pass with context-aware and skill-aware requests
- `tests.test_provider_retry`: pass with retryable timeout/network behavior
- `tests.test_runtime_lanes`: pass with deterministic single-conversation contention handling
- `tests.test_session_sqlite`: pass with durable reload behavior
- `tests.test_feishu`: pass with routing, hidden progress, card delivery, and no duplicate regression
- full `PYTHONPATH=src python -m unittest -v`: pass

## Implementation Order

1. Chunk 1
2. Chunk 2
3. Chunk 3
4. Chunk 4
5. Chunk 5
6. Chunk 6
7. Chunk 7

Do not reorder these chunks. Milestone A must finish before Milestone B starts.
