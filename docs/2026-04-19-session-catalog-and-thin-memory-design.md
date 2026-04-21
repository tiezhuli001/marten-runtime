# Session Catalog And Thin Memory Design

Date: 2026-04-19  
Status: Draft for review  
Scope: design only; implementation stays for the next stage after design review

## Goal

Add one narrow continuity layer to `marten-runtime` that keeps the harness thin:

- durable local session persistence across restart
- explicit session listing and resume for channel-driven conversations
- opt-in thin user memory for stable preferences and stable facts

The design keeps the runtime center where it already is:

`channel -> binding -> agent -> runtime context -> LLM -> builtin tool / MCP / skill -> LLM -> channel`

The implementation priority stays aligned with the current handoff:

- first complete the minimal durable session persistence slice
- then add explicit session catalog and resume surfaces
- then add opt-in thin memory as a separate follow-up slice

## Design Outcome

This design targets three concrete outcomes:

1. A conversation session survives process restart, crash, and deployment switch when the local `data/` directory survives.
2. Users and operators can explicitly inspect, start, and resume sessions without turning the runtime into a workflow platform.
3. The runtime can carry a very small amount of long-lived user memory when the user explicitly asks to save it.

## Current Repository Baseline

The repository already has most of the short-term continuity model in place.

### Existing strengths

1. The runtime already has a real session model.
   - `SessionRecord` already stores `session_id`, `conversation_id`, `history`, `latest_compacted_context`, `latest_actual_usage`, `recent_tool_outcome_summaries`, and lineage fields.
   - `SessionStore` already owns session mutation semantics and `conversation_id -> session_id` lookup.

2. Runtime context assembly already limits prompt weight.
   - `assemble_runtime_context()` already uses replay trimming, compaction reuse, and tool-outcome summaries.
   - the current architecture already separates stored history from prompt-injected history.

3. The runtime already exposes a natural channel/session seam.
   - ingress already carries `channel_id`, `conversation_id`, `user_id`, and `requested_agent_id`.
   - same-conversation FIFO lanes already serialize by `channel_id + conversation_id`.

4. The repository already uses narrow SQLite-backed stores elsewhere.
   - `SQLiteAutomationStore`
   - `SQLiteSelfImproveStore`

### Current gaps

1. `SessionStore` is still in-memory only.
2. Restart loses the `conversation_id -> session_id` mapping and all session continuity state.
3. There is no explicit session catalog or resume surface for end users.
4. There is no thin long-term memory mechanism for user-confirmed stable preferences or facts.

## Constraints

- preserve the thin harness boundary from ADR 0001
- keep the runtime center in the same place
- keep the first implementation slice focused on durable session continuity
- avoid queue-first execution, worker systems, planner layers, or a general memory platform
- keep prompt growth bounded and explicit
- keep storage local and simple
- preserve the in-memory session store option for tests and local fallback

## Product Position

This design introduces three layers with different responsibilities.

These layers are intentionally staged, not bundled into one required first patch:

- Stage 1: session continuity layer
- Stage 2: session catalog layer
- Stage 3: thin memory layer

### 1. Session continuity layer

This is thread-scoped short-term continuity.

Responsibilities:

- persist session identity and conversation mapping
- persist replay-critical history and compacted continuity state
- restore sessions after restart
- keep the existing replay + compaction path as the prompt entry

### 2. Session catalog layer

This is the explicit discovery and switching surface.

Responsibilities:

- list recent sessions
- inspect a session summary
- create a new session explicitly
- resume an old session explicitly from the current channel conversation

### 3. Thin memory layer

This is user-scoped long-term memory.

Responsibilities:

- store only stable preferences and stable facts
- write only on explicit user request or explicit user-confirmed edit
- keep startup injection tiny
- expose manual read and edit surfaces

## Approaches Considered

### Approach A — SQLite session store + builtin session catalog + file-based thin memory

Use SQLite for durable session state and session catalog metadata. Use a small file-based user memory entrypoint under `data/memory/`.

Why this fits best:

- reuses established repository persistence patterns
- keeps session continuity on the existing active runtime path
- keeps session switching explicit and operator-visible
- keeps long-term memory legible, editable, and low-risk
- avoids early investment in embeddings or a general memory service

### Approach B — file-based sessions and file-based memory

Store sessions as JSON or markdown files.

Trade-offs:

- easy to inspect locally
- weaker query surface for listing and binding metadata
- more brittle for ordered message persistence and partial updates
- inconsistent with current repository SQLite store patterns

### Approach C — unified SQLite memory platform with semantic retrieval

Store sessions and long-term memory in one richer retrieval subsystem.

Trade-offs:

- stronger future retrieval surface
- wider control surface than the current repository needs
- pushes the project toward a memory platform before session durability is complete

### Recommendation

Use **Approach A**.

It produces the highest operator value with the smallest change surface and fits the repository's current architecture.

The implementation order matters:

- durable session persistence is the immediate next architectural slice
- session catalog is the first operator/user extension on top of that slice
- thin memory is a follow-up capability after the session surface is stable

## Proposed Architecture

## 1. Durable Session Store

Add a `SQLiteSessionStore` beside the current in-memory `SessionStore`.

Suggested path:

- `src/marten_runtime/session/sqlite_store.py`

Suggested construction pattern:

- keep `SessionStore` as the current in-memory implementation
- introduce `SQLiteSessionStore` with the same mutator semantics where practical
- extend `build_stateful_stores()` to build the session store
- wire `build_http_runtime()` to use the constructed store
- preserve current diagnostics and runtime-loop ownership

Suggested file location:

- `data/sessions.sqlite3`

### Persisted session data

Persist these session-level fields:

- `session_id`
- `conversation_id`
- `active_agent_id`
- `parent_session_id`
- `session_kind`
- `lineage_depth`
- `state`
- `config_snapshot_id`
- `bootstrap_manifest_id`
- `context_snapshot_id`
- `last_run_id`
- `last_event_at`
- `last_compacted_at`
- `tool_call_count`
- `created_at`
- `updated_at`

Persist these replay-critical structures:

- ordered `SessionMessage` history
- `latest_compacted_context`
- `latest_actual_usage`
- `recent_tool_outcome_summaries`

The first durable slice should also restore enough metadata to keep diagnostics meaningful after restart.

### Prompt-weight rule

Persisting a session does not mean loading the full session into every prompt.

The runtime keeps the current prompt assembly rule:

- reuse `latest_compacted_context` when available
- replay only the recent tail needed by `replay_limit`
- reuse `recent_tool_outcome_summaries`
- keep the durable raw history as restoration material, not as default prompt payload

### Retention and bounded history

To keep the session store useful without turning it into a raw transcript warehouse, the first implementation should enforce conservative bounds:

- retain ordered history needed for replay integrity
- keep prompt assembly bounded by existing replay and compaction
- add config-backed soft limits for raw history count and raw history bytes
- prefer compaction reuse over unbounded transcript replay

The durable session slice exists to preserve continuity, not to promote every historical token into the live prompt.

## 2. Session Catalog

Add one explicit session catalog surface. The session catalog is a discovery and switching layer, not autonomous memory.

This is a follow-up slice after durable session persistence lands.

Recommended exposure:

- diagnostics/operator HTTP endpoints for direct inspection
- one builtin family tool for user-visible actions

Suggested builtin family name:

- `session`

Suggested first actions:

- `session.list`
- `session.show`
- `session.new`
- `session.resume`

### Session identity model

Keep two identities distinct:

1. Channel conversation identity
   - the native thread/chat identity from the channel layer
   - examples: HTTP `conversation_id`, Feishu chat/thread id

2. Runtime session identity
   - the durable `session_id`
   - owns replay history, compacted context, and continuity state

3. Active binding identity
   - the current mapping from `channel_id + conversation_id` to `session_id`
   - changes when `session.new` or `session.resume` is called

### Default continuity rule

Default continuity should stay channel-native:

- one `channel_id + conversation_id` continues one active runtime session by default
- same-conversation FIFO lanes continue to serialize on the channel conversation key

### Explicit switching rule

Session switching should be explicit and tool-driven:

- `session.new` creates a fresh session and binds the current channel conversation to it
- `session.resume` rebinds the current channel conversation to an existing durable session

This preserves one stable UI thread in the channel while letting the user say, in effect, “continue yesterday’s topic here.”

For clarity:

- the channel thread identity stays unchanged
- the active runtime binding changes
- the running turn stays on the session that was resolved at turn start
- `session.new` and `session.resume` take effect from the next inbound turn on the same channel conversation
- the previously bound session remains durable and discoverable
- `session.resume` does not replay every historical message into the next prompt; it resumes through the normal replay + compaction path

### Catalog metadata

Store lightweight metadata to make listing and search practical:

- `session_title`
- `session_preview`
- `channel_id`
- `user_id`
- `agent_id`
- `last_event_at`
- `message_count`

Title and preview should stay lightweight:

- on session creation, generate one short LLM-produced title and one short preview
- keep the generation budget small and deterministic in shape
- if title generation fails, degrade to first-user-message truncation
- do not refresh titles on every turn in the first implementation

Recommended first-shape constraint:

- `session_title`: one short topic-style line
- `session_preview`: one short sentence

This keeps list readability high without widening the runtime into a general summarization pipeline.

Listing should operate on stored metadata by default. It should not inject raw transcript bodies into the model unless the user explicitly asks to inspect one session.

## 3. Thin User Memory

Add a very small, opt-in user memory layer. This is separate from sessions.

This is a later slice after session durability and explicit session catalog are stable.

Recommended storage shape:

- `data/memory/users/<user_id>/MEMORY.md`

Optional second-step split:

- `data/memory/users/<user_id>/preferences.md`
- `data/memory/users/<user_id>/facts.md`

### What belongs in thin memory

Allowed categories:

- stable preferences
- stable facts that the user explicitly confirms

Examples:

- response language preference
- preferred answer style
- persistent technology choices
- durable project ownership or role
- stable constraints the user wants remembered

Thin memory should be enabled only when the runtime has a stable user identity. If a channel does not provide a durable `user_id`, the runtime should degrade to no long-term user memory for that conversation.

### What stays out of thin memory

Excluded categories:

- temporary task state
- per-session todos
- transient deadlines
- inferred facts the user did not confirm
- sensitive personal data unless the user explicitly requests it and deployment policy allows it

### Write policy

The first implementation should support only explicit writes:

- user says “remember this”
- user says “write this into memory”
- user manually edits the memory file

Model-proposed memory writes can exist later as a review step. They should not be the default write path for the first slice.

### Read policy

Startup injection must stay tiny.

Recommended rule:

- load at most a small capped `MEMORY.md` entry block into the bootstrap prompt or runtime context
- load detailed memory content only through explicit builtin memory reads

This keeps long-term memory useful without making every request pay the full memory cost.

The default startup path should tolerate a missing memory file and treat it as empty memory.

### Suggested builtin family name

- `memory`

Suggested first actions:

- `memory.get`
- `memory.append`
- `memory.replace`
- `memory.delete`

The tool contract should stay simple and file-oriented for the first slice.

## Data Model

## 1. SQLite session tables

Suggested first schema:

- `sessions`
  - one row per session
- `session_messages`
  - ordered messages per session
- `session_tool_outcome_summaries`
  - bounded recent summaries per session
- `session_bindings`
  - active mapping from `channel_id + conversation_id` to `session_id`

The first implementation should keep the schema simple and local-first. Structured JSON payloads are acceptable for continuity-critical derived objects when that avoids broad model refactors.

### `sessions`

Suggested columns:

- `session_id TEXT PRIMARY KEY`
- `conversation_id TEXT NOT NULL`
- `channel_id TEXT NOT NULL DEFAULT ''`
- `user_id TEXT NOT NULL DEFAULT ''`
- `agent_id TEXT NOT NULL DEFAULT ''`
- `active_agent_id TEXT NOT NULL`
- `parent_session_id TEXT`
- `session_kind TEXT NOT NULL`
- `lineage_depth INTEGER NOT NULL`
- `state TEXT NOT NULL`
- `session_title TEXT NOT NULL DEFAULT ''`
- `session_preview TEXT NOT NULL DEFAULT ''`
- `config_snapshot_id TEXT NOT NULL`
- `bootstrap_manifest_id TEXT NOT NULL`
- `context_snapshot_id TEXT`
- `last_run_id TEXT`
- `last_event_at TEXT`
- `last_compacted_at TEXT`
- `latest_compacted_context_json TEXT`
- `latest_actual_usage_json TEXT`
- `tool_call_count INTEGER NOT NULL DEFAULT 0`
- `message_count INTEGER NOT NULL DEFAULT 0`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### `session_messages`

Suggested columns:

- `session_id TEXT NOT NULL`
- `message_index INTEGER NOT NULL`
- `role TEXT NOT NULL`
- `content TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `received_at TEXT`
- `enqueued_at TEXT`
- `started_at TEXT`
- primary key: `(session_id, message_index)`

### `session_tool_outcome_summaries`

Suggested columns:

- `session_id TEXT NOT NULL`
- `summary_index INTEGER NOT NULL`
- `created_at TEXT NOT NULL`
- `tool_name TEXT NOT NULL`
- `status TEXT NOT NULL`
- `summary_json TEXT NOT NULL`
- primary key: `(session_id, summary_index)`

### `session_bindings`

Suggested columns:

- `channel_id TEXT NOT NULL`
- `conversation_id TEXT NOT NULL`
- `session_id TEXT NOT NULL`
- `bound_at TEXT NOT NULL`
- primary key: `(channel_id, conversation_id)`

This table carries the explicit rebinding needed by `session.resume`.

Compatibility rule for the first durable slice:

- keep `sessions.conversation_id` as the session's original or primary conversation identity
- resolve active continuity through `session_bindings` first
- preserve the legacy single-conversation path when no explicit rebinding has occurred

## 2. Thin memory file structure

Suggested `MEMORY.md` structure:

```md
# User Memory

## Preferences
- Prefer concise engineering answers.
- Default to Chinese unless asked otherwise.

## Stable Facts
- Maintains the `marten-runtime` repository.
- Prefers SQLite-backed local-first designs.

## Notes
- Only keep user-confirmed durable information here.
```

This file is intended to stay small and human-editable.

## Runtime Flow

## 1. Default incoming message flow

1. Channel ingress provides `channel_id`, `conversation_id`, `user_id`, and message payload.
2. Runtime resolves the active session binding for `channel_id + conversation_id`.
3. If no binding exists, runtime creates a new session and writes the initial binding.
4. Runtime appends the new user message to durable history.
5. Runtime assembles prompt context from compacted context, replay tail, tool outcome summaries, and tiny memory entry text when configured.
6. Runtime writes assistant output, updated compaction state, usage, and recent tool outcome summaries back to durable storage.

Binding resolution order should stay explicit:

1. active `session_bindings`
2. legacy direct lookup by conversation id for backward-compatible sessions
3. create a new session

## 2. Explicit resume flow

1. User asks to resume an old session.
2. Model uses `session.list`.
3. Model calls `session.resume` with the selected `session_id`.
4. Runtime updates `session_bindings` for the current `channel_id + conversation_id`.
5. The next user message continues from the resumed session state.

## 3. Thin memory write flow

1. User explicitly asks to remember a stable preference or fact.
2. Model calls the builtin `memory` tool.
3. Runtime updates the user memory file.
4. Future turns see only the capped memory entry block unless a detailed read is explicitly requested.

## Error Handling And Safety

- if `sessions.sqlite3` is unavailable, startup should fail clearly when durable session mode is enabled
- if thin memory files are missing, runtime should degrade to empty memory
- `session.resume` should validate that the target session exists
- `session.resume` should preserve current channel thread identity while changing only the bound runtime session
- `memory` writes should reject oversized writes and unsupported categories
- channels without a stable `user_id` should keep working without long-term user memory
- the first slice should prefer explicit user-facing errors over silent heuristics

## Testing Strategy

The first implementation should prove the design with focused tests before any broad refactor.

### Session durability tests

- create a session and restart the store
- append history and restart the store
- persist compacted context and restart the store
- persist tool outcome summaries and restart the store
- preserve child-session lineage fields

### Session catalog tests

- list sessions ordered by `last_event_at`
- resume a session by rebinding `channel_id + conversation_id`
- create a new session explicitly from an existing channel conversation

### Runtime integration tests

- HTTP conversation survives runtime rebuild
- replay after restart still uses the expected recent messages
- compacted context survives restart and remains visible in diagnostics
- recent tool outcome summaries survive restart and remain reusable

### Thin memory tests

- append to `MEMORY.md`
- replace one section in `MEMORY.md`
- load capped memory entry text
- reject writes that exceed configured limits

## Rollout Plan

Recommended implementation order:

1. `SQLiteSessionStore`
2. bootstrap wiring and durable binding restore
3. session diagnostics and operator inspection
4. builtin `session` tool family
5. thin file-based `memory` tool family
6. optional documentation updates for deployment and config surfaces

Stage boundaries:

- Stage 1 done: restart-safe session continuity works and diagnostics survive restart
- Stage 2 done: users can list/search/show/new/resume sessions explicitly
- Stage 3 done: users can explicitly manage a tiny long-term memory file

## Non-Goals

This design deliberately excludes:

- vector search
- embedding-based semantic memory retrieval
- automatic model-driven memory extraction by default
- distributed session coordination
- multi-node locking
- queue-first execution
- full replay of in-flight partial runs
- a general-purpose memory platform

## Recommendation

The repository should treat durable session continuity as the immediate next architectural slice.

After that slice lands, `session` catalog and explicit `memory` tools can extend the operator and user experience without widening the harness boundary.
