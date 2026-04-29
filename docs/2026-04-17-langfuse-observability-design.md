# Langfuse Observability Integration Design

Date: 2026-04-17  
Status: Draft for review  
Scope: design only; implementation and execution checklist stay for the next stage after design review

## Goal

Add Langfuse observability to `marten-runtime` along the active runtime spine:

`channel -> binding -> runtime loop -> builtin tool / MCP / skill -> delivery / diagnostics`

The design keeps the harness thin, reuses the existing `trace_id` / `run_id` / `tool_calls` / `provider_calls` model, and avoids refactoring the current OpenAI-compatible transport layer.

## Design Outcome

This design targets one practical result:

- every runtime turn maps to one Langfuse trace
- every LLM request round maps to one Langfuse generation
- every builtin tool or MCP tool invocation maps to one Langfuse span
- every run outcome carries enough metadata to correlate Langfuse traces with existing HTTP diagnostics
- the integration stays optional and degrades to a no-op when Langfuse is unconfigured

Execution scope covered by this design:

- interactive HTTP and Feishu turns that flow through `RuntimeLoop.run()`
- automation-triggered turns that flow through the same runtime path
- subagent child runs that reuse the same run-history and runtime-loop surfaces

## Current Repository Baseline

The current repository already provides most of the correlation model that Langfuse needs.

### Existing strengths

1. Stable runtime trace and run identifiers already exist.
   - HTTP ingress passes a `trace_id` into the runtime.
   - `RuntimeLoop.run()` creates the canonical `run_id` through `InMemoryRunHistory.start()`.
   - `GET /diagnostics/run/{run_id}` and `GET /diagnostics/trace/{trace_id}` already exist for operator correlation.

2. Runtime diagnostics already capture the high-value episode facts.
   - `RunRecord` stores `llm_request_count`, `provider_calls`, `tool_calls`, `latest_actual_usage`, `timings`, and queue diagnostics.
   - tool failures are already preserved in `tool_calls`.

3. The main runtime spine is centralized.
   - `RuntimeLoop.run()` owns the request lifecycle, LLM rounds, tool execution, success/error completion, and timing updates.
   - this is the narrowest place to add trace and span lifecycle control.

4. Environment config already reserves Langfuse secrets.
   - `.env.example` already includes `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` placeholders.

### Current gaps

1. The repository ships no Langfuse dependency.
2. The runtime does not initialize any Langfuse client.
3. No root trace, generation, or tool span is emitted.
4. Diagnostics do not expose whether Langfuse is enabled or which external trace id was attached.
5. `.env.example` lacks a `LANGFUSE_BASE_URL` entry for self-hosted or regional deployment.

## Constraints

- preserve the current thin harness architecture
- preserve the current OpenAI-compatible custom transport path
- keep Langfuse optional and safe for local development
- avoid request-specific routing or monitoring-only control branches
- reuse the current diagnostics model instead of inventing a parallel observability state machine
- keep patch scope narrow enough that the first implementation slice can land without reshaping the runtime

## Approaches Considered

### Approach A — manual Langfuse SDK instrumentation in the runtime spine

Add a thin runtime-owned Langfuse adapter and instrument the run lifecycle directly in `RuntimeLoop.run()`.

Why this fits best:

- matches the repository center of gravity: runtime loop owns the end-to-end chain
- works with the current custom OpenAI-compatible transport
- keeps the provider layer stable
- maps naturally onto existing `run_id`, `trace_id`, tool history, timing, and usage fields
- gives the repository one explicit observability boundary instead of hidden SDK behavior

### Approach B — replace or wrap the provider layer with Langfuse OpenAI integration

This centers observability in the provider client.

Trade-offs:

- provider-level generations become easy
- root run trace and tool spans still need runtime-layer work
- current code uses a custom urllib-based OpenAI-compatible client, so provider wrapping pushes the repo toward a transport refactor that the feature itself does not require

### Approach C — add OpenTelemetry first and bridge Langfuse later

This broadens the architecture beyond the immediate need.

Trade-offs:

- useful if the repository is moving toward unified metrics, traces, and logs across many services
- larger design surface
- more moving parts than the current runtime needs for its first production observability layer

### Recommendation

Use **Approach A** for the first slice.

It produces the highest signal with the smallest patch surface and aligns with the repository's current shape.

## Proposed Architecture

## 1. Thin observability module

Add one new module that owns all Langfuse-facing behavior.

Suggested path:

- `src/marten_runtime/observability/langfuse.py`

Suggested responsibilities:

- load and validate Langfuse config from environment
- initialize a reusable Langfuse client when config is complete
- expose a small runtime-facing API such as:
  - `enabled()`
  - `start_run_trace(...)`
  - `observe_generation(...)`
  - `observe_tool_call(...)`
  - `finalize_run(...)`
  - `flush()`
- encapsulate all SDK imports so the rest of the runtime stays thin
- degrade to a no-op implementation when Langfuse config is absent

This module becomes the single observability seam. The rest of the runtime calls it through a narrow interface.

## 2. Root trace lifecycle in `RuntimeLoop.run()`

Start the Langfuse root trace in `RuntimeLoop.run()` after `run_id` exists and before the first LLM round begins.

The root trace should use the existing runtime correlation identifiers:

- `trace_id`: repository runtime trace id
- `run_id`: canonical run history id
- `session_id`
- `agent_id`
- `app_id`
- `channel_id`
- `request_kind`
- `parent_run_id`
- `config_snapshot_id`
- `bootstrap_manifest_id`

Recommended naming:

- trace name: `runtime.turn`
- trace input: current user message plus compact runtime context summary when available
- trace metadata: identifiers, runtime mode, model profile, prompt mode, compaction decision, lane diagnostics when available

This keeps Langfuse aligned with the repository's real execution owner.

## 3. Generation lifecycle around each `resolved_llm.complete(current_request)`

Instrument the LLM call inside `RuntimeLoop.run()` rather than inside the transport layer.

Why this location is better for v1:

- the runtime loop already knows the stage: `llm_first` or `llm_second`
- the loop already owns `current_request`, `llm_request_count`, timing, usage, tool history, and error mapping
- the design keeps Langfuse aligned with the repo's run-history semantics

Each generation should capture:

- generation name: `llm.first` or `llm.followup`
- model name
- provider name
- model profile name
- request kind
- input message payload assembled from `LLMRequest`
- available tools snapshot or summarized tool names
- response text or requested tool call
- token usage from `reply.usage`
- retry diagnostics from `last_call_diagnostics`
- latency in milliseconds
- final status: success or error

Error metadata should include:

- normalized error code for provider failures
- timeout budget when present
- retry attempt count when present

## 4. Tool span lifecycle around `resolve_tool_call(...)`

Instrument tool spans in `RuntimeLoop.run()` around the `resolve_tool_call(...)` boundary.

Each tool span should capture:

- span name: `tool.call`
- tool family and tool name
- requested payload
- normalized result payload or summarized result
- success / rejection / execution_failed classification
- runtime stage timing
- channel id, agent id, and run id metadata

This design covers:

- builtin tools
- MCP tools
- future tool families that still pass through `resolve_tool_call(...)`

The tool span becomes the Langfuse-side equivalent of `run_history.tool_calls`.

## 5. Run finalization and correlation write-back

When the runtime finishes a run, finalize the Langfuse trace with:

- final status: succeeded / failed
- error code when present
- final visible text when present
- total elapsed time
- `llm_request_count`
- aggregate usage from `RunRecord`
- compacted-context diagnostics
- tool history summary

Then write the external correlation ids back into existing diagnostics structures.

Minimum new fields to persist locally:

- `RunRecord.external_observability.langfuse_trace_id`
- `RunRecord.external_observability.langfuse_url` or trace permalink when available
- `trace_index[trace_id].external_refs.langfuse_trace_id`
- `trace_index[trace_id].external_refs.langfuse_url`

This preserves the current operator workflow:

`runtime diagnostics -> run_id -> trace_id -> Langfuse trace`

## 6. Runtime diagnostics surface

Extend `GET /diagnostics/runtime` and run/trace diagnostics to expose the observability state.

Suggested runtime diagnostics additions:

```json
{
  "observability": {
    "langfuse": {
      "enabled": true,
      "configured": true,
      "base_url": "https://cloud.langfuse.com",
      "environment": "default"
    }
  }
}
```

Suggested run/trace diagnostics additions:

- `langfuse_trace_id`
- `langfuse_url`
- optional `langfuse_enabled_at_run_time`

This keeps existing diagnostics useful for operators who begin from the local runtime surface.

## Config Design

## Required environment variables

Keep the existing keys and add the missing base-url surface.

```env
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Optional follow-up surface for later phases:

```env
LANGFUSE_ENV=
LANGFUSE_RELEASE=
LANGFUSE_SAMPLE_RATE=
```

For the first slice, only `PUBLIC_KEY`, `SECRET_KEY`, and `BASE_URL` are required by design.

## Runtime behavior

- complete config present → Langfuse client enabled
- partial config present → startup keeps running and diagnostics show `configured=false` with a reason
- no config present → runtime uses the no-op observer and records `enabled=false`

This behavior keeps local development smooth and keeps observability optional.

## Data Model Mapping

| Repository field | Langfuse mapping |
| --- | --- |
| `trace_id` | root trace metadata and external correlation key |
| `run_id` | root trace metadata and session-level run identifier |
| `session_id` | session id / conversation metadata |
| `request_kind` | trace metadata |
| `agent_id`, `app_id` | trace metadata and tags |
| `provider_calls[*]` | generation metadata for retry diagnostics |
| `tool_calls[*]` | tool spans |
| `latest_actual_usage` | generation usage and final trace summary |
| `timings` | generation and trace duration fields |
| `compaction` | trace metadata |
| `queue` | trace metadata |

## Minimal Code Patch Plan

This section lists the smallest patch surface that supports a useful first integration.

### New files

1. `src/marten_runtime/observability/langfuse.py`
   - new thin adapter
   - client initialization
   - no-op fallback
   - span / generation / trace helpers

### Existing files to patch

1. `requirements.txt` and `pyproject.toml`
   - add the Langfuse SDK dependency

2. `.env.example`
   - add `LANGFUSE_BASE_URL`
   - keep existing public/secret placeholders

3. `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
   - initialize the Langfuse observer once during runtime bootstrap
   - store it on `HTTPRuntimeState`
   - flush it during shutdown if needed

4. `src/marten_runtime/interfaces/http/app.py`
   - call observer flush/shutdown from the FastAPI lifespan teardown
   - keep shutdown sequencing narrow and explicit

5. `src/marten_runtime/runtime/loop.py`
   - start root run trace after `run_id` is created
   - wrap each LLM call in a generation observation
   - wrap tool execution in a tool span observation
   - finalize the trace on success and error exits

6. `src/marten_runtime/runtime/history.py`
   - add a small `external_observability` surface to `RunRecord`
   - preserve Langfuse correlation ids for local diagnostics

7. `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
   - write Langfuse external refs into `trace_index[trace_id].external_refs`
   - preserve the existing `trace -> run_ids / job_ids / event_ids` shape

8. `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
   - expose runtime-level Langfuse enabled/configured state

### Optional follow-up patches

These are useful later and stay out of the first minimal slice.

- `src/marten_runtime/runtime/llm_client.py`
  - only if the team wants lower-level provider payload instrumentation later
- `docs/CONFIG_SURFACES.md`
  - add the Langfuse base URL once implementation lands
- `README.md` / `README.md`
  - add operator-facing observability setup notes once implementation lands

## Verification Plan for the Future Implementation

This design keeps the future implementation provable in small slices.

### Slice 1 — bootstrap and no-op behavior

Proof:

- runtime boots with no Langfuse config
- runtime boots with full Langfuse config
- `/diagnostics/runtime` exposes the expected observability state

### Slice 2 — run trace and generation instrumentation

Proof:

- one plain chat turn creates one root trace and one generation
- run diagnostics keep the local `run_id` / `trace_id` path
- provider failure path finalizes the Langfuse trace with failure metadata

### Slice 3 — tool span instrumentation

Proof:

- one builtin tool turn creates one tool span
- one MCP tool turn creates one tool span
- tool rejection and tool execution failure paths surface correct error state

### Slice 4 — external correlation in local diagnostics

Proof:

- `/diagnostics/run/{run_id}` returns Langfuse trace correlation fields
- `/diagnostics/trace/{trace_id}` returns Langfuse external refs

## Risks and Mitigations

### Risk 1 — observability code widens runtime complexity

Mitigation:

- one thin adapter module
- runtime loop calls a narrow interface
- no SDK imports outside the observability module and bootstrap seam

### Risk 2 — high-cardinality or oversized payload logging

Mitigation:

- summarize large tool results before attaching them
- keep full operator truth in existing local diagnostics and structured stores
- send concise payloads to Langfuse metadata when raw content is too large

### Risk 3 — partial configuration creates startup friction

Mitigation:

- no-op fallback when unconfigured
- diagnostics expose configured state and reasons
- runtime core stays usable without Langfuse

### Risk 4 — duplicated source of truth between Langfuse and run history

Mitigation:

- local `RunRecord` remains source-of-truth for runtime semantics
- Langfuse is the external observability surface
- local history stores only the external correlation ids needed to bridge the two

## Deferred Items

These items stay out of the first design slice on purpose:

- broad OpenTelemetry adoption
- transport-layer refactor away from the current OpenAI-compatible client
- prompt or tool payload redaction policy beyond basic truncation and summarization
- dashboard conventions, scorecards, or evaluator pipelines
- execution document and patch sequencing details beyond the minimal patch map in this design

## Recommended Next Step After Design Review

After this design is confirmed, write one execution document that turns the minimal patch map into ordered implementation slices with exact verification commands.
