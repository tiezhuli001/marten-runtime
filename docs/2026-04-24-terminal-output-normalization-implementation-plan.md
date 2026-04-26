# Terminal Output Normalization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** introduce one channel-aware terminal-output normalization boundary so the runtime keeps producing raw final text while storage, API visible text, and channel rendering all derive from one consistent normalized result.

**Architecture:** keep `RuntimeLoop` responsible only for `raw final text`. Add one terminal-output normalization boundary for terminal events (`final` / `error`) that takes `raw_text + channel_id + event_type` and returns `(visible_text, channel_payload)`. Keep channel rendering thin and channel-local: the shared interface is generic, while per-channel rules stay inside channel adapters. Feishu card rendering continues to consume raw text so existing card behavior remains stable.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, unittest, current HTTP/channel serialization path

---

## Source Documents

- Design reference:
  - `docs/2026-04-01-feishu-generic-card-protocol-design.md`
  - `docs/2026-04-22-generic-loop-finalization-contract-design.md`
- Continuity file:
  - `STATUS.md`
- Main implementation files:
  - `src/marten_runtime/channels/output_normalization.py`
  - `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - `src/marten_runtime/interfaces/http/channel_event_serialization.py`
  - `src/marten_runtime/channels/feishu/rendering.py`
  - `src/marten_runtime/channels/feishu/rendering_support.py`
- Main regression files:
  - `tests/test_gateway.py`
  - `tests/feishu/test_rendering.py`
  - `tests/test_feishu_rendering_support.py`

## Goal Lock

- **Target outcome:** remove protocol tail leakage such as stray ````` from persisted assistant text and channel payload text without regressing current Feishu card rendering.
- **Boundary:** interface/channel-finalization path only; no runtime loop prompt/contract/tool-selection changes.
- **Proof:** focused gateway + Feishu rendering tests, then one `/messages` Feishu-simulated smoke that verifies `visible_text`, stored history, and rendered card stay aligned.

## Locked Invariants

- `RuntimeLoop` continues to produce one `raw final text`.
- No new storage-specific Feishu text cleaner.
- One normalized `visible_text` must feed all non-rich-text sinks for the same terminal event:
  - persisted assistant history
  - top-level HTTP `result` / `final_text` / `text`
  - serialized event `payload.text`
- Channel rendering payloads stay derived from the same raw terminal event, not from re-hydrated stored text.
- Feishu card rendering keeps consuming raw text so current protocol parsing, fallback structured cards, and usage footer behavior remain unchanged.
- The normalization interface must be generic across channels; only the per-channel rule implementation may branch on `channel_id`.
- Default behavior for channels without explicit formatting protocol remains identity-style:
  - `visible_text = raw_text`
  - `channel_payload = None`
- Do not introduce a global cross-channel view framework.
- Do not widen this slice into runtime prompt changes, finalization-contract changes, or transport retries.

## Problem Statement

The current path already contains a Feishu-specific visible-text reducer (`history_visible_text(...)`), but it is not the single terminal-output normalization boundary and it does not fully scrub protocol residue after Feishu parsing succeeds. This creates split behavior:

- Feishu card content can be correct
- top-level text / event payload text / stored assistant history can still retain protocol tail artifacts
- different sinks can observe different terminal text shapes for the same event

The required fix is boundary cleanup, not another runtime contract change.

## Proposed Design

## 1. Introduce One Terminal-Output Normalization Interface

Create one interface-layer helper that accepts:

- `raw_text`
- `channel_id`
- `event_type`
- optional usage/run context when a channel payload needs it

and returns:

- `visible_text`
- `channel_payload`

This is the only terminal-output normalization entry point used by `_finalize_session_turn(...)` and per-channel event serialization.

Implementation ownership should live in one small shared module, for example:

- `src/marten_runtime/channels/output_normalization.py`

That keeps:

- runtime loop free of channel output logic
- `bootstrap_handlers.py` focused on response assembly
- `channel_event_serialization.py` focused on packaging

### Why this boundary is correct

- runtime stays channel-agnostic at the execution layer
- channel rules stay local to channel integrations
- storage/API/event payload all share one normalized visible text
- future channels can plug in their own visible-text or rich-payload rules without changing runtime contracts

## 2. Keep Channel Rules Channel-Local Behind the Shared Interface

The interface is generic. Rule implementations remain channel-local.

### Default channel behavior

- `visible_text = raw_text`
- `channel_payload = None`

### Feishu behavior

- derive `visible_text` through Feishu protocol parsing + visible-text cleanup
- derive `channel_payload` through current Feishu card rendering path

This keeps future non-Feishu channels free to opt into their own formatting contract later.

## 3. Promote Feishu Visible-Text Cleanup Into the Canonical Feishu Normalizer

Reuse the current Feishu text-reduction path instead of creating a second storage-only helper.

Current function:

- `src/marten_runtime/interfaces/http/channel_event_serialization.py::history_visible_text`

Refactor intent:

- move or rename it into a clearer Feishu-visible-text normalization helper owned by the Feishu channel boundary
- make it the single Feishu path for converting `raw_text -> visible_text`

### New cleanup scope

Beyond removing full `feishu_card` protocol blocks, it must also trim protocol residue left after successful parse, including:

- trailing standalone `````
- trailing standalone `feishu_card`
- trailing standalone `</invoke>`
- trailing standalone `</minimax:tool_call>`
- other parser leftovers that carry no user-visible meaning and are clearly protocol shell text

### Anti-regression guard

This cleanup must only remove recognized protocol-shell residue. It must not delete normal markdown code spans, legitimate fenced code blocks in plain answers, or visible prose.

## 4. Normalize Once In `_finalize_session_turn(...)`

`src/marten_runtime/interfaces/http/bootstrap_handlers.py::_finalize_session_turn(...)` should, for the terminal `final` / `error` event only:

1. read `terminal_raw_text`
2. call the unified normalization interface once
3. persist and return the resulting `visible_text`
4. attach any `channel_payload` returned by the normalizer

This removes current split handling where:

- history uses one transformation
- top-level HTTP text can still use raw text
- event serialization transforms again later

## 5. Keep Event Serialization Thin

`serialize_event_for_channel(...)` should consume normalized terminal output rather than re-deciding terminal text shape independently.

Preferred end state:

- terminal-event normalization happens once before response assembly
- event serialization only packages already-normalized outputs for channel delivery

If a small compatibility shim is temporarily needed, it should remain a pass-through over the new normalization interface rather than a second logic copy.

## File / Module Map

- `src/marten_runtime/channels/output_normalization.py`
  - own the generic terminal normalization contract
  - dispatch to channel-local visible-text / payload builders
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - compute terminal normalization once in `_finalize_session_turn(...)`
  - make top-level response text fields use normalized `visible_text`
- `src/marten_runtime/interfaces/http/channel_event_serialization.py`
  - stop owning independent Feishu text cleanup semantics
  - package already-normalized terminal output, with at most a thin compatibility delegation
- `src/marten_runtime/channels/feishu/rendering.py`
  - keep Feishu card parsing/rendering on raw text
  - host Feishu-specific visible-text normalization helper if that is the cleanest ownership boundary
- `src/marten_runtime/channels/feishu/rendering_support.py`
  - host small protocol-shell cleanup helpers if that keeps parsing/rendering code focused
- `tests/test_gateway.py`
  - lock top-level text fields, event payload text, and stored history alignment
- `tests/feishu/test_rendering.py`
  - lock protocol-shell cleanup behavior and card non-regression
- `tests/test_feishu_rendering_support.py`
  - lock helper-level cleanup edge cases if helper extraction happens

## Delivery Order

Implement in four chunks:

1. define the shared normalization boundary and invariants
2. move Feishu visible-text cleanup under that boundary and extend protocol-shell stripping
3. rewire finalize/serialization sinks to share one `visible_text`
4. run focused and end-to-end verification, then sync docs/status

## Chunk 1: Shared Normalization Boundary

### Task 1: Add the generic terminal-output normalization contract

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/interfaces/http/channel_event_serialization.py`
- Create: `src/marten_runtime/channels/output_normalization.py`
- Test: `tests/test_gateway.py`

- [ ] **Step 1: Write the failing tests**
  - add regression expectations that one terminal event yields one consistent visible text across:
    - top-level response `text`
    - top-level response `final_text`
    - event `payload.text`
    - persisted assistant history

- [ ] **Step 2: Run focused tests to verify failure**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_gateway
```

Expected:
- new assertions fail because visible text is still computed in multiple places

- [ ] **Step 3: Implement the normalization interface**
  - add one helper returning:
    - `visible_text`
    - optional `channel_payload`
  - keep default non-Feishu behavior identity-style
  - keep non-terminal events outside this helper so the slice stays narrow

- [ ] **Step 4: Re-run focused tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_gateway
```

Expected:
- new contract tests pass

## Chunk 2: Feishu Visible-Text Cleanup Consolidation

### Task 2: Reuse and strengthen the Feishu visible-text reducer

**Files:**
- Modify: `src/marten_runtime/channels/feishu/rendering.py`
- Modify: `src/marten_runtime/channels/feishu/rendering_support.py`
- Modify: `src/marten_runtime/interfaces/http/channel_event_serialization.py`
- Modify: `src/marten_runtime/channels/output_normalization.py`
- Test: `tests/feishu/test_rendering.py`
- Test: `tests/test_feishu_rendering_support.py`

- [ ] **Step 1: Write failing tests for protocol-shell residue**
  - cover exact stray-tail shapes:
    - short summary + trailing `````
    - short summary + trailing `</invoke>`
    - short summary + trailing `</minimax:tool_call>`
  - cover anti-regression:
    - plain markdown inline code remains
    - legitimate non-protocol prose remains

- [ ] **Step 2: Run focused tests to verify failure**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.feishu.test_rendering \
  tests.test_feishu_rendering_support
```

Expected:
- new residue-cleanup assertions fail before implementation

- [ ] **Step 3: Implement Feishu canonical visible-text cleanup**
  - reuse existing Feishu parsing path
  - extend it to remove only recognized protocol-shell residue
  - keep card rendering on raw text

- [ ] **Step 4: Re-run focused tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.feishu.test_rendering \
  tests.test_feishu_rendering_support
```

Expected:
- residue cleanup passes
- current Feishu rendering behavior stays green

## Chunk 3: Single Visible Text For Storage And Delivery

### Task 3: Rewire finalize and serialization sinks

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/interfaces/http/channel_event_serialization.py`
- Modify: `src/marten_runtime/channels/output_normalization.py`
- Test: `tests/test_gateway.py`

- [ ] **Step 1: Write failing gateway regressions**
  - verify one Feishu final reply stores and returns the same cleaned visible text in all sinks
  - verify card still contains detailed structured content

- [ ] **Step 2: Run focused tests to verify failure**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_gateway
```

Expected:
- new cross-sink consistency assertions fail before rewiring

- [ ] **Step 3: Implement single-source visible text flow**
  - compute normalized terminal output once in `_finalize_session_turn(...)`
  - persist `visible_text`
  - use `visible_text` for response text fields
  - use raw text only where channel payload rendering explicitly needs it

- [ ] **Step 4: Re-run focused tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_gateway
```

Expected:
- response, payload, and storage consistency assertions pass

## Chunk 4: Full Verification And Drift Check

### Task 4: Lock regression surface and verify the real chain shape

**Files:**
- Modify: `STATUS.md`
- Modify if needed: `docs/ARCHITECTURE_CHANGELOG.md`

- [ ] **Step 1: Run focused Feishu/gateway regression**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.feishu.test_rendering \
  tests.test_feishu_rendering_support \
  tests.test_gateway
```

Expected:
- all pass

- [ ] **Step 2: Run broader acceptance slice that covers channel output stability**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_acceptance \
  tests.contracts.test_gateway_contracts \
  tests.contracts.test_runtime_contracts
```

Expected:
- all pass

- [ ] **Step 3: Run Feishu-simulated smoke for the exact live chain**

Use `/messages` with:
- `channel_id = "feishu"`
- same ordered `time -> runtime -> mcp` request shape used in live validation

Verify:
- `llm_request_count` is preserved as expected for the chain
- top-level response `text/final_text/result` contain cleaned visible text
- serialized final event `payload.text` matches cleaned visible text
- rendered card still contains the detailed chain summary
- persisted assistant history matches cleaned visible text

- [ ] **Step 4: Sync continuity and architecture notes**
  - update `STATUS.md` with completed slice and proof
  - add `ARCHITECTURE_CHANGELOG.md` note only if the normalization boundary materially changes the documented interface path

## Non-Goals For This Slice

- changing `RuntimeLoop` finalization behavior
- changing prompt contracts or tool-selection behavior
- introducing a generic cross-channel renderer registry
- changing non-terminal event payload behavior
- rewriting Feishu card protocol shape
- changing usage-footer formatting
- moving channel formatting rules into runtime core

## Review Checklist

Use this checklist before implementation starts and after each chunk:

- Does the plan keep runtime output as `raw final text`?
- Is there exactly one normalized `visible_text` per terminal event?
- Are storage and user-visible plain text paths sharing the same normalized value?
- Does Feishu card rendering still consume raw text?
- Does the design stay generic at the interface boundary and channel-local in rule ownership?
- Does any new helper duplicate existing Feishu text cleanup instead of reusing it?
- Does any step risk changing current Feishu card layout or footer behavior?

## Final Acceptance Criteria

- no protocol-shell residue remains in stored assistant text for the affected Feishu paths
- no protocol-shell residue remains in top-level response text fields or final event payload text
- Feishu card rendering remains unchanged for currently covered shapes
- non-Feishu channels retain current text behavior
- all listed verification commands pass
