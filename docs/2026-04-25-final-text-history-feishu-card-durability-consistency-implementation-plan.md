# Final Text / History vs Feishu Card Body Durability Consistency Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make structured Feishu replies persist one durable plain-text form that preserves the same information content as the rendered card body, while the Feishu card lead stays compact and channel-local.

**Architecture:** keep the runtime loop producing one raw terminal text. Refine terminal-output normalization so it returns two text surfaces: `durable_text` for persistence and plain-text sinks, and `visible_text` for the Feishu-facing compact lead inside the rendered card. Keep Feishu card rendering sourced from `raw_text`; add one deterministic plain-text reconstruction path for structured Feishu replies so replay, compaction, restart, HTTP plain text, and diagnostics all consume the durable form.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, unittest, in-memory + SQLite session stores, current HTTP/channel serialization path

---

## Source Documents

- Continuity source of truth:
  - `/Users/litiezhu/docs/ytsd/工作学习/AI学习/handoff/HANDOFF_2026-04-25_MARTEN_RUNTIME_CURRENT_TURN_EVIDENCE_LEDGER_FINALIZATION.md`
- Baseline design / plan that introduced the current visible-text sink rule:
  - `docs/2026-04-24-terminal-output-normalization-implementation-plan.md`
- Feishu protocol design:
  - `docs/2026-04-01-feishu-generic-card-protocol-design.md`
- Routing boundary that stays locked during this repair:
  - `docs/architecture/adr/0004-llm-first-tool-routing-boundary.md`
- Main implementation files in the current repo:
  - `src/marten_runtime/channels/output_normalization.py`
  - `src/marten_runtime/channels/feishu/rendering.py`
  - `src/marten_runtime/channels/feishu/rendering_support.py`
  - `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
  - `src/marten_runtime/interfaces/http/channel_event_serialization.py`
  - `src/marten_runtime/channels/feishu/delivery.py`
  - `src/marten_runtime/channels/feishu/service.py`
  - `src/marten_runtime/channels/feishu/service_support.py`
- Main regression files already present in the repo:
  - `tests/feishu/test_rendering.py`
  - `tests/test_http_event_serialization.py`
  - `tests/test_gateway.py`
  - `tests/test_runtime_context.py`
  - `tests/test_session_restart_integration.py`
  - `tests/contracts/test_gateway_contracts.py`
  - `tests/feishu/test_delivery.py`
  - `tests/feishu/test_websocket_service.py`
  - `tests/test_acceptance.py`

## Goal Lock

- **Target outcome:** the same structured Feishu reply yields one durable plain-text record across `final_text`, top-level HTTP plain text, serialized terminal event text, and session history, while the card still renders a compact lead plus structured sections.
- **Boundary:** terminal-output normalization, Feishu rendering support, HTTP finalization/serialization sinks, and persistence/replay verification only.
- **Proof:** focused unit tests for durable-text reconstruction, sink routing, and Feishu delivery/raw-card preservation, then restart/replay regressions, then one simulated Feishu smoke that checks both durable plain text and rendered card behavior.

## Why This Repair Exists

The current implementation follows the earlier terminal-output normalization plan too literally for Feishu structured replies:

- `visible_text` is compact by design
- Feishu card sections can carry richer detail than that compact lead
- `_finalize_session_turn(...)` currently persists `visible_text`
- `serialize_event_for_channel(...)` currently emits `visible_text` as terminal event text

That is correct for channel presentation and too thin for durable state.

The result is one product drift:

- Feishu user sees a detailed card body
- `final_text`, session history, replay, compaction, restart, and plain HTTP readers can receive only the short lead

This repair corrects the persistence target. It does not change tool routing, prompt contracts, runtime loop control flow, or Feishu card rendering strategy.

## Locked Invariants

- keep the runtime loop contract unchanged: it still emits one `raw_text` terminal event
- keep Feishu card rendering sourced from `raw_text`
- keep the fix inside the interface/channel boundary; no prompt, tool-followup, recovery-flow, or routing changes belong in this slice
- keep ADR 0004 intact; this repair adds zero host-side natural-language routing
- keep `SessionMessage.content` as the durable assistant text field unless a code-level blocker appears; the current repo already persists assistant text through one `content` column, so the first-choice plan avoids a schema migration
- keep non-Feishu channels identity-style:
  - `durable_text = raw_text`
  - `visible_text = raw_text`
  - `channel_payload = None`
- keep plain Feishu direct answers identity-style when no structured card protocol is present and no structured fallback is derived
- keep usage footer channel-local; it stays part of the Feishu card payload and does not become durable assistant text
- keep live Feishu delivery rendering on the raw/card surface:
  - delivered interactive cards must continue to derive from `raw_text` or a precomputed card payload built from `raw_text`
  - `durable_text` may feed plain sinks and must never become the sole card render input
- keep websocket Feishu delivery and automation Feishu delivery on the same corrected sink contract
- keep deterministic durable-text reconstruction truthful:
  - only content already present in `raw_text` or parsed Feishu protocol payload
  - no fabricated metadata
  - no synthesis from card chrome such as icons, colors, or footer separators
- keep replay, compaction, and restart consuming the durable assistant text automatically through existing `SessionMessage.content`

## Architecture Adjustment

The earlier `docs/2026-04-24-terminal-output-normalization-implementation-plan.md` established one useful boundary and one now-proven-wrong sink rule.

What stays valid:

- one shared terminal-output normalization boundary
- channel-local Feishu parsing/rendering behind that boundary
- runtime loop remains channel-agnostic

What changes in this repair:

- terminal normalization returns **two** text surfaces instead of one
- persistence/plain sinks consume `durable_text`
- Feishu card lead consumes `visible_text`
- live Feishu delivery consumes either the raw terminal text or a precomputed card payload so the card renderer keeps its current input contract

This is the smallest repo-shaped correction because the current drift lives in `output_normalization.py`, `bootstrap_handlers.py`, and `channel_event_serialization.py`, while the detailed content already exists inside Feishu protocol parsing.

## File / Module Map

### Module A: terminal-output normalization contract

**Files:**
- Modify: `src/marten_runtime/channels/output_normalization.py`
- Test: `tests/test_http_event_serialization.py`

**Responsibility:**
- return one `TerminalOutputNormalization` object with:
  - `durable_text`
  - `visible_text`
  - `channel_payload`

**Constraints:**
- non-Feishu behavior stays identity-style
- terminal events only; progress events stay untouched
- default behavior stays trivial for channels without special rendering

**Boundary:**
- data contract only; no Feishu-specific parsing logic should be duplicated here

**Key test cases:**
- non-Feishu final/error returns raw text for both surfaces
- Feishu final/error can carry distinct durable and visible text in one object
- precomputed normalization can be passed into event serialization without re-parsing

**Done means:**
- all callers can consume `durable_text` and `visible_text` explicitly
- the contract can represent the Feishu split without widening provider-facing request/response transport

### Module B: Feishu durable plain-text reconstruction

**Files:**
- Modify: `src/marten_runtime/channels/feishu/rendering.py`
- Modify: `src/marten_runtime/channels/feishu/rendering_support.py`
- Test: `tests/feishu/test_rendering.py`

**Responsibility:**
- add one Feishu-owned helper that converts `raw_text` into the durable plain-text equivalent of what the card body communicates
- keep `render_final_reply_card(...)` behavior stable

**Constraints:**
- card rendering still uses `raw_text`
- durable text must stay plain text / markdown-light text only
- durable text must keep semantic detail from protocol `summary`, `sections`, and trailing note when that detail is absent from the visible lead
- durable text must keep protocol-shell cleanup behavior
- durable text must keep plain non-protocol text unchanged except for existing protocol residue stripping and follow-up offer trimming

**Boundary:**
- Feishu channel semantics only; no persistence or HTTP routing logic in this module

**Key test cases:**
- fenced `feishu_card` reply with short lead + section items -> durable text contains the section items
- provider `<invoke name="feishu_card">` shape -> durable text contains the parsed details
- bare trailing JSON / inline trailing JSON -> durable text contains parsed details
- malformed protocol -> durable text falls back to cleaned raw text
- plain XML-like line without protocol context stays unchanged
- fallback structured cards derived from already-detailed plain text keep the existing plain text rather than re-rendering a thinner summary

**Done means:**
- one helper can reconstruct a durable text form for every Feishu protocol shape already supported by `parse_feishu_card_protocol(...)`
- `render_final_reply_card(...)` remains green on the current rendering suite

### Module C: durable sink routing across HTTP response, serialized event text, session history, and Feishu delivery

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/interfaces/http/channel_event_serialization.py`
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/channels/feishu/service_support.py`
- Test: `tests/test_http_event_serialization.py`
- Test: `tests/test_gateway.py`
- Test: `tests/contracts/test_gateway_contracts.py`
- Test: `tests/feishu/test_delivery.py`
- Test: `tests/feishu/test_websocket_service.py`

**Responsibility:**
- make durable text the persisted/plain-text sink
- keep card payload attachment intact
- preserve the live Feishu card render input contract for websocket and automation delivery

**Constraints:**
- top-level response `result`, `final_text`, and `text` must use `durable_text`
- terminal serialized event `payload.text` must use `durable_text`
- session history must append `durable_text`
- card payload stays exactly the channel payload returned by normalization
- live Feishu delivery must keep a raw/card input separate from `payload.text` when `payload.text` becomes `durable_text`
- websocket runtime delivery and `_deliver_automation_events(...)` must preserve the same compact-lead + full-card behavior
- current non-Feishu tests that expect text equality stay valid because non-Feishu remains identity-style

**Boundary:**
- sink wiring and delivery-contract wiring only; no changes to runtime loop event production or run history contracts

**Key test cases:**
- Feishu structured success reply -> top-level fields, event text, and stored history all contain the durable detail; card header/body still match current behavior
- Feishu structured error reply -> same durable sink behavior for `event_type="error"`
- websocket runtime delivery keeps the compact lead and structured card even after `payload.text` becomes durable text
- automation Feishu delivery keeps the same card behavior as interactive Feishu delivery
- Feishu plain direct answer -> all text surfaces remain identical
- HTTP/non-Feishu reply -> behavior stays unchanged
- gateway contract tests reflect the intended durable-text plain response for Feishu terminals

**Done means:**
- plain sinks are aligned on durable text
- delivered Feishu cards still render from raw/card input rather than reconstructed durable text
- card rendering stays intact
- no call site still persists `visible_text` as assistant history

### Module D: replay, compaction, and restart proof

**Files:**
- Test: `tests/test_runtime_context.py`
- Test: `tests/test_session_restart_integration.py`
- Test: `tests/test_acceptance.py`

**Responsibility:**
- prove that durable text now flows into the existing context/restart path with no new storage model

**Constraints:**
- first-choice implementation uses the existing `SessionMessage.content` field
- restart path should pass without adding new SQLite columns
- replay and compaction assertions should verify information preservation, not card chrome replication

**Boundary:**
- verification-first module; change production code here only if the new durable sink reveals a replay bug

**Key test cases:**
- next-turn runtime context includes detail that previously lived only in Feishu card sections
- SQLite-backed restart reloads the durable assistant text verbatim
- acceptance-level simulated Feishu flow preserves durable text across a second turn that references detailed section content

**Done means:**
- replay and restart tests prove the fix matters for real continuity paths
- schema remains unchanged unless a concrete blocker appears during implementation

### Module E: docs sync and full verification

**Files:**
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `/Users/litiezhu/docs/ytsd/工作学习/AI学习/handoff/HANDOFF_2026-04-25_MARTEN_RUNTIME_CURRENT_TURN_EVIDENCE_LEDGER_FINALIZATION.md`

**Responsibility:**
- record the corrected contract: durable text for persistence, visible text for compact Feishu lead
- capture verification evidence

**Constraints:**
- changelog entry must name the corrected sink boundary
- continuity update must point future work at the new plan file and the updated invariant
- full verification must include the required Feishu smoke classes already used on this branch

**Boundary:**
- docs and verification only; no extra product work folds into this step

**Key test cases / evidence:**
- targeted unit suites for rendering + serialization + gateway
- replay/restart suites
- broad regression suite already used by this branch for runtime/gateway stability
- `git diff --check`
- one simulated Feishu smoke covering:
  - 普通对话 / builtin
  - MCP 多轮工具调用
  - skill / subagent
  - 切换会话后继续对话

**Done means:**
- docs describe the corrected contract accurately
- verification evidence shows durable text and card rendering both behaving as intended

## Delivery Order

Implement in five strict chunks:

1. split the terminal normalization contract into `durable_text` and `visible_text`
2. implement Feishu durable plain-text reconstruction
3. route durable text into response/event/history sinks
4. prove replay/restart continuity and acceptance behavior
5. sync docs and run full verification

Do not start a later chunk until the current chunk:

- passes its focused verification
- still matches the locked invariants above
- leaves `git diff --check` clean

## Chunk 1: Split The Terminal Normalization Contract

### Task 1: Add `durable_text` to `TerminalOutputNormalization`

**Files:**
- Modify: `src/marten_runtime/channels/output_normalization.py`
- Modify: `tests/test_http_event_serialization.py`

**Constraints:**
- identity behavior for non-Feishu channels
- no call-site widening outside the current terminal normalization boundary

**Boundary:**
- contract shape only; durable-text content for Feishu can temporarily equal visible-text until Chunk 2 lands

- [ ] **Step 1: Write the failing tests**
  - add assertions that `TerminalOutputNormalization` exposes both text surfaces
  - add one Feishu precomputed-normalization test that can carry distinct values

- [ ] **Step 2: Run the focused failing tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_event_serialization
```

Expected:
- new assertions fail because the normalization contract only exposes `visible_text`

- [ ] **Step 3: Implement the contract split**
  - extend the dataclass with `durable_text`
  - make identity branches set both values to `raw_text`
  - keep Feishu branch returning a placeholder equal pair until Chunk 2 adds the durable renderer

- [ ] **Step 4: Re-run the focused tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_event_serialization
```

**Done means:**
- the normalization contract supports two text surfaces
- no caller still depends on a single-field assumption without compile/test coverage

## Chunk 2: Implement Feishu Durable Plain-Text Reconstruction

### Task 2: Add one Feishu-owned durable-text renderer

**Files:**
- Modify: `src/marten_runtime/channels/feishu/rendering.py`
- Modify: `src/marten_runtime/channels/feishu/rendering_support.py`
- Modify: `src/marten_runtime/channels/output_normalization.py`
- Modify: `tests/feishu/test_rendering.py`

**Constraints:**
- keep `render_final_reply_card(raw_text, ...)` behavior stable
- durable text may reuse protocol parsing and fallback parsing helpers
- durable text must not include usage footer text or Feishu visual labels such as `📌` / `🗂️`

**Boundary:**
- one deterministic text reconstruction path only; avoid a second card renderer or cross-channel formatter

- [ ] **Step 1: Write the failing tests**
  - protocol summary + sections -> durable text includes both the short lead and section items
  - invoke/block/json variants -> durable text includes parsed detail
  - malformed protocol -> durable text falls back to cleaned raw text
  - plain non-protocol Feishu text stays unchanged

- [ ] **Step 2: Run the focused failing tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.feishu.test_rendering
```

Expected:
- new durable-text assertions fail because no such helper exists yet

- [ ] **Step 3: Implement the durable renderer**
  - add a helper with a repo-shaped name such as `normalize_feishu_durable_text(...)`
  - parse protocol when present
  - reconstruct plain text from:
    - visible lead
    - protocol summary when it adds information
    - protocol sections and items
    - trailing note when present
  - preserve existing residue stripping and follow-up-offer trimming
  - keep already-detailed plain text replies on the raw-text path

- [ ] **Step 4: Wire the Feishu branch in `normalize_terminal_output(...)`**
  - set `visible_text` from the existing compact normalizer
  - set `durable_text` from the new durable renderer
  - keep `channel_payload` sourced from `render_final_reply_card(raw_text, ...)`

- [ ] **Step 5: Re-run the focused tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.feishu.test_rendering tests.test_http_event_serialization
```

**Done means:**
- Feishu normalization returns a durable plain-text form richer than the compact lead when structure exists
- current card-rendering regressions stay green

## Chunk 3: Route Durable Text Into Plain Sinks

### Task 3: Rewire final response, terminal event text, assistant history, and Feishu delivery payloads

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/interfaces/http/channel_event_serialization.py`
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/channels/feishu/service_support.py`
- Modify: `tests/test_gateway.py`
- Modify: `tests/contracts/test_gateway_contracts.py`
- Modify: `tests/test_http_event_serialization.py`
- Modify: `tests/feishu/test_delivery.py`
- Modify: `tests/feishu/test_websocket_service.py`

**Constraints:**
- `result`, `final_text`, and `text` become durable-text sinks
- terminal event `payload.text` becomes the durable terminal text
- card payload remains attached for Feishu terminal events
- Feishu delivery receives a separate raw/card surface for final/error cards
- current non-Feishu API expectations stay unchanged

**Boundary:**
- response/history serialization and Feishu delivery-contract wiring only; do not change runtime loop event emission or run-diagnostics storage in this task

- [ ] **Step 1: Write the failing tests**
  - update Feishu gateway expectations so top-level fields and session history contain detail previously hidden in card sections
  - add serialization expectations that terminal event text is durable text while card payload still exists
  - add delivery expectations that websocket and automation Feishu cards still render from raw/card input
  - update contract tests for the intended Feishu plain-text response shape

- [ ] **Step 2: Run the focused failing tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_event_serialization tests.test_gateway tests.contracts.test_gateway_contracts tests.feishu.test_delivery tests.feishu.test_websocket_service
```

Expected:
- new assertions fail because sinks still use `visible_text`

- [ ] **Step 3: Implement sink routing**
  - in `_finalize_session_turn(...)`, append `SessionMessage.assistant(normalized_terminal.durable_text)`
  - make top-level response text fields use `durable_text`
  - in `serialize_event_for_channel(...)`, set terminal `payload.text = durable_text`
  - keep card payload attachment unchanged
  - carry forward the raw/card surface needed by Feishu delivery, for example via `payload.card` and/or a dedicated raw-text field on `FeishuDeliveryPayload`
  - update `build_delivery_payload(...)`, `FeishuDeliveryClient`, and websocket delivery wiring so interactive cards prefer the precomputed card or raw text instead of re-rendering from durable text
  - normalize `_deliver_automation_events(...)` onto the same contract so automation Feishu delivery stays aligned with interactive Feishu delivery
  - keep helper naming honest; retire or repurpose `history_visible_text(...)` so it reflects durable behavior or becomes a compatibility alias with updated semantics

- [ ] **Step 4: Re-run the focused tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_event_serialization tests.test_gateway tests.contracts.test_gateway_contracts tests.feishu.test_delivery tests.feishu.test_websocket_service
```

**Done means:**
- top-level HTTP text, terminal event text, and assistant history all align on durable text
- delivered Feishu cards still render from raw/card input rather than reconstructed durable text
- Feishu card rendering remains intact

## Chunk 4: Prove Continuity Through Replay And Restart

### Task 4: Add replay / restart / acceptance regressions for durable detail

**Files:**
- Modify: `tests/test_runtime_context.py`
- Modify: `tests/test_session_restart_integration.py`
- Modify: `tests/test_acceptance.py`

**Constraints:**
- prefer verification-only changes here
- keep current session storage model unless concrete failures prove a blocker

**Boundary:**
- continuity proof only; production-code edits here must answer a failing continuity test directly

- [ ] **Step 1: Write the failing tests**
  - runtime-context replay after a Feishu structured reply references a section item that previously lived only in the card body
  - SQLite restart reloads the durable assistant text containing that detail
  - acceptance flow proves a second turn can rely on the persisted detail without reading the card payload

- [ ] **Step 2: Run the focused failing tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_runtime_context tests.test_session_restart_integration tests.test_acceptance
```

Expected:
- at least the new Feishu-durable continuity assertions fail until sink routing is complete

- [ ] **Step 3: Fix any continuity bug revealed by the new tests**
  - first choice is zero production change because durable text should already flow through `SessionMessage.content`
  - if a bug appears, keep the repair local to the replay/restart path that actually drops the durable text

- [ ] **Step 4: Re-run the focused tests**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_runtime_context tests.test_session_restart_integration tests.test_acceptance
```

**Done means:**
- replay, restart, and acceptance proofs confirm the durable text survives the real continuity path
- no schema migration happened unless a verified blocker forced it

## Chunk 5: Docs Sync And Full Verification

### Task 5: Sync docs and run the strongest practical proof

**Files:**
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `/Users/litiezhu/docs/ytsd/工作学习/AI学习/handoff/HANDOFF_2026-04-25_MARTEN_RUNTIME_CURRENT_TURN_EVIDENCE_LEDGER_FINALIZATION.md`

**Constraints:**
- record the corrected invariant explicitly: `durable_text` for persistence/plain sinks, `visible_text` for compact Feishu lead
- keep verification evidence precise and reproducible

**Boundary:**
- changelog, continuity, and verification only

- [ ] **Step 1: Update docs**
  - add one changelog entry for the sink split
  - update the handoff/continuity doc with the new plan path, rationale, and verification state

- [ ] **Step 2: Run the targeted regression bundle**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.feishu.test_rendering \
  tests.test_http_event_serialization \
  tests.test_gateway \
  tests.contracts.test_gateway_contracts \
  tests.feishu.test_delivery \
  tests.feishu.test_websocket_service \
  tests.test_runtime_context \
  tests.test_session_restart_integration
```

- [ ] **Step 3: Run the broad regression bundle already used by this branch**

Run:
```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_tool_followup_support \
  tests.test_llm_message_support \
  tests.test_llm_client \
  tests.test_llm_transport \
  tests.test_recovery_flow \
  tests.test_runtime_history \
  tests.test_http_runtime_diagnostics \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.runtime_loop.test_provider_failover \
  tests.test_runtime_capabilities \
  tests.tools.test_session_tool \
  tests.tools.test_subagent_tools \
  tests.test_subagent_service \
  tests.test_subagent_integration \
  tests.contracts.test_runtime_contracts \
  tests.contracts.test_gateway_contracts \
  tests.feishu.test_delivery \
  tests.feishu.test_websocket_service \
  tests.test_acceptance \
  tests.test_gateway
```

- [ ] **Step 4: Run diff hygiene**

Run:
```bash
git diff --check
```

- [ ] **Step 5: Run one latest-source simulated Feishu smoke**
  - verify for each smoke turn:
    - card lead remains compact
    - card sections render fully
    - top-level `final_text` / `result` carry durable detail
    - the next turn can reference that durable detail
    - token footer still renders correctly

Smoke set:
- 普通对话 / builtin 工具
- MCP 工具调用，多轮工具调用
- 使用 skill 的对话，使用子代理的对话
- 切换会话，并且在新会话中进行对话

**Done means:**
- docs reflect the corrected contract
- targeted and broad regressions pass
- Feishu smoke confirms card rendering and durable-text persistence together

## Final Audit Checklist

Mark this plan ready for execution only when every answer below is **yes**:

- [ ] The plan keeps the fix inside terminal-output normalization and Feishu rendering boundaries.
- [ ] The plan preserves ADR 0004 and adds zero host-side tool routing.
- [ ] The plan keeps the runtime loop raw-text contract unchanged.
- [ ] The plan gives one best-path storage model: reuse `SessionMessage.content` for durable text first.
- [ ] The plan covers both in-memory and SQLite continuity through replay/restart verification.
- [ ] The plan names the exact tests that prove durable text now contains card-body detail.
- [ ] The plan defines done criteria for every module and every chunk.
- [ ] The plan keeps live Feishu card rendering on the raw/card surface and keeps the usage footer card-local.
- [ ] The plan covers websocket Feishu delivery and automation Feishu delivery in addition to HTTP serialization.

## Current Recommendation

Execute this plan as the next slice. It fits the current repo because the bug sits in the existing interface-layer sink split, the required parsing logic already lives in Feishu rendering, and the current session storage model can carry durable text without a schema migration.
