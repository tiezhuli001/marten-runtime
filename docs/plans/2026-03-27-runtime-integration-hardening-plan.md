# Runtime Integration Hardening Implementation Plan

> Status: completed historical record. The original Feishu webhook tasks in this file were superseded by the later websocket-first migration and no longer describe the active baseline.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** add production-facing integration seams for `.env` autoloading, real MCP execution over `docker`/`stdio`/`http`, and Feishu webhook verification plus outbound delivery without breaking the existing `LLM + agent loop + MCP + skills` runtime contracts.

**Architecture:** keep the runtime thin by preserving the current config split: `.env` only stores secrets and local overrides, `mcps.json` keeps connection definitions, `config/mcp.example.toml` plus optional local `config/mcp.toml` keeps runtime policy, and channel verification/delivery logic stays inside focused Feishu adapter modules. Extend the current MCP and Feishu skeletons in place rather than introducing a second orchestration layer or a private integration surface.

**Tech Stack:** Python 3.11+, FastAPI, official `mcp` Python SDK, `python-dotenv`, stdlib `subprocess`/`urllib`, unittest

---

## Chunk 1: Bootstrap And `.env` Autoload

### Task 1: Add a focused env loader and lock non-override semantics

**Files:**
- Create: `src/marten_runtime/config/env_loader.py`
- Test: `tests/test_env_loader.py`

- [x] **Step 1: Write the failing test**

```python
def test_load_env_file_sets_missing_values_without_overriding_existing_env():
    ...
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_env_loader -v`
Expected: FAIL because `marten_runtime.config.env_loader` does not exist.

- [x] **Step 3: Write minimal implementation**

Implement a small loader that:
- loads a repo-local `.env` when present
- keeps existing process env values authoritative
- returns whether a file was loaded plus the resolved path

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_env_loader -v`
Expected: PASS

### Task 2: Wire env autoload into HTTP bootstrap

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Test: `tests/test_models.py`

- [x] **Step 1: Write the failing test**

Add a test proving env-based model selection still works when credentials are loaded from the process env path used by app bootstrap.

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_models -v`
Expected: FAIL on missing env bootstrap hook.

- [x] **Step 3: Write minimal implementation**

Call the env loader before model/MCP/Feishu clients are constructed and add `python-dotenv` plus `mcp` to runtime dependencies.

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_models -v`
Expected: PASS

## Chunk 2: Real MCP Executor

### Task 3: Expand MCP config models and compat-loader merge

**Files:**
- Modify: `src/marten_runtime/mcp/models.py`
- Modify: `src/marten_runtime/mcp/loader.py`
- Modify: `config/mcp.example.toml` or local `config/mcp.toml`
- Modify: `mcps.json`
- Test: `tests/test_mcp.py`

- [x] **Step 1: Write the failing test**

Add loader assertions for:
- `command` / `args` / `env` / `cwd` from `mcps.json`
- `timeout_seconds` -> `timeout_ms`
- policy override from `config/mcp.example.toml` or local `config/mcp.toml`
- `http`/`streamable-http` config surface

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_mcp -v`
Expected: FAIL because current loader drops connection fields.

- [x] **Step 3: Write minimal implementation**

Keep `mcps.json` as the lightweight connection layer and merge it into the runtime-wide `MCPServerSpec` without moving governance fields out of TOML.

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_mcp -v`
Expected: PASS

### Task 4: Replace mock MCP client with real stdio and streamable-http execution

**Files:**
- Modify: `src/marten_runtime/mcp/client.py`
- Create: `tests/fixtures/mcp_stdio_server.py`
- Create: `tests/fixtures/mcp_streamable_http_server.py`
- Test: `tests/test_runtime_mcp.py`

- [x] **Step 1: Write the failing test**

Add end-to-end MCP client tests that:
- spawn a local stdio MCP server process and call a real tool
- spawn a local streamable HTTP MCP server and call a real tool
- preserve the runtime-facing result contract (`server_id`, `tool_name`, `ok`, traceable payload)

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_mcp -v`
Expected: FAIL because current client is hardcoded mock text.

- [x] **Step 3: Write minimal implementation**

Use the official `mcp` SDK:
- `stdio_client` for `transport = "stdio"` including `docker ...` commands
- `streamablehttp_client` for `transport = "http"` / `transport = "streamable-http"`
- a mock fallback path only for the existing mock server contract

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_runtime_mcp -v`
Expected: PASS

### Task 5: Rewire runtime tool registration to the real MCP executor

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `config/agents.toml`
- Modify: `apps/example_assistant/app.toml`
- Test: `tests/test_gateway.py`
- Test: `tests/test_contract_compatibility.py`

- [x] **Step 1: Write the failing test**

Add a gateway/runtime assertion that MCP-backed tools registered from config still produce `progress -> final` and remain visible in runtime diagnostics after the executor swap.

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_gateway tests.test_contract_compatibility -v`
Expected: FAIL on MCP runtime wiring drift.

- [x] **Step 3: Write minimal implementation**

Build the MCP client from loaded server specs, keep tool registration fail-closed to configured tool names, and expose real server counts in diagnostics.

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_gateway tests.test_contract_compatibility -v`
Expected: PASS

## Chunk 3: Feishu Webhook Verification And Real Delivery

### Task 6: Normalize real Feishu callback payloads and verify webhook authenticity

**Files:**
- Modify: `src/marten_runtime/channels/feishu/models.py`
- Modify: `src/marten_runtime/channels/feishu/inbound.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `.env.example`
- Test: `tests/test_feishu.py`

- [x] **Step 1: Write the failing test**

Add tests for:
- `url_verification` challenge response
- token verification failure
- signature verification success/failure when signing material is configured
- normalization of real nested Feishu message payload into `InboundEnvelope`

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: FAIL because the current adapter only supports a simplified event model.

- [x] **Step 3: Write minimal implementation**

Implement a thin verification layer that:
- supports `url_verification`
- checks configured verification token
- optionally validates request signature when signing material is configured
- preserves runtime-generated `trace_id` after normalization

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: PASS

### Task 7: Replace Feishu delivery stub with real access-token + message send flow

**Files:**
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Modify: `.env.example`
- Test: `tests/test_feishu.py`

- [x] **Step 1: Write the failing test**

Add tests proving the delivery client:
- fetches a tenant access token using `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
- posts a text message to Feishu with `chat_id`
- preserves `run_id` / `trace_id` / `event_id` / `sequence` in the emitted payload contract

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: FAIL because the current client never performs HTTP delivery.

- [x] **Step 3: Write minimal implementation**

Implement a small real client with:
- cached tenant access token acquisition
- send-message API call
- injectable HTTP transport for tests

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: PASS

### Task 8: Reconnect the Feishu webhook route to verified inbound + real outbound

**Files:**
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Test: `tests/test_acceptance.py`
- Test: `tests/test_contract_compatibility.py`

- [x] **Step 1: Write the failing test**

Add an integration-style test covering:
- webhook challenge handshake
- verified inbound event -> runtime execution
- outbound delivery call triggered from the final runtime event

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.test_acceptance tests.test_contract_compatibility -v`
Expected: FAIL because the current route accepts only the simplified body and uses a stub sender.

- [x] **Step 3: Write minimal implementation**

Convert the route to request-aware webhook handling, preserve the standard delivery contract, and fail closed on invalid verification.

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m unittest tests.test_acceptance tests.test_contract_compatibility -v`
Expected: PASS

## Chunk 4: Sync, Regression, And Operator Docs

### Task 9: Sync docs and status after implementation

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `STATUS.md`
- Modify: workspace `STATUS.md` when the repo is being executed from a larger monorepo workspace

- [x] **Step 1: Re-read the implementation and update operator-facing docs**
- [x] **Step 2: Record real config keys and startup steps for `.env`, MCP, and Feishu**
- [x] **Step 3: Run full regression**

Run: `PYTHONPATH=src python -m unittest -v`
Expected: PASS

- [x] **Step 4: Run targeted drift checks**

Run:
- `rg -n "mcps.json|config/mcp.example.toml|FEISHU_|MINIMAX_API_KEY|dotenv|streamable-http|stdio" README.md docs/README.md STATUS.md src tests`
- `sed -n '1,220p' .env.example`

Expected: docs and runtime code reflect the new real integration path without reopening settled architecture.
