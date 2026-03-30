# Architecture Audit

This page records the current architecture judgment for `marten-runtime`.

## Short Answer

`marten-runtime` is already a real private-agent runtime for:

`gateway -> binding -> agent router -> runtime context assembly -> LLM/tool loop -> channel delivery`

Milestone A from the private harness design is implemented and test-covered:

1. gateway binding + multi-agent routing
2. runtime context assembly + live context rehydration
3. skills first-class runtime integration
4. provider transport resilience

Milestone B is intentionally still pending in part:

1. durable session persistence

Interactive conversation serialization is already implemented as single-process FIFO conversation lanes for HTTP `/messages` and Feishu interactive ingress.

That means the repository is correctly shaped as a simplified openclaw-style private agent runtime, but it is still an MVP harness rather than a fully hardened multi-session runtime.

## What Is Implemented

### 1. Binding And Multi-Agent Routing Are On The Live Path

Current evidence:

- `config/bindings.toml` defines channel, conversation, user, and mention-gated routing rules
- `bindings_loader.py` and `agents/bindings.py` load and resolve binding precedence
- `AgentRouter.route(...)` now checks requested agent, binding match, active agent, and default fallback in deterministic order
- tests cover conversation binding, user binding, mention-required behavior, and fallback routing

Judgment:

- channel/user/conversation can now bind to the intended agent
- multi-agent hosting is no longer just config shape; it is part of the active runtime path

### 2. Runtime Context Assembly Is Real

Current evidence:

- `runtime/context.py` assembles one structured runtime context object per turn
- `session/replay.py` feeds recent session messages back into the next request
- compaction and rehydration are used to construct working context text
- `runtime/loop.py` passes replayed context, skill snapshot data, and tool snapshot data into `LLMRequest`

Judgment:

- the LLM now sees replayed session context instead of only the current user turn
- working context is assembled in a focused layer instead of being scattered through bootstrap and provider code

### 3. Skills Are First-Class Runtime Inputs

Current evidence:

- `skills/service.py` builds a visible skill snapshot for the runtime
- `skills/selector.py` resolves activated skills for the current turn
- `runtime/llm_client.py` injects skill heads, always-on skill text, and activated skill bodies into provider messages
- tests verify both startup skill visibility and activation-time body injection

Judgment:

- skills are no longer passive files on disk
- the model can now see both the stable skill surface and the bodies of relevant activated skills

### 4. Provider Retry Is Implemented

Current evidence:

- `runtime/provider_retry.py` normalizes provider transport errors
- `OpenAIChatLLMClient` wraps transport calls with bounded retry/backoff
- retryable timeout and transport failures are retried
- auth failures remain fail-fast

Judgment:

- transient provider failures no longer break the main chain as easily
- current resilience is still minimal, but it is correctly scoped for Milestone A

### 5. Existing MCP And Channel Behavior Were Preserved

Current evidence:

- runtime loop tests still cover the multi-step tool loop
- Feishu tests still cover dedupe, self-message ignore, hidden progress, final-card delivery, and websocket service behavior
- full `unittest` coverage passes with the current Milestone A code path

Judgment:

- Milestone A did not regress the existing MCP tool loop
- Feishu-facing behavior remains aligned with the intended UX and safety boundaries

## What Is Still Missing

### 1. Per-Conversation Serialization

Current state:

- incoming messages are still processed directly
- there is no in-memory lane guard or one-conversation-at-a-time protection yet

Impact:

- overlapping messages in the same conversation can still race

Status:

- known gap
- intentionally deferred to Milestone B

### 2. Durable Session Persistence

Current state:

- live session state is still in-memory on the hot path
- process restart loses session continuity

Impact:

- context replay works only for the life of the current process

Status:

- known gap
- intentionally deferred to Milestone B

## Non-Blocking Future Work

These are valid future directions, but they are not required for the current project goal:

- durable delivery outbox
- queue-first or worker-first execution
- heartbeat / cron / proactive runs
- hybrid memory recall and promotion
- planner / swarm style orchestration

## Audit Conclusion

The repository now matches the intended Milestone A architecture:

- `LLM + agent + MCP + skill` first
- `harness-thin, policy-hard, workflow-light`
- main chain centered on runtime assembly, not queue-first infrastructure

Remaining issues are now mostly about hardening and publishability, not the basic intelligence spine.
