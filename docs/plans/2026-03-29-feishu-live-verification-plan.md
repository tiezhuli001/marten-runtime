# Feishu Live Verification Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** prove the real runtime chain `Feishu -> LLM -> GitHub MCP -> LLM -> Feishu`, and capture any remaining configuration gaps or code hardening work required to make that chain repeatable.

**Architecture:** keep the current runtime shape unchanged. Treat this as a live verification and operator-hardening effort, not a redesign: Feishu inbound continues through `FeishuWebsocketService`, model calls continue through the OpenAI-compatible client, MCP remains connection-owned by `mcps.json`, and outbound reply continues through the Feishu message API. Only add code if live verification reveals a concrete blocker or if a channel-visible issue needs hardening after the chain is proven.

**Tech Stack:** FastAPI, MiniMax OpenAI-compatible endpoint, GitHub MCP over stdio/docker, Feishu websocket + Feishu message API, unittest-based verification docs

---

## Chunk 1: Operator Checklist

### Task 1: Add the single-page live checklist

**Files:**
- Create: `docs/LIVE_VERIFICATION_CHECKLIST.md`
- Modify: `README.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Write the checklist page**

Include:

- current verified boundary
- exact required config for MiniMax, GitHub MCP, and Feishu
- preflight diagnostics checks
- real Feishu conversation steps
- true blockers vs optional hardening

- [ ] **Step 2: Link the checklist from entry docs**

Update the repo entry docs so operators can find the checklist without reading historical plans first.

- [ ] **Step 3: Re-read the checklist for drift**

Confirm the checklist matches the current verified state:

- `HTTP -> LLM -> GitHub MCP` already proven
- real Feishu inbound still pending

## Chunk 2: Execution Plan For The Remaining Live Proof

### Task 2: Record the concrete execution plan

**Files:**
- Create: `docs/plans/2026-03-29-feishu-live-verification-plan.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Break the remaining proof into milestones**

Milestones:

1. config preflight
2. runtime startup
3. diagnostics confirmation
4. real Feishu inbound trigger
5. final reply verification
6. post-run hardening review

- [ ] **Step 2: Call out exact files and signals**

Document:

- which file owns each config
- what diagnostics values must be true
- what symptoms indicate config failure vs code failure

- [ ] **Step 3: Record code-action rules**

Document that:

- no new code is required unless live Feishu verification exposes a concrete blocker
- `<think>` leakage should be treated as post-proof hardening, unless the user decides it is release-blocking

## Chunk 3: First Live Run Procedure

### Task 3: Define the exact operator run

**Files:**
- Modify: `docs/LIVE_VERIFICATION_CHECKLIST.md`
- Modify: `STATUS.md`

- [ ] **Step 1: Write the preflight command set**

Commands should cover:

- runtime startup
- `GET /diagnostics/runtime`
- optional `GET /diagnostics/trace/{trace_id}`
- optional `GET /diagnostics/run/{run_id}`

- [ ] **Step 2: Write the exact Feishu prompt**

Use a prompt that strongly forces GitHub MCP:

```text
Use GitHub MCP tool get_me and reply with my GitHub login and public repo count in one sentence.
```

- [ ] **Step 3: Define pass/fail criteria**

Pass:

- inbound Feishu event arrives
- run completes
- reply returns to same chat
- reply contains GitHub-derived data

Fail buckets:

- websocket/connectivity failure
- provider auth/transport failure
- MCP discovery/call failure
- Feishu outbound delivery failure

## Chunk 4: Post-Proof Hardening

### Task 4: Decide whether any code changes are needed after the live run

**Files:**
- Potential modify: `src/marten_runtime/runtime/llm_client.py`
- Potential modify: `src/marten_runtime/channels/feishu/service.py`
- Potential modify: `src/marten_runtime/channels/feishu/delivery.py`
- Potential modify: `tests/test_feishu.py`
- Potential modify: `tests/test_acceptance.py`

- [ ] **Step 1: Check whether channel-visible output leaks reasoning tags**

If the live Feishu reply includes `<think>...</think>`, treat that as a concrete hardening item.

- [ ] **Step 2: Add only minimal code needed**

Do not refactor architecture. Add the smallest normalization/filtering change that removes channel-visible leakage.

- [ ] **Step 3: Add targeted regression coverage**

At minimum, add tests for:

- final visible reply text normalization
- Feishu-triggered final delivery payload shape

- [ ] **Step 4: Re-run targeted verification**

Run the smallest relevant tests first, then the broader suite if the touched area expands.

## Verification Commands

Use these during execution:

```bash
PYTHONPATH=src python -m unittest -v
```

```bash
PYTHONPATH=src python -m uvicorn marten_runtime.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8000
```

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

## Success Definition

This plan is complete when:

- the checklist page exists and is linked from entry docs
- the remaining live Feishu proof has an operator-ready runbook
- the repository clearly distinguishes missing external conditions from missing code
- any post-proof hardening items are explicitly separated from chain blockers
