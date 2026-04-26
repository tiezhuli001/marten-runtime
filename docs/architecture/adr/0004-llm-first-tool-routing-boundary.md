# ADR 0004: LLM-First Tool Routing Boundary

- Status: Accepted
- Date: 2026-04-22

## Context

ADR 0001 established that `marten-runtime` is a thin harness, and ADR 0002 established that capability exposure is progressive-disclosure-first.

Recent iterations had added request-specific tool-surface narrowing and natural-language matchers in places such as:

- `src/marten_runtime/runtime/llm_request_instructions.py`
- historical `src/marten_runtime/runtime/query_hardening.py`

That drift reintroduces a host-side intent router for ordinary natural-language requests across builtin families such as:

- `runtime`
- `time`
- `session`
- `automation`
- `mcp`
- `skill`
- `spawn_subagent`
- `self_improve`

Once the host starts classifying free-form user language into tool families, capability metadata stops being static declaration and starts becoming mutable routing policy. That shape conflicts with:

- thin-harness ownership
- progressive disclosure
- LLM-first capability selection

The project needs one durable boundary that future code changes can follow.

## Decision

Free-form natural-language tool selection belongs to the model.

The runtime remains responsible for model-visible capability declaration and machine-verifiable execution contracts.

### The Runtime Must Own

- capability catalog text, tool descriptions, usage rules, examples, and parameter schemas
- exact tool name and parameter-schema validation
- required-field, enum, and type validation
- permission, scope, ownership, and side-effect correctness checks
- live-data truth checks for claims about current time, current runtime state, or other freshness-bound answers
- session, channel, and delivery binding correctness
- tool execution, retry, recovery, and diagnostics
- structured protocol surfaces whose semantics are already explicit outside free-form language, such as channel action payloads, slash commands, buttons, and prior tool-followup state

### The Runtime Must Avoid

- host-side family routing for ordinary natural-language requests such as “当前上下文窗口多大”, “切换会话”, “看看定时任务”, “加载某个 skill”, or “查一下 GitHub”
- host-side routing that treats free-form tokens such as `sess_xxx`, “新开一个会话”, “子代理”, or sequential wording as sufficient reason to bypass model intent selection
- request-specific keyword or regex branching that narrows ordinary free-form language to one builtin family only because the host believes it understands the intent
- reintroducing a general intent-recognition helper layer after `query_hardening.py` has already been removed
- growing capability declarations or request-instruction helpers into a mutable router
- treating “the model may choose the wrong tool” as sufficient reason to add host-side natural-language classification

### Default Correction Path

When tool selection quality is weak, the default fix path is:

1. improve capability descriptions
2. improve examples and usage rules
3. tighten parameter schemas
4. improve prompt wording and capability catalog clarity
5. add acceptance coverage for the target user wording

Host-side natural-language routing is not the default correction path.

### Structured Exceptions

Deterministic binding is allowed when the upstream surface is already structured and machine-verifiable, for example:

- a slash command whose contract already names the action
- a button or card action payload
- a previous tool-followup turn that is already bound to the tool result from the same run
- transport-level enforcement for a required live tool call when the runtime is protecting freshness truth, not classifying free-form intent

These exceptions are contract enforcement. They are outside the free-form natural-language routing boundary.

## Consequences

- `llm_request_instructions.py` should shrink toward prompt assembly and contract hints, not grow into a natural-language router
- deleted host-side intent helpers should stay deleted unless a new structured contract requires a narrow replacement
- capability declarations should carry more of the model-facing clarity burden
- builtin tools with side effects should invest in clearer descriptions, examples, and schemas
- poor tool selection should first be treated as a model-facing contract-quality problem
- future reviews should reject host-side natural-language family routing growth unless the input surface is already structured and contract-owned

## References

- [ADR 0001: Thin Harness Boundary](./0001-thin-harness-boundary.md)
- [ADR 0002: Progressive Disclosure Default Surface](./0002-progressive-disclosure-default-surface.md)
- [Progressive Disclosure + LLM-First Capability Design](../../2026-03-31-progressive-disclosure-llm-first-capability-design.md)
- [Architecture Changelog](../../ARCHITECTURE_CHANGELOG.md)
