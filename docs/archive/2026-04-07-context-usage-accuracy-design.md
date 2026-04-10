# 2026-04-07 Context Usage Accuracy Design

## 1. Purpose

This document proposes the next thin architecture slice for `marten-runtime`: replace the current rough context-usage estimate with a more credible usage model that is still compatible with the runtime's thin-harness boundary.

The target is **not** a full prompt-accounting platform. The target is:

- provider-reported usage when available
- tokenizer-based preflight input estimation before a request is sent
- rough fallback only when the first two are unavailable
- a compact user-queryable runtime status surface that remains LLM-first

This design is intentionally scoped to improve:

- user-facing `runtime.context_status`
- compaction-trigger trustworthiness
- run/session diagnostics

without drifting into:

- memory platformization
- retrieval/vector systems
- full provider-abstraction rearchitecture
- large host-side routing logic

---

## 2. Requirement Check Against User Intent

### 2.1 Confirmed user requirements

The approved direction from the latest discussion is:

- the current rough estimate (`len(text)//4`) is not good enough as the primary visible value
- the number shown to the user should have real reference value
- provider usage is preferred whenever the provider returns it
- if provider usage is unavailable, estimate against the **actual outbound LLM payload**, not against a hand-picked subset of text fields
- the result should still stay inside the current thin builtin boundary:
  - builtin performs inspection/query
  - LLM still decides how to answer naturally
- the design must not widen into a memory system, retrieval layer, or complex host-side planner
- different models have different context windows and tokenization behavior; the design should respect model metadata instead of assuming one fixed universal window

### 2.2 Interpreted product outcome

The intended outcome is **not** “perfect provider-independent accounting for every model on day one.”

It is:

- make the primary number meaningful enough for users and operators
- make compaction triggers materially more trustworthy
- preserve the current runtime architecture shape
- allow incremental model-specific tokenizer improvements over time

---

## 3. Review Of The Current Baseline

### 3.1 What exists today

Current `marten-runtime` already has:

- model-window-aware compaction settings:
  - `context_window_tokens`
  - `reserve_output_tokens`
  - `compact_trigger_ratio`
- one builtin family tool `runtime` with action `context_status`
- run-level compaction diagnostics
- current-request rough estimation in `estimate_request_tokens()`

Relevant files:

- `src/marten_runtime/runtime/llm_client.py`
- `src/marten_runtime/tools/builtins/runtime_tool.py`
- `src/marten_runtime/runtime/history.py`
- `src/marten_runtime/session/compaction_trigger.py`

### 3.2 Current gap

Current visible usage is derived from:

- selected prompt text fields
- replayed conversation messages
- `working_context_text`
- a rough `len(text)//4` heuristic

This means it does **not** fully account for:

- function/tool schema overhead
- tool descriptions
- tool call and tool result payloads in follow-up turns
- provider message-wrapper overhead
- provider-reported output/reasoning/cache usage
- model-specific tokenization differences

### 3.3 Consequence

The current estimate is still useful as a **trend signal**, but not as a reliable “current context usage” number.

That is the exact gap this design addresses.

---

## 4. What Strong Existing Systems Actually Do

## 4.1 OpenCode pattern

Observed from `opencode-ai/opencode`:

- provider usage is tracked and persisted at session level
- auto-compact uses model context window and triggers near the high-water mark
- UI shows token/cost status from provider-reported usage rather than a local string-length guess

What matters architecturally:

- actual usage is treated as the most trustworthy signal
- compaction decisions should prefer runtime/provider truth over local approximation when available

## 4.2 Codex pattern

Observed from `openai/codex`:

- the TUI consumes runtime/app-server token telemetry rather than inventing its own final truth
- token usage surfaces distinguish input/output/cached/reasoning fields
- model metadata includes context-window-aware compaction thresholds and effective window considerations
- the UI treats some baseline/system overhead as non-user-controllable capacity

What matters architecturally:

- runtime-side structured usage telemetry is the right source of truth
- context usage is more credible when it is tied to real response usage events
- fixed system/tool overhead should be considered explicitly, not hidden in a naive estimate

## 4.3 Claude Code pattern

Observed from the reconstructed Claude Code source map:

- context accounting is category-aware:
  - system prompt
  - tools
  - MCP tools
  - agents
  - memory files
  - skills
  - messages
  - message breakdown for tool calls/results/attachments
- it prefers API-backed counting where possible and falls back when necessary
- autocompact thresholding is model-window aware and leaves explicit headroom/buffers

What matters architecturally:

- category-aware breakdowns are useful for diagnostics and operator trust
- user-visible output can stay concise while diagnostics stay detailed
- preflight counting against the actual outbound request shape is much more meaningful than partial string counting

## 4.4 Conclusion for `marten-runtime`

The strongest shared idea across OpenCode, Codex, and Claude Code is:

> trust provider/runtime usage first; when estimating locally, estimate the real outbound payload, not an arbitrary subset of prompt text.

That is the pattern this design adopts.

---

## 5. Architecture Decision

## 5.1 Use a three-tier usage source strategy

For each run and for `runtime.context_status`, usage should be resolved in this priority order:

1. **Provider actual usage**
   - source of truth for the just-completed provider call when available
2. **Tokenizer-based preflight estimate**
   - estimate the outbound request payload immediately before sending it
3. **Rough fallback estimate**
   - only when neither of the above is available

### 5.2 Do not replace the current builtin boundary

Keep:

- builtin family: `runtime`
- action: `context_status`
- LLM-first natural-language answer path

Change only the returned data quality and semantics.

---

## 6. Usage Semantics

## 6.1 Separate “current outgoing request” from “last actual provider usage”

This distinction is necessary.

### `last_actual_usage`

Represents the most recent real provider-reported usage from a completed LLM call.

Suggested fields:

- `input_tokens`
- `output_tokens`
- `total_tokens`
- `cached_input_tokens` optional
- `reasoning_output_tokens` optional
- `provider_name`
- `model_name`
- `captured_at`

### `next_request_estimate`

Represents the estimated input cost of the request that would be sent **now** for the current turn.

Suggested fields:

- `input_tokens_estimate`
- `estimator_kind` = `provider` | `tokenizer` | `rough`
- `context_window_tokens`
- `effective_window_tokens`
- `usage_percent`
- `advisory_threshold_tokens`
- `proactive_threshold_tokens`

### Why both are needed

- provider usage answers: “what actually happened on the last call?”
- preflight estimate answers: “if we send the current turn now, how large is it likely to be?”

Users care about both, but especially the second one for “现在上下文用了多少”.

---

## 7. Data Sources And Resolution Strategy

## 7.1 Provider actual usage

### Primary rule

If the provider returns usage fields, persist them and prefer them over any local approximation for the completed call.

### Scope for first implementation

The first implementation should support:

- OpenAI-compatible chat completion `usage` payloads

The design should still allow additional providers later.

### Normalized runtime shape

Introduce one normalized internal shape, for example:

- `input_tokens`
- `output_tokens`
- `total_tokens`
- `cached_input_tokens`
- `reasoning_output_tokens`
- `raw_usage_payload`

This avoids scattering provider-specific parsing logic throughout the runtime.

## 7.2 Tokenizer-based preflight estimate

### Primary rule

Estimate token usage against the **actual outbound payload** that the LLM client is about to send.

Estimate target includes:

- final `messages`
- tool descriptions
- tool parameter schemas
- tool follow-up messages (`assistant tool_calls`, `tool` messages)
- all runtime-injected system text that actually lands in the payload

### Why this matters

This is the layer that upgrades the current estimate from “rough prompt text size” to “approximate true input size for this request”.

## 7.3 Rough fallback estimate

Replace the current `len(text)//4` fallback with one deterministic payload-based fallback rule.

Implementation rule for v1:

1. serialize the final outbound payload with:
   - `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
2. classify the serialized characters into:
   - `ascii_text_chars`
   - `cjk_chars`
   - `other_non_ascii_chars`
   - `json_structure_chars`
   - `whitespace_chars`
3. compute:

```text
rough_input_tokens =
  ceil(
    ascii_text_chars / 4.0
    + cjk_chars / 1.2
    + other_non_ascii_chars / 2.0
    + json_structure_chars / 2.0
    + whitespace_chars / 6.0
  )
```

Character-bucket rules:

- `ascii_text_chars`
  - ASCII letters, digits, and ASCII punctuation except JSON structural characters and whitespace
- `cjk_chars`
  - characters in:
    - `U+3400..U+4DBF` (CJK Extension A)
    - `U+4E00..U+9FFF` (CJK Unified Ideographs)
    - `U+3040..U+309F` (Hiragana)
    - `U+30A0..U+30FF` (Katakana)
    - `U+AC00..U+D7AF` (Hangul syllables)
- `other_non_ascii_chars`
  - all remaining non-ASCII characters not counted in `cjk_chars`
- `json_structure_chars`
  - one of: `{ } [ ] : , "`
- `whitespace_chars`
  - spaces, tabs, carriage returns, and newlines

This rule is intentionally empirical and conservative. It exists to make fallback estimation materially better than a single `/4` rule for mixed Chinese/English/tool-schema payloads while remaining thin and deterministic.

Reference pseudocode:

```python
def classify_char(ch: str) -> str:
    code = ord(ch)
    if ch in " \t\r\n":
        return "whitespace_chars"
    if ch in '{}[]:,"':
        return "json_structure_chars"
    if code <= 0x7F:
        return "ascii_text_chars"
    if (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    ):
        return "cjk_chars"
    return "other_non_ascii_chars"
```

When it is used, diagnostics and builtin results must say so explicitly.

---

## 8. Tokenizer Strategy

## 8.1 Do not require perfect universal tokenizer coverage in v1

Different models/providers use different tokenizers. The design should therefore support a model-configured tokenizer family rather than assume one global tokenizer.

Suggested model metadata additions:

- `tokenizer_family: str | None`
- `supports_provider_usage: bool | None`
- optional later: `effective_context_ratio: float | None`

## 8.2 Initial tokenizer-family approach

The first thin implementation must support this explicit family set:

- `openai_cl100k`
- `openai_o200k`
- `rough`

Family contract:

- `openai_cl100k`
  - use the corresponding tokenizer backend directly
- `openai_o200k`
  - use the corresponding tokenizer backend directly
- `rough`
  - use the deterministic script-aware fallback rule defined in section 7.3
  - do not substitute `len(text)//4`
  - do not add per-provider special cases inside `rough`

Therefore `rough` must be used only when:

- provider usage is unavailable
- no reliable `tokenizer_family` is configured for the active profile

When `rough` is used:

- diagnostics and builtin results must explicitly mark it as a fallback estimate
- compaction / advisory logic may consume it as a conservative estimate
- user-visible wording must not describe it as actual provider usage

This is intentionally thin.

It is enough to:

- support OpenAI-compatible profiles better than today
- avoid blocking the whole design on perfect tokenizer parity for every provider
- preserve a safe fallback path without leaving algorithm choice undefined

## 8.3 Future extension boundary

Tokenizer quality can improve incrementally per model profile without changing the runtime contract.

That keeps the architecture thin while allowing better precision over time.

---

## 9. Context Window And Effective Window Policy

## 9.1 Preserve current model-window-aware compaction settings

Keep the current compaction window inputs:

- `context_window_tokens`
- `reserve_output_tokens`
- `compact_trigger_ratio`

## 9.2 Continue to compute effective window

`effective_window_tokens = context_window_tokens - reserve_output_tokens`

This remains the right baseline for:

- usage percentage
- advisory status
- proactive compact threshold

## 9.3 Do not hard-code one global universal window

The user-provided context-window reference material reinforces this:

- models differ widely in advertised and effective context windows
- “200k for everything” is acceptable only as a fallback, not as primary truth

Therefore:

- profile metadata remains authoritative when known
- fallback defaults remain necessary when unknown

---

## 10. Runtime Data Model Changes

## 10.1 LLM reply metadata

Extend `LLMReply` with normalized usage metadata.

Suggested addition:

- `usage: LLMUsage | None`

## 10.2 Run history

Extend run diagnostics/history to record:

- preflight estimate for the first request
- optional preflight estimate for tool follow-up requests if needed
- last actual provider usage from the completed call
- estimate source kind
- optional category breakdown

## 10.3 Session-level latest actual usage

Persist the latest actual provider usage in session state so `runtime.context_status` can show recent true usage even before the next run completes.

This mirrors the general spirit of OpenCode/Codex: keep the latest credible usage close to the session/runtime state.

---

## 11. Diagnostics And Breakdown

## 11.1 Internal diagnostics should be richer than builtin output

Internal diagnostics should expose more detail than user-facing answers.

Suggested internal breakdown fields:

- `system_prompt_tokens`
- `skill_tokens`
- `capability_catalog_tokens`
- `always_on_skill_tokens`
- `compact_summary_tokens`
- `working_context_tokens`
- `conversation_tokens`
- `current_user_message_tokens`
- `tool_schema_tokens`
- `tool_history_tokens`

## 11.2 User-facing builtin stays compact

The builtin should keep returning a compact operator-friendly result, not a raw accounting dump.

---

## 12. Builtin Contract Evolution

## 12.1 Keep the action stable

Do not widen the surface.

Keep:

- tool family: `runtime`
- action: `context_status`

## 12.2 Upgrade the result semantics

Recommended result fields:

- `model_profile`
- `context_window`
- `effective_window`
- `estimated_current_input`
- `estimated_usage_percent`
- `estimate_source`
- `last_actual_input`
- `last_actual_output`
- `last_actual_total`
- `compaction_status`
- `latest_checkpoint`
- `summary`

Optional internal-only/debug fields may exist in diagnostics, not necessarily in the user-facing builtin result.

## 12.3 Summary contract

The builtin summary should explicitly reflect confidence.

Examples:

- high confidence:
  - current request estimate from tokenizer + last actual provider usage available
- degraded confidence:
  - rough fallback only

This avoids misleading the user into thinking a rough estimate is a precise measurement.

---

## 13. Testing Strategy

## 13.1 Unit tests

Must cover:

- provider usage extraction from OpenAI-compatible payloads
- tokenizer preflight estimate against final outbound payload
- fallback selection order: provider > tokenizer > rough
- builtin output semantics with and without actual usage
- compaction thresholds still derive from model metadata correctly

## 13.2 Regression tests

Must prove:

- current capability/runtime contracts do not drift
- natural-language runtime status queries still call `runtime.context_status`
- same-conversation serial execution remains intact
- compaction logic is not widened beyond current boundary

## 13.3 Live validation goals

Must prove in a real provider chain:

- normal turns increase estimated current input reasonably
- tool-heavy turns show larger preflight estimates than plain text turns
- provider actual usage is captured and surfaced when available
- runtime answers no longer rely on a misleading rough primary number when richer data exists

---

## 14. File Responsibility Map

### New files

- `src/marten_runtime/runtime/usage_models.py`
  - normalized usage data models
- `src/marten_runtime/runtime/token_estimator.py`
  - outbound-payload token estimation abstraction and family routing
- `tests/test_usage_estimator.py`
  - estimator selection and outbound-payload counting coverage
- `tests/test_runtime_usage.py`
  - normalized usage extraction and builtin usage-shape coverage

### Modified files

- `src/marten_runtime/runtime/llm_client.py`
  - add normalized provider usage extraction
  - compute preflight estimate against final payload
- `src/marten_runtime/runtime/history.py`
  - persist actual and estimated usage diagnostics
- `src/marten_runtime/runtime/loop.py`
  - record usage metadata into run history and tool context
- `src/marten_runtime/session/models.py`
  - persist latest actual usage at session scope
- `src/marten_runtime/session/store.py`
  - set/get latest usage metadata
- `src/marten_runtime/tools/builtins/runtime_tool.py`
  - return upgraded `context_status` payload
- `src/marten_runtime/runtime/tool_calls.py`
  - pass upgraded usage context where needed
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - wire estimator/runtime dependencies if needed
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - surface session-level latest usage into turn execution context if needed
- `src/marten_runtime/config/models_loader.py`
  - add optional tokenizer and usage capability metadata
- `config/models.toml`
  - annotate active profiles with tokenizer/usage metadata where appropriate
- `tests/test_models.py`
- `tests/test_runtime_loop.py`
- `tests/test_contract_compatibility.py`
- `tests/test_acceptance.py`

---

## 15. Alignment Check: Why This Design Does Not Drift

This design remains inside the approved theme and does **not** drift because:

- it keeps the existing `runtime` builtin rather than creating a new capability family per question
- it does not add memory retrieval, background summarizers, or planner logic
- it improves trust in the current compaction/runtime path rather than broadening product scope
- it follows the same core idea found in OpenCode, Codex, and Claude Code:
  - trust actual provider/runtime usage when possible
  - otherwise estimate the real payload
  - keep user-facing output concise and operator-meaningful
