Date: 2026-04-21
Status: Draft for review
Scope: design only; implementation stays for the next stage after design review

## Goal

Strengthen session memory in `marten-runtime` without widening the harness:

- when leaving a session through `session.new` or `session.resume`, proactively produce and persist a compacted summary for the source session
- when resuming a historical session, load context through one stable path:
  - prompt base
  - persisted compacted summary when available
  - recent `8` user turns
  - recent `3` tool outcome summaries
  - thin user memory when present
- replace the current message-count replay rule with a more user-meaningful turn-based replay policy

This design explicitly excludes file-based session storage. The active storage backend remains SQLite.

## Design Outcome

This design targets four concrete outcomes:

1. Switching away from a long-running session leaves behind a reusable compacted checkpoint instead of relying only on future overflow-triggered compaction.
2. Restoring an old session rehydrates the model from a stable layering rule rather than a thin best-effort tail alone.
3. Replay policy becomes understandable and operator-tunable:
   - default: recent 8 user turns
   - optional config override: one integer
4. The implementation stays inside the current runtime path instead of introducing a worker platform or subagent-based archival flow.

## Current Repository Baseline

The repository already has the right building blocks, but they are not yet arranged around session switching.

### Existing strengths

1. Durable session persistence already exists.
   - `SQLiteSessionStore` persists ordered history, `latest_compacted_context`, `latest_actual_usage`, and recent tool outcome summaries.
   - `session_bindings` already supports `channel_id + conversation_id -> session_id`.

2. Session restore already uses replay + compaction, not raw full-history injection.
   - `assemble_runtime_context()` reuses `latest_compacted_context` when present.
   - restored sessions already load through the normal runtime context path.

3. Thin compaction already exists as a narrow internal capability.
   - `run_compaction()` can summarize an older prefix and persist a `CompactedContext`.
   - compaction is already model-aware and already integrated into the runtime loop.

4. Session switching already exists as an explicit user surface.
   - `session.new` creates a new session and rebinds the current conversation.
   - `session.resume` rebinds the current conversation to an existing session.

### Current gaps

1. Switch actions do not proactively compact the source session.
   - a session can have a large durable history but still no compacted summary because it never crossed the compaction threshold during normal turns

2. Replay policy is too thin and too low-level.
   - current replay is measured in recent messages, not recent user turns
   - default replay is `6` messages, which is often only `3` turns or less

3. Compaction tail semantics do not match the desired user-facing restore contract.
   - current compacted artifacts preserve a tail count in message units
   - the desired restore rule is easier to reason about in turn units

4. Current compaction trigger is sized for very large context windows.
   - real sessions can feel memory-weak long before the current proactive threshold is reached

## Reference Comparison

Local reference implementations point to the same high-level pattern:

1. Durable storage is broader than live prompt injection.
   - `openclaw` persists session transcript state, then trims live prompt history to the last `N` user turns before the LLM call.
   - `nanobot` persists full session state and archive files, but live prompt assembly uses the unconsolidated suffix plus summary/memory layers.

2. “Feels like full history restore” usually comes from layered context, not raw full-history replay.
   - bounded recent-turn replay keeps local continuity
   - compacted summaries preserve older intent and state
   - memory/context-engine layers can add stable facts or synthetic guidance

3. For `marten-runtime`, the missing piece is policy quality, not a whole-history injection mode.
   - SQLite persistence already holds the full transcript
   - the runtime currently feels thin because replay is still budgeted as recent messages

This design therefore keeps the current durable-storage shape and improves the restore contract rather than switching to raw full-history prompt injection.

## Constraints

- preserve the thin harness boundary
- keep the runtime center at:
  - `channel -> binding -> runtime context -> LLM -> builtin/MCP/skill -> LLM -> channel`
- keep SQLite as the session backend in this slice
- do not switch restore behavior to raw full-history prompt injection
- do not introduce a job queue, workflow engine, or long-lived background worker system
- do not introduce subagent-owned archival sessions for simple session compaction
- do not introduce a new pluggable context-engine seam in this slice
- keep restored prompt assembly bounded and deterministic
- keep config surface minimal

## Problem Statement

The current implementation already loads durable session history after restart, but the user experience still feels like old sessions are not fully remembered.

The root cause is structural:

1. replay is currently too thin
2. switch actions do not force a compacted checkpoint
3. compaction tail semantics are defined in message counts instead of turn counts

As a result, many historical sessions restore through:

- prompt base
- no compacted summary
- recent 6 messages

instead of the desired shape:

- prompt base
- compacted summary of earlier work
- recent 8 user turns

## Approaches Considered

### Approach A — keep fixed 6 messages and only add switch-triggered compaction

Pros:

- smallest change surface
- no config changes

Cons:

- still replays a message-count tail that is too thin for long-running work
- user-facing semantics remain hard to explain
- compaction and replay continue to use different mental models

### Approach B — switch-triggered compaction + fixed 8 user turns

Pros:

- much clearer restore behavior
- smaller surface than a configurable policy
- aligns replay and compaction around user turns

Cons:

- hardcodes a product decision into runtime internals
- forces code changes for future tuning

### Approach C — switch-triggered compaction + configurable replay policy with default 8 user turns

Pros:

- best operator control with one narrow knob
- clear default behavior
- keeps first implementation simple while avoiding future hardcoding
- aligns well with OpenClaw-style turn replay

Cons:

- introduces one config addition

### Recommendation

Use **Approach C**.

The first implementation should still behave as:

- default replay: recent 8 user turns
- switch compaction: enabled by default

The only added operator knob should be the replay turn count.

## Proposed Design

## 1. Canonical Restore Contract

After this change, a restored session should always assemble context in this order:

1. system prompt / app bootstrap prompt
2. compacted summary from `latest_compacted_context`, when available
3. recent `8` user turns from durable session history
4. recent `3` tool outcome summaries
5. thin user memory block, when available
6. working context derived from the active replay source

This makes the restore rule explicit:

- older work belongs in the compacted summary
- recent work belongs in the replay tail
- tool outputs stay as thin structured follow-up hints, not raw transcript replay

For this slice, the tool-summary budget stays fixed:

- restore injects the most recent `3` tool outcome summaries
- this remains a bounded runtime-owned constant, not a new config surface

## 2. Replay Policy Changes

### 2.1 Current problem

`assemble_runtime_context()` currently accepts `replay_limit` in message units.

That is too low-level for long-running conversational work because:

- one long assistant reply can crowd out multiple turns
- `6` messages often means only `3` turns
- the meaning is difficult to explain to users and operators

### 2.2 Proposed policy

Replace message-count replay with **user-turn replay**.

Canonical rule:

- replay the most recent `N` user turns
- include each selected user message plus any assistant replies that belong to those turns
- default `N = 8`

### 2.3 Default and configuration

Default:

- `session_replay_user_turns = 8`

Minimal config surface:

- add one runtime config field under platform config:
  - `runtime.session_replay_user_turns = 8`
- add one optional env override:
  - `SESSION_REPLAY_USER_TURNS`

No additional knobs are required in the first slice.

### 2.4 Turn-selection algorithm

Use this replay algorithm for `SessionMessage` history:

1. filter to replayable `user` and `assistant` messages
2. exclude the current inbound user message when it has already been appended to session history
3. walk backward through replayable history
4. count user messages as turn boundaries
5. once `N` user turns are included, slice from the earliest selected user message forward
6. retain assistant replies within the selected turn window
7. apply the existing noisy-assistant suppression only as a secondary guard, not as the primary replay budget mechanism

### 2.5 Why 8 user turns

`8` user turns gives a stronger near-history buffer while staying bounded:

- it keeps recent intent, corrections, and local continuity visible
- it better covers the common “multi-step coding/debugging exchange” shape
- it is still bounded and easy to explain
- it matches how users think about “recent conversation”

## 3. Compacted Context Contract Changes

### 3.1 Current problem

`CompactedContext.preserved_tail_count` currently uses message units.

That makes compaction artifacts misaligned with the desired replay rule.

### 3.2 Proposed contract

Move compaction tail semantics to **user-turn units**.

Recommended artifact fields:

- keep `source_message_range`
  - this range should stay indexed against the full persisted `session_messages` history so restore can slice without replayable-index remapping
- add `preserved_tail_user_turns`
- keep `created_at`
- keep existing summary fields such as `next_step`, `open_todos`, and `pending_risks`

Backward compatibility:

- existing persisted artifacts without `preserved_tail_user_turns` should continue to load
- absent value falls back to the runtime default replay policy

### 3.3 Tail alignment rule

Switch-triggered compaction should preserve the same number of user turns that the restore path replays.

Default:

- `preserved_tail_user_turns = session_replay_user_turns = 8`

That means a resumed session naturally restores as:

- compact summary for everything older than the preserved tail
- recent 8 user turns as the replay tail

## 4. Proactive Compaction On Session Switch

## 4.1 Trigger points

Trigger source-session compaction on:

- `session.new`
- `session.resume`

Do not trigger on:

- `session.list`
- `session.show`

## 4.2 Which session gets compacted

When a switch action succeeds:

- compact the **source session**
- store the artifact on the source session
- bind the conversation to the **target session** as today

This keeps responsibilities clean:

- source session gains better resumability
- target session receives the next inbound turn

## 4.3 Why not use a subagent

Do not use a subagent for switch-triggered compaction in the first slice.

Reasons:

- compaction is already a single-purpose internal LLM call
- subagents would create extra session lineage, extra routing, and extra persistence semantics for a problem that only needs one summarization call
- the harness already has a thin compaction runner; reuse it directly

## 4.4 Execution model

Use **inline best-effort compaction inside the switch path**.

Recommended flow:

1. current session is resolved at turn start
2. user requests `session.new` or `session.resume`
3. switch handler checks whether the source session needs compaction
4. if needed, call the compaction runner directly using the current resolved LLM client
5. persist `latest_compacted_context` on the source session
6. perform the bind/create switch action
7. continue returning the normal switch result to the user

Failure semantics:

- compaction failure must not block the switch
- switch success and compaction success are separate outcomes
- compaction failure should log clearly and leave any existing compacted artifact untouched

### 4.5 Why inline instead of background

Inline best-effort compaction is the thinner design for this slice:

- no executor or job service required
- no crash window between successful switch and queued compaction start
- no new persistence state for background task bookkeeping
- session switching is low-frequency enough to tolerate one extra summarization call

If latency later proves unacceptable, a follow-up slice can add a bounded background fallback. That is not needed in the first implementation.

## 5. Source Session Eligibility Rules

Do not compact on every switch blindly.

A source session is eligible for switch-triggered compaction only when all conditions hold:

1. source and target sessions are different
2. source session has more than `session_replay_user_turns` replayable user turns
3. source session contains replayable content worth summarizing
4. source session has grown beyond the already-compacted prefix, or has no compacted context yet

Suggested staleness rule:

- if no `latest_compacted_context` exists, compaction is eligible
- if `latest_compacted_context.source_message_range[1]` is older than the current compactable prefix, compaction is eligible
- otherwise skip

This keeps switch compaction cheap and idempotent.

## 6. Switch Path Integration

## 6.1 Introduce a narrow session transition helper

Do not embed LLM ownership directly into `run_session_tool()` logic.

Add one thin internal helper or service, for example:

- `session/transition.py`

Responsibilities:

- inspect switch action intent
- evaluate source-session compaction eligibility
- run compaction when needed
- persist the result
- then perform create/bind mutation on the session store

This keeps the builtin tool small and keeps compaction-specific logic out of generic store methods.

## 6.2 Inputs required by the transition helper

The helper needs:

- `session_store`
- source `session_id`
- target action (`new` or `resume`)
- current `channel_id`
- current `conversation_id`
- current inbound user message text
- current resolved LLM client
- replay policy

The current inbound user message matters because the compaction path should exclude the switch request itself from the summarized source prefix when possible.

## 7. Resume-Time Restore Semantics

After a historical session is resumed, the next inbound turn should see:

- prompt base
- compact summary from that session when present
- recent 8 user turns from that session
- recent 3 tool outcome summaries from that session
- thin memory for the current stable user when present

This should remain true after:

- runtime restart
- explicit `session.resume`
- a previous `session.new` away from that session

## 8. Diagnostics And Operator Visibility

Add narrow diagnostics so the behavior is observable.

Recommended additions:

### Session diagnostics

- whether the session has a compacted summary
- compacted summary timestamp
- compacted prefix end index
- preserved tail user turns

### Runtime diagnostics

- current replay policy user-turn count
- whether the latest switch-triggered compaction ran
- keep runtime diagnostics process-scoped:
  - expose latest in-process switch-compaction outcome
  - do not invent a fake single “active session” for the whole runtime
  - per-session compact-summary reuse belongs in session diagnostics and `runtime.context_status`

### `runtime.context_status`

Expose enough detail to explain:

- current replay tail budget in user turns
- current checkpoint availability
- whether the current session is running on compact-summary reuse

## 9. Failure Handling

The implementation should prefer explicit and local failure behavior.

Rules:

- `session.new` and `session.resume` still succeed when switch compaction fails
- a failed switch compaction must not erase an older valid compacted artifact
- replay path must continue to work with:
  - no compacted summary
  - old compacted summary
  - newly generated compacted summary
- malformed or legacy compacted artifacts should fall back to the default replay policy

## 10. Testing Strategy

The first implementation should prove behavior with focused tests.

### 10.1 Replay policy tests

- last 8 user turns are replayed instead of last 8 messages
- selected replay includes assistant replies belonging to selected turns
- current inbound user message is excluded from replay
- noisy assistant replies do not orphan a selected user turn
- compacted sessions replay compact summary plus recent turn tail

### 10.2 Switch compaction tests

- `session.new` compacts the source session when eligible
- `session.resume` compacts the source session when eligible
- switching does not fail when compaction generation fails
- unchanged source sessions skip redundant compaction
- compacted artifact preserves tail turns equal to replay policy

### 10.3 Integration tests

- restore after `session.new` loads compact summary plus recent replay tail
- restore after `session.resume` loads compact summary plus recent replay tail
- restart still preserves compacted artifact and replay behavior
- `session.show` reflects compact summary availability

### 10.4 Diagnostics tests

- runtime diagnostics expose replay policy
- runtime context status reflects checkpoint availability
- session listing/show surfaces compact-summary presence correctly

## 11. Rollout Plan

Recommended implementation order:

1. introduce replay policy plumbing and turn-based replay tests
   - for the current repository shape, prefer threading one integer through existing call sites over adding a new standalone replay-policy service or dataclass
2. update `CompactedContext` contract to use preserved tail user turns
3. add session transition helper for switch-triggered compaction
4. wire `session.new` and `session.resume` through the helper
5. extend diagnostics
6. run focused and integration regression coverage

## 12. Non-Goals

This design deliberately excludes:

- file-based session storage
- raw full-history prompt injection for restored sessions
- semantic memory or embeddings
- pluggable context-engine expansion for prompt assembly
- subagent-based session archival
- workflow queues for compaction jobs
- automatic compaction on every ordinary turn regardless of need
- large new config surfaces beyond the replay turn count

## Recommendation

Implement session memory strengthening in this order:

1. make replay policy turn-based with default `8`
2. make that `8` configurable through one runtime integer
3. run inline best-effort compaction on `session.new` and `session.resume`
4. persist compacted artifacts in SQLite as today

That gives the desired resumed-session shape:

- prompt base
- compacted summary
- recent 8 user turns
- recent 3 tool outcome summaries
- thin memory

without introducing a new storage model or a new execution subsystem.
