# Feishu Message Pipeline Unification Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Feishu inbound normalization, websocket dispatch, and outbound rendering into one coherent message pipeline, fixing intermittent parse failures first and keeping final-message post-processing thin, generic, and aligned with an `LLM + agent + skill + MCP first` architecture.

**Architecture:** Keep the existing thin-harness boundary, queue semantics, receipt dedupe, and delivery retry model intact. The pipeline should become more explicit and easier to reason about, but not expand into a broad channel framework. Inbound and dispatch hardening are the primary goal; outbound processing must remain a narrow channel-adaptation layer instead of growing content-type-specific Feishu renderer taxonomies.

**Tech Stack:** Python, unittest, Feishu callback normalization, websocket service, interactive-card delivery

---

## Chunk 1: Baseline Freeze And Message-Pipeline Inventory

### Task 1: Freeze the current Feishu baseline

**Files:**
- Read: `docs/ARCHITECTURE_CHANGELOG.md`
- Read: `src/marten_runtime/channels/feishu/inbound.py`
- Read: `src/marten_runtime/channels/feishu/service.py`
- Read: `src/marten_runtime/channels/feishu/delivery.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_runtime_lanes.py`
- Test: `tests/test_contract_compatibility.py`

- [x] **Step 1: Confirm branch and worktree**

Run: `git branch --show-current && git status --short`
Expected: current branch is not `main`; only expected planning changes exist

- [x] **Step 2: Run the current Feishu-focused baseline**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_runtime_lanes tests.test_contract_compatibility -v`
Expected: PASS

- [x] **Step 3: Freeze the non-negotiable message-pipeline contracts**

Must preserve:
- self-message ignore behavior
- blank-message ignore behavior
- allowed-chat filtering
- receipt dedupe
- semantic replay suppression
- same-conversation FIFO lane behavior
- hidden progress plus visible final-card behavior
- retry/update/dead-letter delivery semantics

**Testing plan for Task 1**
- Feishu-focused baseline suite must pass before implementation.

**Exit condition for Task 1**
- The current Feishu contracts are frozen and verified on the feature branch.

### Task 2: Write down the desired unified pipeline boundaries

**Files:**
- Read: `src/marten_runtime/channels/feishu/inbound.py`
- Read: `src/marten_runtime/channels/feishu/service.py`
- Read: `src/marten_runtime/channels/feishu/delivery.py`
- Update: local `STATUS.md`

- [x] **Step 1: Inventory the current stages**

Stages to map explicitly:
- raw frame payload coercion
- callback payload parsing
- message normalization
- guardrail filtering
- dedupe and semantic replay suppression
- runtime dispatch
- outbound event mapping
- card/text rendering
- send/update/retry path

- [x] **Step 2: Lock the target one-way pipeline**

Target flow:
- raw payload
- normalized `FeishuInboundEvent`
- normalized `InboundEnvelope`
- runtime result/events
- normalized outbound payload
- rendered card/text
- delivery result

- [x] **Step 3: Mark the post-processing boundary correctly**

Reference goal:
- cleaner assistant-facing final reply
- card-friendly output can still improve, but primarily via model/skill guidance instead of new hardcoded renderer branches
- Feishu delivery stays responsible only for minimal channel adaptation and safe payload construction

Constraint:
- no direct dependency on an external `openclaw` template because no local implementation is present in this workspace
- no dedicated renderer proliferation for each new business content type

**Testing plan for Task 2**
- No new tests required if this is a design/inventory task only, but the desired pipeline stages must be reflected in implementation task boundaries.

**Exit condition for Task 2**
- The target pipeline stages and card-style reference goals are explicitly documented in local continuity before refactoring begins.

## Chunk 2: Inbound Normalization Hardening

### Task 3: Make `inbound.py` tolerate real Feishu payload variants deterministically

**Files:**
- Modify: `src/marten_runtime/channels/feishu/inbound.py`
- Test: `tests/test_feishu.py`

- [x] **Step 1: Enumerate supported inbound payload families in tests**

Required families:
- simplified callback payloads
- official nested callback payloads
- `content` as plain string
- `content` as JSON string
- `content` as decoded dict
- locale-wrapped rich-text payloads

- [x] **Step 2: Make text extraction precedence deterministic**

Required precedence:
- direct plain text
- rich-text text blocks
- `@mention` blocks when they add user-visible content

- [x] **Step 3: Ignore unsupported rich-text block tags safely**

Unknown tags should not fail the entire parse.

- [x] **Step 4: Tighten identifier fallback rules**

Stabilize extraction for:
- `event_id`
- `message_id`
- `chat_id`
- `user_id`

- [x] **Step 5: Keep blank-message behavior explicit**

Normalization may return empty text when the message is truly empty, but should not accidentally discard valid rich-text messages.

**Testing plan for Task 3**
- Add tests for:
- JSON-string rich text
- locale-specific rich text
- mixed text and mention blocks
- unknown rich-text tags
- missing `message_id` fallback
- missing sender-id fallback
- Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
- Expected: PASS

**Exit condition for Task 3**
- Known inbound payload variants normalize consistently and no covered rich-text variant fails parsing unnecessarily.

## Chunk 3: Websocket Dispatch Unification

### Task 4: Refactor `service.py` into one explicit inbound-to-runtime pipeline

**Files:**
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Possibly modify: `src/marten_runtime/channels/feishu/inbound.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_runtime_lanes.py`

- [x] **Step 1: Make stage boundaries explicit inside `handle_event_payload()`**

Stages must be readable and isolated:
- payload coercion
- event type gate
- callback parse
- message guardrails
- dedupe/semantic replay checks
- ack reaction
- lane acquire/release
- runtime handler call
- outbound mapping and delivery

- [x] **Step 2: If needed, extract narrow helper functions without broad refactor**

Allowed:
- small private helpers for normalization/guardrail/delivery mapping

Disallowed:
- a new channel framework
- moving unrelated responsibilities across modules

- [x] **Step 3: Make outbound payload construction depend on normalized message objects**

No ad-hoc payload assumptions should remain in delivery mapping.

- [x] **Step 4: Preserve all concurrency and dedupe contracts**

No change to:
- receipt store semantics
- semantic duplicate suppression window
- lane acquire/release behavior
- accepted/ignored/error status handling

**Testing plan for Task 4**
- Re-run Feishu dispatch tests.
- Re-run lane tests if control flow changes.
- Add a regression test for any real inbound shape that previously caused intermittent parse or dispatch failure.
- Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_runtime_lanes tests.test_contract_compatibility -v`
- Expected: PASS

**Exit condition for Task 4**
- `service.py` follows one explicit normalized message pipeline without regressing queueing, dedupe, or acceptance behavior.

## Chunk 4: Outbound Post-Processing Boundary

### Task 5: Define the outbound rendering contract without widening the channel layer

**Files:**
- Read: `src/marten_runtime/channels/feishu/delivery.py`
- Read: `tests/test_feishu.py`
- Test: `tests/test_feishu.py`

- [x] **Step 1: Freeze the current outbound behavior**

Keep:
- `progress -> hidden`
- `final -> interactive card`
- `error -> current lightweight path` unless a concrete presentation bug requires change
- update-before-send fallback behavior

- [x] **Step 2: Translate the generic post-processing goal into testable requirements**

Required rendering goals:
- keep `final -> interactive`
- keep visible user text clean
- no internal IDs leaked into visible assistant text
- keep the renderer generic so future output formatting can be improved by skills/prompts instead of new delivery branches

- [x] **Step 3: Decide what metadata is safe to render**

Allowed examples:
- minimal generic card wrappers required by Feishu
- user-facing message body

Disallowed by default:
- raw run IDs
- raw trace IDs
- raw event IDs
- content-type-specific hardcoded card variants

**Testing plan for Task 5**
- Add or update tests that lock the generic final-card contract without over-constraining irrelevant JSON ordering.
- Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
- Expected: PASS

**Exit condition for Task 5**
- The outbound card contract is explicit and remains thin before any future presentation work lands.

### Task 6: Keep `delivery.py` thin and remove rejected renderer specialization

**Files:**
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_contract_compatibility.py`

- [x] **Step 1: Remove content-type-specific renderer selection**

Required outcome:
- no task-list / candidate-rule / check-result renderer taxonomy
- one generic final interactive card path remains

- [x] **Step 2: Keep message content safe inside the generic card**

Do not produce invalid JSON or malformed Feishu card payloads.

- [x] **Step 3: Keep delivery semantics unchanged**

Do not alter:
- retry policy
- update/send selection
- dead-letter recording
- duplicate-window behavior

- [x] **Step 4: Keep internal runtime identifiers out of the visible card body**

Presentation should stay user-facing and clean.

**Testing plan for Task 6**
- Add assertions for:
- correct `msg_type = interactive`
- no visible `run_id`, `trace_id`, or `event_id`
- update/send fallback still passing
- Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_contract_compatibility -v`
- Expected: PASS

**Exit condition for Task 6**
- `delivery.py` stays a generic channel adapter and remains contract-compatible with the current delivery model.

## Chunk 5: End-To-End Feishu Verification

### Task 7: Verify the unified message pipeline end to end

**Files:**
- Test: `tests/`
- Update: `docs/ARCHITECTURE_CHANGELOG.md`
- Update: local `STATUS.md`

- [x] **Step 1: Run the focused Feishu regression suite**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_runtime_lanes tests.test_contract_compatibility -v`
Expected: PASS

- [x] **Step 2: Run the full repository suite**

Run: `PYTHONPATH=src python -m unittest -v`
Expected: PASS

- [ ] **Step 3: If live Feishu validation is in scope, restart and validate the live chain**

Recommended checks:
- runtime `/healthz`
- runtime `/diagnostics/runtime`
- one real inbound message that exercises normalization
- one final visible reply that exercises the new card

- [x] **Step 4: Record the accepted pipeline baseline**

Update:
- `docs/ARCHITECTURE_CHANGELOG.md` with the inbound hardening and thin outbound-boundary results, if the architectural baseline changed
- local `STATUS.md` with exact verification commands and outcomes

**Testing plan for Task 7**
- Focused regression and full regression must pass.
- Any live validation must record exact commands or operator actions and observable outcomes.

**Exit condition for Task 7**
- The Feishu pipeline is hardened end to end, the outbound layer remains thin and generic, and verification evidence is recorded.

## Overall Done Criteria

This plan is complete only when all of the following are true:

- `inbound.py` can normalize the covered real-world Feishu payload variants deterministically.
- `service.py` processes messages through one explicit normalized pipeline without regressing dedupe, replay suppression, or FIFO semantics.
- `delivery.py` remains a thin generic Feishu adapter rather than a specialized renderer registry.
- Hidden progress, final interactive card behavior, retry/update/dead-letter handling, and no-internal-ID presentation rules all remain intact.
- Focused regression and full regression both pass.
