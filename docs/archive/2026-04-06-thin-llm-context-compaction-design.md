# 2026-04-06 Thin LLM Context Compaction Design

## 1. Purpose

This document proposes the next thin architecture slice for `marten-runtime`: a model-aware LLM context compaction layer for long-running sessions.

It is intentionally scoped as an **architecture evolution proposal**, not an implementation-complete memory platform.

The goal is to extend the current context-governance path:

`session history -> replay -> working_context -> LLM request`

into:

`session history -> replay + working_context -> optional LLM compaction -> compact summary + preserved recent tail -> LLM request`

without drifting into:

- session-memory platformization
- subagent memory workers
- planner/swarm orchestration
- cross-session memory systems
- generic knowledge-base infrastructure

---

## 2. Requirement Check Against User Intent

This design is based on the validated product direction plus the latest discussion about Codex / Claude Code compaction patterns.

### 2.1 Confirmed requirements

The proposed slice must satisfy all of the following:

- keep `marten-runtime` within the existing `harness-thin / workflow-light / LLM-first` boundary
- add one thin LLM compaction layer for long-thread continuity
- preserve current structured context governance as the first line of defense
- trigger compaction using **model-aware context pressure**, not a hard-coded one-size-fits-all token count
- avoid replacing or deleting runtime scaffolding such as:
  - system prompt
  - app bootstrap prompt
  - `AGENTS.md` / `SOUL.md` / `TOOLS.md` derived prompt assets
  - visible skill summaries and activated skill bodies
  - capability catalog text
  - MCP tool descriptions / tool schema exposure
- use a replacement strategy informed by strong prior art from Codex and Claude Code rather than inventing an ungrounded local pattern
- use the following user-provided compact prompt as the starting semantic contract:

> 你正在执行一次**上下文检查点压缩（Context Checkpoint Compaction）**。请为另一个将继续此任务的 LLM 创建一份交接摘要。  
> 需要包含：  
> - 当前进展以及已做出的关键决策  
> - 重要的上下文、约束条件或用户偏好  
> - 剩余需要完成的工作（明确的下一步）  
> - 为继续任务所需的关键数据、示例或参考信息  
> 要求：  
> 内容要**简洁、有结构，并以帮助下一个 LLM 无缝继续工作为目标**。

### 2.2 Interpreted outcome

The intended feature is **not** “summarize every turn.”

It is:

- keep normal turns cheap with rule-based governance
- only compact when the thread is clearly under context pressure or long-horizon continuity quality is degrading
- replace only the oversized conversation-history portion with a compact checkpoint
- keep the runtime’s active prompt/tool/skill scaffolding intact

---

## 3. What Strong Existing Systems Actually Do

## 3.1 Codex CLI pattern

Observed from the open-source `openai/codex` implementation:

- Codex has an explicit compact task and a compact prompt
- compaction is primarily used as a **checkpoint / handoff summary** for continuation
- it is triggered when token pressure is high enough **and** the task still needs follow-up work
- after compaction, Codex does **not** simply drop all context and keep only a summary string; it rebuilds a replacement history

What matters architecturally:

- compaction is a **history rewrite**, not a full runtime reset
- the replacement history is designed so the model can continue the task immediately
- initial/system/runtime context is reinjected outside the compacted history boundary as needed

## 3.2 Claude Code pattern

Observed from the reconstructed Claude Code source map:

- it uses several layers before and around compaction:
  - collapse / microcompact / transcript shaping
  - session memory extraction
  - full compact when context pressure becomes serious
- autocompact is model-window aware
- compact output becomes a new boundary plus compact summary plus preserved follow-up context
- session continuity data is treated separately from runtime scaffolding and tool exposure

What matters architecturally:

- prompt/tool scaffolding is not casually replaced by compaction
- recent raw context is often preserved alongside the compacted summary
- compaction is one layer in a broader context-management stack, not the only mechanism

## 3.3 Conclusion for `marten-runtime`

The strongest shared idea across both systems is:

> compact only the history layer, preserve runtime scaffolding, and continue with `summary + preserved recent context` rather than `summary only`.

That is the pattern this design adopts.

---

## 4. Current `marten-runtime` Baseline

Current context governance already provides:

- replay window selection
- noisy assistant replay suppression
- structured working-context derivation
- rendered `working_context_text`

This is the correct first layer and should remain the default path.

Current gaps:

- no model-aware token budget estimation
- no threshold-driven compact trigger
- no LLM-generated continuation checkpoint
- no replacement-history boundary after compaction
- no explicit distinction between:
  - compactable conversation history
  - non-compactable runtime scaffolding

---

## 5. Scope Of The Proposed Slice

## 5.1 In scope

- thin LLM compaction for long-running sessions
- model-aware compact trigger
- compact checkpoint artifact
- replacement-history assembly using:
  - compact summary
  - preserved recent tail
  - current runtime scaffolding
- diagnostics and tests proving compact path correctness

## 5.2 Explicitly out of scope

- background memory extraction agents
- session-memory markdown files
- cross-session memory promotion
- embeddings/vector retrieval
- new orchestration buses
- planner-driven summarization workflows

---

## 6. Architecture Decision

## 6.1 Use a two-layer governance strategy

### Layer 1: cheap rule-based governance

Continue to use the existing path on most turns:

- replay trimming
- noisy transcript suppression
- structured working context

### Layer 2: optional LLM compaction

When context pressure or continuity complexity crosses a threshold:

- create a compact checkpoint
- replace the oversized history prefix with the checkpoint
- preserve a short raw tail for immediate continuity

This keeps normal turns cheap while still allowing long sessions to survive.

---

## 7. Non-Compactable vs Compactable Context Boundaries

This is the most important correctness rule.

## 7.1 Non-compactable runtime scaffolding

These surfaces must **not** be swallowed into the compact-replacement process and must continue to be injected through the normal runtime path:

- selected agent `system_prompt`
- app bootstrap prompt and manifest-derived prompt assets
- `AGENTS.md` / `SOUL.md` / `TOOLS.md` assembled startup instructions
- visible skill summary text
- activated skill bodies
- capability catalog text
- MCP tool descriptions and live tool schemas
- selected agent identity (`agent_id`, `app_id`, `prompt_mode`, tool surface)

These are runtime scaffolding, not chat history.

## 7.2 Compactable conversation state

Only the following should be compacted/replaced:

- older user/assistant conversational history
- older tool-heavy assistant result narration embedded in assistant text
- old intermediate reasoning/results that no longer need verbatim replay

## 7.3 Preserved recent tail

A compacted turn should still preserve a small raw tail from the recent session history, for example:

- the most recent `2-6` replayable messages
- always preserving the last real user message prior to the current one when available

This follows the same broad safety shape seen in Codex / Claude Code:

- keep the runtime scaffolding intact
- rewrite older history
- preserve the most recent raw conversational continuity

---

## 8. Trigger Strategy

## 8.1 Do not use one fixed token number for all models

A global fixed threshold such as `200k` is not a good primary trigger because:

- on a `256k` model it may already be too late
- on a `1M` model it may be far too early
- system/tool/prompt overhead differs by runtime and provider

## 8.2 Use model-aware effective window estimation

Each model profile should be able to expose:

- `context_window_tokens`
- `reserve_output_tokens`
- `compact_trigger_ratio`

Then compute:

- `effective_window = context_window_tokens - reserve_output_tokens`
- `trigger_threshold = effective_window * compact_trigger_ratio`

Recommended defaults if unknown:

- `context_window_tokens = 200000`
- `reserve_output_tokens = 16000`
- `compact_trigger_ratio = 0.80`

This means `200k` is a **fallback for unknown models**, not the universal rule.

## 8.3 Trigger levels

### Advisory zone
- estimated input >= `60%` of effective window
- emit diagnostics only

### Proactive compact zone
- estimated input >= `80%` of effective window
- compact before the next normal turn

### Reactive compact zone
- provider responds with prompt-too-long / context-overflow style failure
- compact immediately and retry the turn once

## 8.4 Follow-up condition

Following Codex’s spirit, proactive compact should prefer sessions where there is clear continuation demand, for example:

- current turn is part of an unfinished task
- there are open todos / pending risks / active goal continuity
- the assistant is likely to need another turn to continue

This avoids compacting solved one-shot turns unnecessarily.

---

## 9. Compaction Prompt Strategy

## 9.1 Use the user-provided prompt as the semantic baseline

The user-provided prompt is strong and already aligned with the intended checkpoint pattern.

It should be preserved as the semantic core.

## 9.2 Thin runtime adaptation

For `marten-runtime`, add only the minimum extra constraints needed for machine-safe continuation:

- state that the output is for replacing oversized conversation history only
- forbid modifying/redefining runtime scaffolding
- prefer concise structure over long prose
- preserve technical anchors such as file names, module names, API names, config keys, and critical error labels when present
- do not repeat details that remain in the preserved recent tail

## 9.3 Recommended prompt draft

```text
你正在执行一次**上下文检查点压缩（Context Checkpoint Compaction）**。
请为另一个将继续此任务的 LLM 创建一份交接摘要。

这个摘要的用途是：
- 替换过长的旧会话历史
- 帮助后续模型无缝继续当前任务
- 不是用来替换 system prompt、skill 描述、MCP 工具描述或 app/bootstrap 提示词

需要包含：
- 当前进展以及已做出的关键决策
- 重要的上下文、约束条件或用户偏好
- 剩余需要完成的工作（明确的下一步）
- 为继续任务所需的关键数据、示例或参考信息

要求：
- 内容要简洁、有结构，并以帮助下一个 LLM 无缝继续工作为目标
- 只保留继续工作真正需要的信息，不要复述所有历史
- 不要虚构未发生的事实
- 不要保留纯噪音工具日志
- 如有关键文件、模块、接口、报错、配置项，请保留这些技术锚点
- 如果最近几条消息仍会被保留，请不要重复展开这些最近尾部细节

建议输出结构：
- 当前进展
- 关键决策
- 约束/偏好
- 关键数据/参考
- 剩余工作
- 明确下一步
```

This keeps the user’s prompt intact while making the runtime-safe boundary explicit.

---

## 10. Compaction Output Shape

Use a structured internal artifact even if the compaction model returns text.

Recommended internal shape:

- `summary_text`
- `primary_request`
- `active_goal`
- `key_decisions[]`
- `user_constraints[]`
- `completed_results[]`
- `failed_attempts[]`
- `open_todos[]`
- `pending_risks[]`
- `important_refs[]`
- `next_step`
- `source_message_range`

The runtime may initially parse conservatively and only require:

- `summary_text`
- `open_todos`
- `pending_risks`
- `next_step`

but the artifact shape should leave room for later strengthening without redesign.

---

## 11. Replacement Strategy After Compaction

## 11.1 Do not replace the entire runtime input

The post-compaction turn should be assembled from these layers:

### A. Normal runtime scaffolding (unchanged)
- system prompt
- app/bootstrap prompt assets
- skill summaries / activated skill bodies
- capability catalog
- MCP tool surface

### B. Compacted checkpoint summary
- injected as a dedicated continuation block
- stands in for the older conversation prefix

### C. Preserved recent tail
- small number of recent raw conversation messages
- kept verbatim for local continuity

### D. Current working context
- existing structured working context can still be rendered and injected
- may later absorb fields from compact output if useful

### E. Current user message
- always appended normally

## 11.2 Why this is the right replacement pattern

This follows the strongest shared pattern from Codex and Claude Code:

- replace only the oversized history layer
- preserve task-continuity summary
- preserve a recent raw tail
- keep runtime scaffolding injected through its normal path

## 11.3 Boundary rule

The compact checkpoint should become the semantic replacement for the **older conversation prefix**, not for the entire prompt stack.

That distinction must be explicit in code and tests.

---

## 12. Proposed File-Level Evolution

## 12.1 New modules

- `src/marten_runtime/session/compaction_trigger.py`
  - model-aware pressure estimation
  - proactive/reactive trigger decisions

- `src/marten_runtime/session/compaction_prompt.py`
  - prompt builder
  - summary wrapper helpers

- `src/marten_runtime/session/compacted_context.py`
  - compacted artifact model
  - render helpers

- `src/marten_runtime/session/compaction_runner.py`
  - execute compact request against LLM client
  - parse/store compact result

## 12.2 Modified modules

- `src/marten_runtime/config/models_loader.py`
  - optional model-window metadata

- `src/marten_runtime/runtime/context.py`
  - assemble post-compact runtime context
  - merge compact summary + recent tail + current working context

- `src/marten_runtime/runtime/loop.py`
  - before the main completion call, decide whether compaction is needed
  - if reactive overflow occurs, compact once and retry once

- `src/marten_runtime/session/store.py`
  - persist latest compact artifact per session
  - track compaction generation / timestamp

- `src/marten_runtime/runtime/llm_client.py`
  - provide a rough token estimator helper
  - possibly expose compaction-call request shape reuse

- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - wire a compaction-capable client path
  - optionally allow compaction to use a cheaper profile later

---

## 13. Verification Plan

The implementation must be locked by tests before being considered complete.

### 13.1 Trigger correctness
- compact does not trigger on short sessions
- compact triggers by ratio, not fixed universal token count
- unknown model profiles fall back to a conservative default

### 13.2 Boundary correctness
- compact replacement does **not** remove:
  - system prompt
  - bootstrap prompt
  - skill heads / activated skill bodies
  - capability catalog text
  - MCP tool descriptions
- compact replacement **does** rewrite oversized conversation history prefix

### 13.3 Continuation correctness
- after compact, the next request still sees:
  - compact summary
  - preserved recent tail
  - current message
- the model can continue from unfinished tasks without losing constraints and next step

### 13.4 Reactive recovery
- when provider returns prompt-too-long-like failure, the runtime compacts once and retries once
- if retry still fails, the controlled error surfaces cleanly

### 13.5 Acceptance coverage
- long coding-style thread survives compaction and continues with correct agent/app/tool surfaces intact

---

## 14. Why `marten-runtime` Should Add This Layer Now

The current rule-based governance is enough for short and medium sessions, but it will eventually underperform in the exact long-thread scenarios the runtime is evolving toward:

- coding-style execution threads
- multi-step debugging
- extended operator conversations
- private-agent sessions that need continuity over many turns

Adding a **thin compaction layer now** is the smallest next architecture move that:

- preserves the existing MVP boundary
- aligns with strong prior art
- avoids premature platformization
- materially improves long-thread survivability

---

## 15. Final Recommendation

`marten-runtime` should adopt the following direction:

- keep current replay + working-context governance as the default path
- add one thin, model-aware LLM context compaction layer
- trigger by effective-window ratio rather than a single fixed token number
- use the user-provided Codex-style checkpoint prompt as the baseline, with minimal runtime-boundary additions
- replace only the old conversation-history prefix
- preserve runtime scaffolding and a recent raw tail
- defer full session-memory systems until real product pressure proves they are necessary

This is the recommended architecture evolution path.
