# Feishu Generic Card Protocol Design

## Goal

Introduce one optional, minimal Feishu-facing structure protocol that the model may emit when a reply benefits from card presentation, while keeping the runtime aligned with:

- LLM first
- thin harness
- skill and prompt guidance over host-side intent routing
- one generic renderer instead of business-specific renderer proliferation

This design is specifically for the Feishu outbound path in `marten-runtime`. It does not introduce a general cross-channel view system, a renderer registry keyed by business type, or a new tool surface.

## Problem

The current Feishu path already works, but its presentation ceiling is low:

- plain text inside one generic card is safe but visually flat
- relying only on unconstrained natural-language formatting gives limited control over hierarchy
- placing both rendering logic and delivery logic in `delivery.py` mixes concerns and leaves no clean home for visual iteration

The user explicitly rejected:

- one renderer per business type
- delivery-layer semantic classification
- system-prompt-heavy channel rules
- heavy `openClaw`-style Feishu card engineering

The current direction is:

- default to natural language
- let the model decide whether extra structure is worthwhile
- keep the runtime limited to optional parsing plus one generic card skeleton
- move rendering responsibilities out of `delivery.py`

## Design Summary

The assistant continues to answer in natural language by default.

When the model believes the reply is naturally card-shaped, it may append one optional structured block at the end of the final answer:

```text
```feishu_card
{ ...small JSON object... }
```
```

The runtime then uses three distinct responsibilities:

1. **LLM / skill layer**
   - decide whether structured output is worth using
   - emit natural language first
   - optionally append one trailing `feishu_card` block

2. **Generic renderer**
   - detect and parse the optional block
   - validate against a very small schema
   - remove the protocol block from the visible answer body
   - map valid structured output into one generic Feishu card skeleton
   - fall back safely when parsing fails or structure is absent

3. **Delivery layer**
   - select `text` vs `interactive` transport shape by event type
   - call the renderer for final replies
   - keep retry, update, dedupe, dead-letter, and send semantics unchanged

The runtime does not decide whether a reply is a task card, rule card, checklist card, or any other business type. That decision stays with the model. The runtime only knows one optional structure protocol and one generic renderer.

## Protocol

### Transport Shape

The optional structure is embedded inside the final model text as a fenced code block with info string `feishu_card`.

Example:

````text
当前有 3 个任务，其中 2 个进行中。

```feishu_card
{
  "title": "当前任务",
  "summary": "共 3 项，2 项进行中",
  "sections": [
    {
      "title": "任务列表",
      "items": [
        "修复 Feishu 入站解析",
        "补齐全链路耗时埋点",
        "完成真实链路回归"
      ]
    }
  ]
}
```
````

The visible answer remains readable even if the protocol block is ignored. The structured block is an enhancement, not the primary carrier of meaning.

### Minimal Schema

The protocol intentionally supports only a tiny field set:

```json
{
  "title": "string, optional",
  "summary": "string, optional",
  "sections": [
    {
      "title": "string, optional",
      "items": ["string", "string"]
    }
  ]
}
```

Schema rules:

- `title`
  - optional
  - single short line
- `summary`
  - optional
  - one to two short lines
- `sections`
  - optional array
  - each section may have an optional short `title`
  - each section may have `items`
- `items`
  - array of plain strings only
  - no nested objects
  - no metadata fields like status, ids, colors, icons, actions, timestamps as structured keys

### Hard Limits

To prevent protocol creep, the first version explicitly does not support:

- nested sections
- tables
- buttons
- actions
- forms
- per-item metadata objects
- arbitrary markdown fragments per section
- raw Feishu card JSON
- channel-independent card abstractions

If future needs exceed these limits, the design should first prove that the need is generic before expanding the schema.

## Model Responsibility

The model remains responsible for deciding whether the optional structured block is worth emitting, within the current Feishu channel constraints.

### Default Behavior

Default behavior is:

- a one-line direct answer may stay plain text
- multi-line, grouped, or list-like Feishu replies should end with one trailing `feishu_card`

The model should append `feishu_card` when the reply naturally fits a compact structured presentation, such as:

- grouped task lists
- checklist or verification output
- candidate rules or options
- status summaries with a few grouped bullets
- result sets that are easier to scan than read as prose

The model may omit the block for:

- single-fact answers
- short conversational replies
- cases where valid JSON cannot be produced confidently

### Skill Guidance

The Feishu formatting skill should remain extremely thin. It should tell the model:

- one-line direct answers may stay plain text
- everything else should end with one trailing `feishu_card`
- visible text must stay to one short summary line when `feishu_card` is present
- visible bullet duplication outside `feishu_card` is not allowed
- the JSON must restate information already present in the answer
- if uncertain, omit the block

This preserves the repo's LLM-first boundary. The harness exposes one thin channel constraint plus one generic renderer; the model still decides the final card content.

## Runtime Responsibility

### Renderer Boundary

The generic renderer should live beside the Feishu channel code, but outside delivery transport logic.

Recommended file boundary:

- `src/marten_runtime/channels/feishu/rendering.py`

The renderer owns:

- trailing `feishu_card` block detection
- schema validation
- structured parse result types
- fallback decision for malformed blocks
- generic visual skeleton assembly
- final Feishu interactive-card JSON generation for final replies

The renderer must not:

- infer business type from plain text
- choose among multiple business renderers
- synthesize missing semantics from prose
- expose internal runtime metadata
- grow into a channel-agnostic UI framework

### Delivery Boundary

`delivery.py` remains a post-processing and transport adapter. It must not become a semantic renderer.

Allowed responsibilities:

- call the renderer for final replies
- keep event-type transport selection
- preserve retry, update, send, dedupe, and dead-letter semantics

Disallowed responsibilities:

- protocol parsing
- card skeleton construction
- visual hierarchy decisions
- reply-type branching
- business-specific layout branches

### Parsing Contract

Detection rules:

- only inspect final visible text for `event_type == "final"`
- only parse a trailing fenced block with info string exactly `feishu_card`
- ignore non-trailing blocks to reduce accidental captures

Parsing rules:

- JSON object only
- reject invalid JSON
- reject unsupported keys
- reject wrong field types
- reject deeply nested structures

Failure behavior:

- log a compact parse failure reason
- ignore the structured block entirely
- render the reply with the existing text-card fallback

This failure mode is intentionally forgiving. The protocol should never break user-visible delivery.

## Generic Renderer Skeleton

The runtime owns exactly one generic Feishu rendering skeleton for protocol-backed replies.

Suggested slots:

1. optional header title
2. optional summary area
3. zero or more sections
4. each section:
   - optional short section title
   - flat item list
5. optional lightweight footer hint only if it is generic and user-visible

This is not a content taxonomy. It is one stable skeleton with optional slots.

### Rendering Principles

- compact first
- scan-friendly over decorative
- obvious hierarchy over raw markdown dump
- no attempt to mimic a dashboard or workflow engine
- no business semantics in the host
- keep Feishu payload construction deterministic and low-risk

The card should feel more intentional than plain text, but not smarter than the model.

## Testing Strategy

The protocol and renderer should be validated with narrow tests, not broad UI simulation.

### Unit Tests

Add tests for:

- trailing `feishu_card` block detection
- valid minimal block parse
- parse failure on invalid JSON
- parse failure on invalid field types
- parse failure on unsupported keys
- removal of the structured block from visible body
- fallback behavior when the block is malformed

### Renderer Tests

Add tests that lock:

- plain final reply renders through the generic fallback skeleton
- structured final reply renders through the same generic skeleton with populated title, summary, and sections
- visual-slot ordering is stable
- no business-specific renderer switching exists

### Delivery Tests

Add tests that lock:

- `delivery.py` delegates final rendering to the renderer
- retry/update/send behavior does not change
- dedupe/dead-letter behavior does not change

### Skill Contract Tests

Keep skill verification narrow:

- Feishu always-on skill remains thin
- skill text allows plain text only for one-line direct answers
- skill text requires one trailing `feishu_card` for multi-line or grouped Feishu replies

## Risks

### Risk 1: The model emits malformed JSON

Mitigation:

- trailing-block-only detection
- strict schema validation
- safe fallback to plain text card

### Risk 2: The model overuses the protocol

Mitigation:

- keep the rule narrow: one-line direct answers may remain plain text
- require `feishu_card` only for multi-line or grouped Feishu replies
- avoid expanding the schema or adding business-specific renderers

### Risk 3: The renderer grows into a hidden rendering framework

Mitigation:

- freeze the minimal field set
- keep exactly one generic skeleton
- reject business-specific layout branches
- keep delivery and renderer responsibilities separate

## Non-Goals

This design does not attempt to:

- replicate `openClaw` streaming card UX
- introduce typed renderer families like task card, rules card, checklist card
- build a cross-channel structured response standard
- move message beautification into system-prompt-heavy host logic
- make `delivery.py` reason about semantics
- replace natural language as the default final answer format

## Acceptance Criteria

This design is considered successful when all of the following are true:

- replies without protocol blocks behave exactly as they do today
- replies with valid protocol blocks render through one generic renderer path
- malformed protocol blocks never break delivery
- `delivery.py` no longer contains protocol parsing or card skeleton construction
- the generic renderer is the only owner of Feishu card visual structure
- the Feishu skill remains short and enforces the one-line-plain-text / otherwise-structured Feishu rule
- real Feishu output is visibly cleaner for list-like replies without widening the architecture

## Source Alignment

This design aligns with:

- `docs/archive/plans/2026-04-01-feishu-message-pipeline-unification-plan.md`
- `docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md`
- `docs/architecture/adr/0001-thin-harness-boundary.md`
- `docs/architecture/adr/0002-progressive-disclosure-default-surface.md`
