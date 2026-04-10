# 2026-04-07 LLM Tool Episode Summary Design

## 1. Purpose

This document tightens the earlier thin cross-turn tool continuity slice for `marten-runtime`.

The earlier implementation proved the product value of a small cross-turn summary sidecar, but the first extraction strategy leaned too heavily on rules derived from tool payload structure. That approach is acceptable as a fallback, but it is not the best primary design because it can lose the *goal* of the tool turn:

- why the tool was called
- what question the tool episode was trying to answer
- what conclusion the assistant reached after seeing the tool results
- which parts of the result are still safe to carry into the next turn

The new design keeps the thin harness boundary intact while replacing the rules-first extraction path with a **post-turn LLM tool-episode summary** path.

The target is still intentionally narrow:

- preserve same-turn correctness
- improve cross-turn continuity for builtin / MCP / skill turns
- avoid replaying raw tool transcript noise into future requests
- avoid turning runtime into a memory platform

It is **not** a planner, retrieval, or durable-memory architecture.

---

## 2. Requirement Check Against The Latest Discussion

### 2.1 Confirmed user intent

From the latest discussion, the target behavior is:

- do **not** let the main agent be drowned by historical tool transcript noise
- do **not** pretend raw tool outputs can always be reduced with growing handcrafted rules
- keep the implementation thin and harness-aligned
- preserve the model's understanding of **what this tool turn accomplished**, not only a handful of extracted fields
- accept a small amount of extra LLM work if it materially improves semantic continuity
- avoid engineering sprawl for a non-primary chain optimization

### 2.2 Product interpretation

The right question is not:

> How do we engineer enough rules to parse every possible tool output?

The right question is:

> How do we preserve the minimum semantic continuation signal from a completed tool-bearing turn while keeping the runtime thin?

That leads directly to a post-turn summary of the **tool episode** rather than a rules-only parser of the **tool result**.

---

## 3. Architecture Decision

## 3.1 Keep the existing same-turn boundary unchanged

Same-turn behavior remains exactly as it is today:

- the assistant decides to call tool(s)
- the runtime sends the tool call(s)
- tool result(s) are injected back into the same turn's follow-up request
- the assistant produces the final answer for that turn

This is still the correctness path for tool use. The new feature must not alter it.

## 3.2 Change only the cross-turn continuity path

Cross-turn continuity should become:

- replayed history: `user/assistant` only
- plus one thin summary sidecar generated from the most recent relevant tool-bearing turn(s)

This means:

- **same turn** keeps full tool protocol state
- **later turns** do not replay raw tool transcripts
- **later turns** may receive one small LLM-generated summary block

## 3.3 Use LLM summary as the primary extractor

After a turn completes and only if the turn included at least one successful tool call, the runtime may run a **small post-turn LLM summarizer** over the completed tool episode.

The summarizer should see the tool episode, not just the raw tool result.

Minimum summary input:

- current user message
- assistant tool calls for the turn
- tool results for the turn
- assistant final reply for the turn

This lets the summarizer infer:

- the tool-use intent
- the final resolved answer
- which facts matter for future continuity
- whether the result is too volatile to preserve

## 3.4 Keep a minimal fallback extractor

A tiny deterministic fallback remains necessary when:

- summarizer model is unavailable
- summarizer call times out
- summarizer returns invalid JSON
- the tool turn is too small to justify the extra call

But this fallback is **not** the primary design. It should only provide a thin degraded behavior such as:

- `调用了 runtime.context_status，已得到上下文状态。`
- `调用了 github MCP，已获得查询结果。`
- `已加载 skill feishu_channel_formatting。`

The fallback must not keep expanding into a tool-specific parser matrix.

---

## 4. Why This Is Better Than The Earlier Rules-First Plan

## 4.1 Rules lose turn intent too easily

Rules operating only on the tool payload/result may capture fields like:

- `repo`
- `branch`
- `issue_count`

but still miss:

- whether the assistant was validating a claim
- whether the assistant was comparing candidates
- whether the result was provisional or final
- whether the assistant told the user this result is time-sensitive

## 4.2 The final assistant reply is part of the truth

The completed turn already contains the assistant's synthesis. That synthesis is often a better candidate for later continuity than any raw tool field.

A post-turn summarizer can preserve that synthesis while dropping the protocol noise.

## 4.3 This remains thin if the output contract is small

This design does **not** require large new memory layers if we keep:

- one small JSON schema
- one bounded session sidecar
- one bounded reinjection block
- one small fallback path

That is still compatible with the current harness philosophy.

---

## 5. Non-Goals

Explicitly out of scope:

- replaying raw tool transcript across turns
- vector retrieval / embeddings
- cross-session memory promotion
- background summarization workers
- a general durable memory platform
- summarizing every non-tool turn
- planner-driven tool narration
- automatic subagentization of all tool usage

---

## 6. Why Subagents Are Not The Primary Solution Here

Subagents are useful for very tool-heavy workflows, but they do not remove the need for a continuity artifact.

Even if a subagent performs the tool work, the parent agent still needs a thin answer to:

- what did that tool-heavy effort accomplish?
- what is safe to remember next turn?
- what should be refreshed if asked again?

So the correct relationship is:

- subagentization is an **optional future optimization** for tool-heavy workflows
- thin outcome summary remains the cross-turn continuity mechanism

For this slice, the design should remain inside the current main runtime path.

---

## 7. Tool Episode Definition

A **tool episode** is the smallest completed unit that should be summarized.

For v1, define one episode as:

- one user turn
- one assistant decision to use tools
- zero or more tool calls/results produced before the turn completes
- the assistant's final natural-language reply for that turn

If a turn has no successful tool call, there is no tool episode summary.

If a turn uses multiple tools, summarize them as **one episode**, not as unrelated fragments.

That keeps the summary aligned with user intent rather than protocol structure.

---

## 8. Summary Data Contract

The persisted sidecar should stay intentionally small.

Suggested model:

- `summary_id`
- `run_id`
- `created_at`
- `source_kind` (`builtin` | `mcp` | `skill` | `mixed` | `other`)
- `summary_text`
- `facts`
- `volatile`
- `keep_next_turn`
- `refresh_hint`
- `token_estimate`

### 8.1 `summary_text`

One short sentence or two short clauses capturing the episode outcome.

Example:

- `上一轮通过 github MCP 查询了 CloudWide851/easy-agent，确认仓库存在，默认分支为 main。`

### 8.2 `facts`

Optional structured facts, capped very tightly.

Suggested cap:

- at most 3 facts
- short string values only

Examples:

- `repo=CloudWide851/easy-agent`
- `default_branch=main`

### 8.3 `volatile`

Marks whether the result is time-sensitive enough that it should not be trusted on a later turn without refresh.

Examples that should usually be volatile:

- current time
- trending lists
- rapidly-changing counts
- queue depth / online state / dynamic status

### 8.4 `keep_next_turn`

Whether to reinject this summary into the very next turn by default.

Rules:

- `false` for clearly volatile tool results such as `time`
- `true` when the episode produced stable continuity facts

### 8.5 `refresh_hint`

Optional short instruction for later behavior.

Example:

- `若用户再次询问当前时间，应重新调用工具。`

This field is for runtime-managed continuity text, not for a general agent planning layer.

---

## 9. Summarizer Output Schema

The summarizer must be forced into a tiny JSON schema.

Recommended schema:

```json
{
  "summary": "string",
  "facts": [
    {"key": "string", "value": "string"}
  ],
  "volatile": true,
  "keep_next_turn": false,
  "refresh_hint": "string"
}
```

Hard limits:

- `summary`: <= 220 chars target
- `facts`: <= 3 items
- each value short enough for prompt reinjection
- `refresh_hint`: optional, <= 120 chars target

If schema validation fails, discard the LLM result and fall back.

---

## 10. Summarizer Prompt Contract

The summarizer prompt should be intentionally narrow.

It should instruct the model to do only this:

- infer what the tool episode was trying to achieve
- summarize the outcome for future continuity
- keep only facts that are likely useful on the next turn
- mark volatile results so they are not reused as truth
- never copy large tool outputs or JSON blobs

The prompt must explicitly forbid:

- long summaries
- policy narration
- speculative facts not grounded in the episode
- storing full tool payloads
- preserving high-churn facts as durable memory

This should be a small dedicated prompt, not a large framework.

---

## 11. Reinjection Contract

The rendered reinjection block remains thin.

Recommended shape:

```text
Recent tool outcome summary:
- 上一轮通过 github MCP 查询了 CloudWide851/easy-agent，确认仓库存在，默认分支为 main。
```

Or if multiple recent summaries survive budget trimming:

```text
Recent tool outcome summaries:
- 上一轮调用 runtime.context_status，确认当前估算约 2694/245760 tokens，本轮峰值主要来自工具结果注入后。
- 上一轮通过 github MCP 查询了 CloudWide851/easy-agent，确认仓库存在，默认分支为 main。
```

Rules:

- no raw JSON
- no code fences
- no raw tool transcript
- no more than 1-3 short lines total
- omit volatile summaries by default

Placement remains near the current continuity scaffolding, alongside:

- compact summary text
- working context text

It must not replace:

- system prompt
- skill bodies
- capability catalog
- live tool schema exposure

---

## 12. Budgeting And Retention

Keep very little.

Recommended v1 limits:

- persist at most 3 recent episode summaries
- render at most 2 summaries into the next request
- reinjection budget target: ~80-180 tokens total

Selection order:

1. newest first
2. non-volatile first
3. summaries with short facts first
4. drop anything noisy or stale

This is enough to support multi-turn continuity without becoming another context sink.

---

## 13. When To Run The Summarizer

Run only after a tool-bearing turn completes successfully enough to produce a final assistant reply.

Do **not** run on:

- plain non-tool turns
- partial/incomplete tool execution
- tool failures with no meaningful continuity value
- turns already marked too small / too cheap to summarize if the runtime introduces a small heuristic gate

This keeps the feature thin and cost-bounded.

---

## 14. Model / Cost Strategy

This feature is not the main chain. Cost and latency must stay secondary.

Recommended policy:

- use a small summarizer-capable model profile
- keep the prompt tiny
- keep the input slice narrow to the completed episode only
- allow disable-by-config
- allow fallback-only mode

The main user-visible runtime path must still work if summary generation is skipped.

---

## 15. Failure Semantics

If summarization fails:

- do not fail the user turn
- do not change same-turn semantics
- do not persist broken artifacts
- fall back to a tiny deterministic summary or nothing

If the summary is noisy:

- drop it
- prefer omission over bad memory

---

## 16. Interaction With Volatile Tools

This design directly addresses the `time`-style concern.

### `time` example

The summarizer may produce:

- `summary`: `上一轮调用了 time 工具获取当前时间。`
- `volatile`: `true`
- `keep_next_turn`: `false`
- `refresh_hint`: `若再次询问当前时间，应重新调用工具。`

Result:

- the runtime does **not** inject stale time into the next turn
- a later user asking again should still trigger the tool

This keeps continuity about *what happened* without fossilizing stale values.

---

## 17. Interaction With Skills

Skill turns should be handled the same way as any other tool episode.

Important boundary:

- do not persist the skill body itself
- do allow the summarizer to note that a skill was loaded and why it mattered to the turn

Example:

- `上一轮加载了 feishu_channel_formatting skill，用于生成符合渠道格式的回复。`

This preserves continuity without replaying `SKILL.md` contents.

---

## 18. Minimal Fallback Contract

The fallback path should be intentionally weak.

It may use only:

- tool family / name
- success/failure state
- maybe one very short obvious fact already available in the final assistant reply or canonical result fields

Examples:

- `上一轮调用了 runtime.context_status，并已返回上下文状态。`
- `上一轮调用了 github MCP，并获得了查询结果。`
- `上一轮加载了 skill feishu_channel_formatting。`

The fallback must not continue expanding toward a pseudo-semantic parser for every external tool.

---

## 19. Implementation Shape

The implementation should stay structurally close to what already exists.

### Keep

- session sidecar persistence
- bounded reinjection block
- current history replay boundary (`user/assistant` only)
- current same-turn tool follow-up semantics

### Replace / shrink

- replace the current rules-first extractor path with an LLM-summary-first path
- shrink the deterministic extractor to a small fallback helper
- remove growing tool-specific extraction branches that are not justified by thin-harness scope

This keeps the amount of new engineering low while correcting the main semantic weakness.

---

## 20. Verification Goals

The design is only successful if all of the following are true:

1. same-turn tool behavior is unchanged
2. next-turn continuity improves for real multi-turn builtin / MCP / skill scenarios
3. volatile results are not incorrectly reused as durable truth
4. the reinjection block stays small
5. failure of summarization does not break the user turn
6. implementation complexity is lower than a growing rules matrix

---

## 21. Final Decision

For `marten-runtime`, the right thin design is:

- **same-turn:** keep full tool protocol for correctness
- **cross-turn:** inject only a thin continuity summary
- **summary source:** use a post-turn **LLM tool-episode summarizer** as the primary path
- **fallback:** keep a very small deterministic degraded path
- **scope:** remain session-local, budgeted, and non-platformized

This is the smallest design that preserves "what the tool turn accomplished" without overbuilding the runtime.
