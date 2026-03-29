# Feishu Webhook-First Hardening Implementation Plan

> Status: superseded on 2026-03-28. Historical record only. The active repo baseline is Feishu `websocket-first`; see `2026-03-28-feishu-websocket-first-migration-plan.md`.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** finish the first production-usable Feishu mode by hardening the existing webhook-first path so inbound events are claimed safely, `progress/final/error` are actually delivered, and waiting UX works without introducing WebSocket mode yet.

**Architecture:** keep the frozen source-of-truth decision unchanged: Feishu first version stays `connection_mode = "webhook"`. Repair the current drift by introducing a thin channel transport seam around the existing FastAPI route, runtime event fan-out, and delivery retry policy. Follow the OTTClaw idea for waiting UX at the adapter layer only: the runtime still emits standard `progress/final/error` events, while the Feishu adapter can render them as one initial card plus later updates.

**Tech Stack:** Python 3.11+, FastAPI, unittest, stdlib `urllib`, in-memory stores first, existing runtime/session/history modules

**Constraints:** do not add WebSocket mode in this plan, do not reopen the webhook-vs-websocket decision, do not add a workflow engine, do not introduce private config surfaces, and do not commit unless the user explicitly asks.

---

## Chunk 1: Inbound Claim, Dedupe, And Transport Boundary

### Task 1: Add a focused inbound receipt store for duplicate suppression

**Files:**
- Create: `src/marten_runtime/channels/receipts.py`
- Modify: `src/marten_runtime/channels/feishu/inbound.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_gateway.py`

- [x] **Step 1: Write the failing tests**

Add tests that prove:
- the same Feishu `event_id` / derived `dedupe_key` is only claimed once
- a duplicate webhook delivery returns a deterministic accepted/ignored response instead of re-running the runtime
- HTTP ingress still normalizes to a valid `InboundEnvelope`

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_gateway -v
```

Expected: FAIL because there is no receipt/claim enforcement yet.

- [x] **Step 3: Write the minimal implementation**

Implement an in-memory receipt store that:
- claims a `dedupe_key`
- records the first seen `trace_id`, `conversation_id`, and `message_id`
- exposes `already_seen()` / `claim()` helpers

Wire Feishu webhook ingress to claim before runtime execution.

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_gateway -v
```

Expected: PASS

### Task 2: Extract a thin Feishu webhook channel service from the HTTP route

**Files:**
- Create: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/channels/feishu/models.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_acceptance.py`

- [x] **Step 1: Write the failing tests**

Add tests that prove:
- the FastAPI route delegates to a service instead of inlining business logic
- challenge, invalid signature, duplicate delivery, and accepted event paths stay distinct
- the service returns a stable result object for route mapping and later async delivery work

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_acceptance -v
```

Expected: FAIL because the route still directly runs message processing and delivery.

- [x] **Step 3: Write the minimal implementation**

Create a focused service that owns:
- request verification
- payload normalization
- dedupe claim
- handoff into the runtime-facing message entry

Keep the HTTP route as a thin adapter.

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_acceptance -v
```

Expected: PASS

## Chunk 2: Real Event Fan-Out And OTTClaw-Style Waiting UX

### Task 3: Deliver all runtime events to Feishu instead of only the last event

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_acceptance.py`

- [x] **Step 1: Write the failing tests**

Add tests that prove:
- a runtime run with `progress -> final` causes two delivery actions instead of only one
- a runtime run with `progress -> error` causes two delivery actions
- all delivery actions preserve `run_id`, `trace_id`, `event_id`, and `sequence`

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_acceptance -v
```

Expected: FAIL because the current route only delivers `result["events"][-1]`.

- [x] **Step 3: Write the minimal implementation**

Refactor the Feishu path so it iterates over emitted `OutboundEvent`s and hands each one to the delivery adapter.

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_acceptance -v
```

Expected: PASS

### Task 4: Add Feishu delivery session state so progress and final/error can update one visible response

**Files:**
- Create: `src/marten_runtime/channels/feishu/delivery_session.py`
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Test: `tests/test_feishu.py`

- [x] **Step 1: Write the failing tests**

Add tests that prove:
- the first `progress` event creates an initial waiting message/card
- later `progress` updates the same delivery session instead of spamming new messages
- `final` or `error` closes the delivery session and updates the visible result
- if update is unavailable, the adapter degrades safely to send-new-message mode

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu -v
```

Expected: FAIL because delivery is currently stateless per event.

- [x] **Step 3: Write the minimal implementation**

Implement a small delivery-session store keyed by `(channel, conversation/chat, run_id)` that supports:
- `start_or_get()`
- `append_progress()`
- `finalize_success()`
- `finalize_error()`

Adapter rules:
- `progress` creates or updates a waiting card/message
- `final/error` updates the same card/message when possible
- adapter behavior stays behind the standard runtime event contract

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu -v
```

Expected: PASS

## Chunk 3: Delivery Policy, Diagnostics, And Verification Closure

### Task 5: Add retry/backoff/dead-letter behavior to Feishu delivery

**Files:**
- Create: `src/marten_runtime/channels/delivery_retry.py`
- Create: `src/marten_runtime/channels/dead_letter.py`
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Modify: `config/channels.example.toml` or local `config/channels.toml`
- Test: `tests/test_feishu.py`
- Test: `tests/test_contract_compatibility.py`

- [x] **Step 1: Write the failing tests**

Add tests that prove:
- `progress` retries stop at the lower threshold
- `final/error` retry more times
- final delivery failure records a dead-letter/backlog item
- retry metadata remains traceable to `run_id` and `trace_id`

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_contract_compatibility -v
```

Expected: FAIL because current delivery is single-shot only.

- [x] **Step 3: Write the minimal implementation**

Implement a focused retry helper with:
- per-event retry counts
- backoff intervals
- dead-letter recording on terminal failure

Keep persistence in-memory for now if no stronger store is already present.

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_contract_compatibility -v
```

Expected: PASS

### Task 6: Expose channel diagnostics for duplicate claims and delivery sessions

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/channels/feishu/delivery_session.py`
- Test: `tests/test_contract_compatibility.py`

- [x] **Step 1: Write the failing tests**

Add tests that prove runtime diagnostics expose:
- duplicate claim counts / last duplicate
- active delivery sessions
- dead-letter counts
- configured Feishu mode and callback URL remain visible

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_contract_compatibility -v
```

Expected: FAIL because current diagnostics do not expose these channel-hardening signals.

- [x] **Step 3: Write the minimal implementation**

Extend diagnostics with channel-specific fields under the existing runtime diagnostics surface rather than inventing a second admin API.

- [x] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_contract_compatibility -v
```

Expected: PASS

### Task 7: Sync repo docs and run the targeted regression bundle

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `STATUS.md`
- Test: `tests/test_feishu.py`
- Test: `tests/test_gateway.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_acceptance.py`
- Test: `tests/test_contract_compatibility.py`

- [x] **Step 1: Update docs to match the new webhook-first hardening state**

Document:
- webhook-first remains the only implemented Feishu mode
- waiting UX now uses progress-driven adapter rendering
- duplicate suppression and delivery retry policy are part of the active runtime behavior

- [x] **Step 2: Run targeted regression**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_feishu tests.test_gateway tests.test_runtime_loop tests.test_acceptance tests.test_contract_compatibility -v
```

Expected: PASS

- [x] **Step 3: Run full regression**

Run:

```bash
PYTHONPATH=src python -m unittest -v
```

Expected: PASS

- [x] **Step 4: Run local HTTP smoke**

Run:

```bash
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

In another shell:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Expected:
- health returns `{"status":"ok"}`
- diagnostics expose Feishu callback config plus new delivery/duplicate signals

---

## Completion Criteria

- Feishu stays `webhook-first`
- inbound duplicate deliveries are suppressed
- runtime-emitted `progress/final/error` all reach the Feishu adapter
- waiting UX is improved without introducing WebSocket mode
- delivery retries and dead-letter behavior exist
- diagnostics expose enough evidence to debug Feishu ingress/delivery
- repo docs and status files reflect the new execution milestone
