# Core Module Slimming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 降低 `runtime` / `channel` / `interfaces` 中超大文件的责任浓度，把纯 helper、channel-owned protocol 和 wiring 逻辑收敛到更薄、更稳定的模块边界。

**Architecture:** 只做行为保持型瘦身。`RuntimeLoop.run()` 继续保持总编排 owner；route policy 不迁出 `loop.py`；Feishu 协议知识从 core `llm_client.py` 向 Feishu channel 边界迁移；HTTP wiring 继续保持 thin bootstrap。

**Tech Stack:** Python、`unittest`、FastAPI、existing runtime helpers (`query_hardening.py`, `direct_rendering.py`, `recovery_flow.py`, `tool_outcome_flow.py`)

> Progress note (2026-04-11): this plan has now **completed the intended 2026-04-11 slimming baseline** in the current working tree. Verified work includes: (1) shard-based baseline and core regression bundles, (2) `runtime/loop.py` tool-outcome summary seam extraction, (3) `runtime/llm_client.py` request/provider helper extraction, (4) Feishu channel helper extraction, and (5) `src/marten_runtime/interfaces/http/bootstrap_runtime.py` slimming through deduped/default/runtime-service/tool-registration seams. `runtime/loop.py` remains the largest hotspot, but the planned low-risk helper/provider seams for this baseline are implemented and re-verified. Use the updated shard-based test commands below rather than the deleted legacy mega-file test modules.

---

## Unified Kickoff Prompt For Coding Agents

Treat this as a structural-slimming slice, not a product rewrite.

Protect these project goals:
- **LLM + agent + MCP + skill first**
- **harness-thin, policy-hard, workflow-light**

Your allowed moves:
- extract pure helpers
- deduplicate registration / bootstrap truth
- tighten ownership boundaries
- shrink file responsibility while preserving runtime authority

Your forbidden moves:
- no planner / intent-router / workflow-engine expansion
- no silent route-policy migration out of `RuntimeLoop`
- no silent change to default `feishu/http -> assistant -> example_assistant` runtime path
- no opportunistic rename of `example_assistant`
- no broad prompt rewrite just because the current app assets feel too thin
- no semantic drift in tool routing, recovery, direct render, diagnostics, or provider fail-closed behavior

Execution discipline:
- baseline test first
- one seam per slice
- focused regression after each seam
- if extraction starts needing runtime state, callbacks, or orchestration ownership, stop and keep it in place
- if you discover a product mismatch (naming, prompt richness, capability declaration quality), record it clearly but do not fold that redesign into this slimming slice

---

## Current Default-App Fact

From the current code path, `apps/example_assistant` is functionally the default runtime app, not a detached sample:

- `config/agents.toml` binds `assistant` and `coding` to `app_id = "example_assistant"`
- `config/bindings.toml` makes `assistant` the default agent for both `http` and `feishu`
- `apps/example_assistant/app.toml` sets `default_agent = "assistant"`
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py` explicitly loads `apps/example_assistant/app.toml` as the default app manifest
- `src/marten_runtime/config/agents_loader.py` falls back to `app_id = "example_assistant"`

Therefore, on the current live code path:
- Feishu inbound traffic normally resolves to `assistant`
- `assistant` normally runs on `example_assistant`

This plan may clarify and decouple that fact, but it must not silently change it.

### Out Of Scope For This Slimming Slice

The following are legitimate concerns, but they are **not** part of this slimming plan unless explicitly reopened:
- renaming `example_assistant` to a production-facing default-app name
- redesigning the default assistant persona/prompt stack
- broadening capability declarations or rewriting prompt assets for product-quality reasons

Coding agents may document these mismatches when encountered, but must not smuggle those product changes into structural slimming work.

---

## Scope And Hotspots

**Primary targets:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Modify: `src/marten_runtime/runtime/query_hardening.py`
- Modify: `src/marten_runtime/runtime/direct_rendering.py`
- Modify: `src/marten_runtime/runtime/recovery_flow.py`
- Modify: `src/marten_runtime/runtime/tool_outcome_flow.py`
- Modify: `src/marten_runtime/channels/feishu/rendering.py`
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Test: `tests/test_query_hardening.py`
- Test: `tests/test_direct_rendering.py`
- Test: `tests/test_recovery_flow.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_runtime_mcp.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_gateway.py`
- Test: `tests/test_contract_compatibility.py`

**Secondary low-risk slimming targets:**
- Modify: `src/marten_runtime/gateway/dedupe.py`
- Modify: `src/marten_runtime/gateway/ingress.py`
- Modify: `src/marten_runtime/gateway/models.py`
- Modify: `src/marten_runtime/config/agents_loader.py`
- Modify: `src/marten_runtime/config/bindings_loader.py`
- Modify: `src/marten_runtime/config/automations_loader.py`
- Modify: `src/marten_runtime/config/models_loader.py`
- Modify: `src/marten_runtime/config/platform_loader.py`
- Modify: `src/marten_runtime/apps/bootstrap_prompt.py`
- Modify: `src/marten_runtime/apps/manifest.py`
- Verify: `apps/example_assistant/app.toml`
- Verify: `config/agents.toml`

**Non-goals:**
- no new generic intent router
- no new planner / workflow engine
- no semantics change to fast-path acceptance or fail-closed provider handling

---

## Chunk 1: Lock the behavior baseline before any code motion

### Task 1: Snapshot the currently protected behaviors

**Files:**
- Verify: `tests/runtime_loop/`
- Verify: `tests/test_llm_client.py`
- Verify: `tests/feishu/`
- Verify: `tests/test_gateway.py`

- [x] **Step 1: Run the route / render / Feishu baseline suite**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.test_query_hardening \
  tests.test_direct_rendering \
  tests.test_recovery_flow \
  tests.test_llm_client \
  tests.runtime_loop.test_forced_routes \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_context_status_and_usage \
  tests.runtime_loop.test_automation_and_trending_routes \
  tests.runtime_mcp.test_github_shortcuts \
  tests.runtime_mcp.test_followup_recovery \
  tests.feishu.test_rendering \
  tests.feishu.test_delivery \
  tests.feishu.test_websocket_service \
  tests.test_gateway
```
Expected: PASS。

- [x] **Step 2: Record the specific seams to preserve**

Check these files manually and annotate in the working notes / commit message:
- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/llm_client.py`
- `src/marten_runtime/channels/feishu/rendering.py`
- `src/marten_runtime/channels/feishu/service.py`
Expected: 明确哪些 helper 是 pure，哪些仍然持有 runtime state / protocol policy。

- [ ] **Step 3: Commit the baseline-only checkpoint**

```bash
git add tests
git commit -m "test: lock runtime slimming baseline"
```

---

## Chunk 2: Finish shrinking `runtime/loop.py` by seam, not by abstraction

### Task 2: Move only pure helper truth out of `loop.py`

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/runtime/query_hardening.py`
- Modify: `src/marten_runtime/runtime/direct_rendering.py`
- Modify: `src/marten_runtime/runtime/recovery_flow.py`
- Modify: `src/marten_runtime/runtime/tool_outcome_flow.py`
- Test: `tests/test_query_hardening.py`
- Test: `tests/test_direct_rendering.py`
- Test: `tests/test_recovery_flow.py`
- Test: `tests/runtime_loop/`

- [x] **Step 1: Identify helpers still duplicated or mixed into `loop.py`**

Inspect:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "def _is_|def _render_|def _recover_|def _summar" src/marten_runtime/runtime/loop.py
```
Expected: 得到候选 helper 列表。

- [x] **Step 2: Write or extend the failing targeted tests first**

Examples to add/extend:
- `tests/test_query_hardening.py`: 纯 matcher / extractor 行为
- `tests/test_direct_rendering.py`: builtin/MCP deterministic render 行为
- `tests/test_recovery_flow.py`: successful-tool follow-up recovery
Expected: 新测试在改动前失败，证明 helper seam 受测试约束。

- [x] **Step 3: Move one pure cluster at a time**

Allowed examples:
- pure text matchers / extractors -> `query_hardening.py`
- already-successful tool render transforms -> `direct_rendering.py`
- recovery-only text selection -> `recovery_flow.py`
- pure tool-outcome fact merge helpers -> `tool_outcome_flow.py`

Forbidden:
- moving top-level route policy out of `loop.py`
- moving run lifecycle / event emission out of `RuntimeLoop`

- [x] **Step 4: Re-run focused tests after each cluster**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.test_query_hardening \
  tests.test_direct_rendering \
  tests.test_recovery_flow \
  tests.runtime_loop.test_forced_routes \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_context_status_and_usage \
  tests.runtime_loop.test_automation_and_trending_routes
```
Expected: PASS。

- [ ] **Step 5: Commit the seam-only extraction**

```bash
git add src/marten_runtime/runtime tests
git commit -m "refactor: slim runtime loop helper seams"
```

Progress note (2026-04-11):
- `runtime/loop.py` moved one more pure summary seam into `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/tool_outcome_flow.py`
- fallback-summary assembly and draft+fallback merge logic no longer live inline in `RuntimeLoop`
- targeted regressions passed:
  - `tests.test_tool_outcome_flow`
  - `tests.runtime_loop.test_tool_followup_and_recovery`
  - `tests.runtime_loop.test_direct_rendering_paths`

---

## Chunk 3: Move Feishu protocol ownership closer to the channel boundary

### Task 3: Remove Feishu-specific protocol inference from `llm_client.py`

**Files:**
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Modify: `src/marten_runtime/channels/feishu/rendering.py`
- Modify: `src/marten_runtime/channels/feishu/service.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/feishu/`
- Test: `tests/test_gateway.py`
- Test: `tests/contracts/`

- [x] **Step 1: Add/extend failing tests that prove Feishu-vs-HTTP separation**

Examples:
- Feishu turns still receive card protocol guard
- plain HTTP turns do not inherit Feishu guard
- skill activation / tool follow-up behavior remains unchanged

- [x] **Step 2: Introduce channel-owned instruction assembly**

Preferred shape:
- Feishu channel computes / injects `channel_protocol_instruction_text`
- `llm_client.py` consumes resolved instruction text, but no longer infers Feishu ownership from unrelated runtime context

- [x] **Step 3: Keep the user-visible behavior identical**

Verify:
- Feishu formatted replies
- fallback structured cards
- no protocol leakage into non-Feishu requests

- [x] **Step 4: Run focused regression**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.test_llm_client \
  tests.feishu.test_rendering \
  tests.feishu.test_delivery \
  tests.feishu.test_websocket_service \
  tests.test_gateway \
  tests.contracts.test_gateway_contracts \
  tests.contracts.test_runtime_contracts
```
Expected: PASS。

- [ ] **Step 5: Commit the boundary-tightening slice**

```bash
git add src/marten_runtime/runtime/llm_client.py src/marten_runtime/channels/feishu src/marten_runtime/interfaces/http tests
git commit -m "refactor: move feishu protocol ownership to channel boundary"
```

Progress note (2026-04-11):
- current code already keeps Feishu guard ownership on the channel/input side:
  - `bootstrap_handlers.py` injects `channel_protocol_instruction_text` only for Feishu turns
  - `llm_client.py` now consumes that resolved instruction text via a thinner helper seam in `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_request_instructions.py`
- focused regressions passed across:
  - `tests.test_llm_client`
  - `tests.feishu.*`
  - `tests.test_gateway`
  - `tests.contracts.*`

---

## Chunk 4: Shrink HTTP bootstrap concentration

### Task 4: Make bootstrap modules wiring-only

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Test: `tests/test_gateway.py`
- Test: `tests/test_health_http.py`
- Test: `tests/test_acceptance.py`

- [x] **Step 1: Identify construction logic that can become named providers**

Inspect:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "def build_|def create_|= .*\(" src/marten_runtime/interfaces/http/bootstrap_runtime.py src/marten_runtime/interfaces/http/bootstrap_handlers.py
```
Expected: 找到 wiring 之外的组装/转换逻辑。

- [x] **Step 2: Add failing tests around the extracted seams**

Examples:
- runtime state assembly
- channel-specific final-event serialization
- diagnostics / health endpoint unchanged

- [x] **Step 3: Extract only reusable providers / serializers**

Allowed targets:
- helper functions co-located under `interfaces/http/`
- serializer/provider helpers with no hidden runtime authority

Forbidden:
- moving runtime orchestration into HTTP layer
- creating a second policy center in bootstrap modules

- [x] **Step 4: Run focused regression**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.test_gateway \
  tests.test_health_http \
  tests.test_acceptance
```
Expected: PASS。

- [ ] **Step 5: Commit the bootstrap slimming slice**

```bash
git add src/marten_runtime/interfaces/http tests
git commit -m "refactor: slim http bootstrap wiring"
```

Progress note (2026-04-11):
- extracted HTTP-layer serializers/providers without moving orchestration ownership:
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/channel_event_serialization.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/runtime_diagnostics.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/feishu_runtime_services.py`
- `bootstrap_handlers.py` now delegates channel final-event serialization and history-visible-text cleanup
- `app.py` now delegates runtime diagnostics serialization
- `bootstrap_runtime.py` now delegates Feishu delivery/websocket service construction
- focused regressions passed:
  - `tests.test_http_event_serialization`
  - `tests.test_http_runtime_diagnostics`
  - `tests.test_feishu_runtime_services`
  - `tests.test_gateway`
  - `tests.test_health_http`
  - `tests.test_acceptance`
  - `tests.contracts.test_runtime_contracts`

---

## Chunk 5: Remove low-value thin layers and duplicate registration truth

### Task 5: Clean composition-root duplication before broader extraction

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/gateway/dedupe.py`
- Modify: `src/marten_runtime/gateway/ingress.py`
- Modify: `src/marten_runtime/gateway/models.py`
- Modify: `src/marten_runtime/config/agents_loader.py`
- Modify: `src/marten_runtime/config/bindings_loader.py`
- Modify: `src/marten_runtime/config/automations_loader.py`
- Modify: `src/marten_runtime/config/models_loader.py`
- Modify: `src/marten_runtime/config/platform_loader.py`
- Modify: `src/marten_runtime/apps/bootstrap_prompt.py`
- Modify: `src/marten_runtime/apps/manifest.py`
- Test: `tests/test_gateway.py`
- Test: `tests/test_agent_specs.py`
- Test: `tests/test_bindings.py`
- Test: `tests/test_router.py`
- Test: `tests/test_platform.py`
- Test: `tests/test_models.py`
- Test: `tests/test_env_loader.py`

- [x] **Step 1: Remove repeated family-tool registration from the HTTP composition root**

Inspect and dedupe:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "_register_family_tools|automation|self_improve|runtime|mcp" src/marten_runtime/interfaces/http/bootstrap_runtime.py
```
Expected: registration truth只保留一份，不再在同一函数中重复展开。

Progress note (2026-04-11):
- removed the duplicate `mcp` / `automation` / `runtime` / `self_improve` registrations from `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- added runtime-contract coverage proving those family tools now retain non-trivial `parameters_schema` metadata instead of being overwritten back to `{\"type\": \"object\"}`
- focused regression passed across gateway, tool, and contract suites after the dedupe

- [x] **Step 2: Collapse gateway thin wrappers only if they stay thinner than the interface layer**

Rules:
- if `gateway/*` 只是 envelope / dedupe / ingress 薄转发，可并回 `interfaces/http/`
- if移动后会让 HTTP layer 变得更重，则保留但压缩 API 面

- [x] **Step 3: Reduce duplicated config-default truth**

Goal:
- loader 只做 parse / normalize
- published defaults 优先落在 `config/*.example.toml`
- 避免 code defaults 与 example 配置双份漂移

- [x] **Step 4: Check whether `apps/example_assistant` still acts as a hard-coded default runtime asset**

Verify references in:
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- `config/agents.toml`
- `apps/example_assistant/app.toml`
Expected: 形成并记录清晰结论——**当前代码事实是它继续承担默认运行资产**；本 slice 只允许澄清/解耦该事实，不允许在无单独方案的情况下直接改名或重写 prompt 体系。

- [x] **Step 5: Run focused regression**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.test_gateway \
  tests.test_agent_specs \
  tests.test_bindings \
  tests.test_router \
  tests.test_platform \
  tests.test_models \
  tests.test_env_loader
```
Expected: PASS。

Progress note (2026-04-11):
- reviewed `gateway/*` and kept those wrappers in place because they remain thinner than the HTTP interface layer
- reduced duplicated default-runtime truth via `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/apps/runtime_defaults.py`
- added loader + runtime-contract coverage proving the current code fact still holds: `apps/example_assistant` remains the default runtime asset and `assistant` remains the default agent
- focused regression passed across gateway / router / loader / contract suites

- [ ] **Step 6: Commit thin-layer cleanup**

```bash
git add src/marten_runtime/interfaces/http src/marten_runtime/gateway src/marten_runtime/config src/marten_runtime/apps config apps tests
git commit -m "refactor: slim composition root and thin loader layers"
```

---

## Chunk 6: Final verification for core module slimming

- [x] **Step 1: Run the core regression bundle**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.test_query_hardening \
  tests.test_direct_rendering \
  tests.test_recovery_flow \
  tests.test_llm_client \
  tests.runtime_loop.test_forced_routes \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_context_status_and_usage \
  tests.runtime_loop.test_automation_and_trending_routes \
  tests.runtime_mcp.test_github_shortcuts \
  tests.runtime_mcp.test_followup_recovery \
  tests.feishu.test_rendering \
  tests.feishu.test_delivery \
  tests.feishu.test_websocket_service \
  tests.test_gateway \
  tests.contracts.test_gateway_contracts \
  tests.contracts.test_runtime_contracts \
  tests.test_acceptance
```
Expected: PASS。

- [x] **Step 2: Run the full suite**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v
```
Expected: PASS。

- [x] **Step 3: Capture size delta for hotspot files**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
for path in [
    'src/marten_runtime/runtime/loop.py',
    'src/marten_runtime/runtime/llm_client.py',
    'src/marten_runtime/channels/feishu/service.py',
    'src/marten_runtime/channels/feishu/rendering.py',
    'src/marten_runtime/interfaces/http/bootstrap_runtime.py',
]:
    p = Path(path)
    print(path, sum(1 for _ in p.open('r', encoding='utf-8')))
PY
```
Expected: 热点文件行数下降或职责明显收敛。

Progress note (2026-04-11):
- current verified hotspot snapshot after the latest slices:
  - `src/marten_runtime/runtime/loop.py` -> `973`
  - `src/marten_runtime/runtime/llm_client.py` -> `610`
  - `src/marten_runtime/channels/feishu/service.py` -> `676`
  - `src/marten_runtime/channels/feishu/rendering.py` -> `479`
  - `src/marten_runtime/interfaces/http/bootstrap_runtime.py` -> `501`
- `src/marten_runtime/channels/feishu/service.py` dropped further by extracting `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/service_support.py`
- latest verification: core regression bundle `285` pass, full suite `495` pass, live `/messages` verification passed again on port `8003`

Progress note (2026-04-11):
- current verified hotspot snapshot after the latest slices:
  - `src/marten_runtime/runtime/loop.py` -> `973`
  - `src/marten_runtime/runtime/llm_client.py` -> `610`
  - `src/marten_runtime/channels/feishu/service.py` -> `676`
  - `src/marten_runtime/channels/feishu/rendering.py` -> `479`
  - `src/marten_runtime/interfaces/http/bootstrap_runtime.py` -> `501`
- `src/marten_runtime/channels/feishu/service.py` dropped further by extracting `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/service_support.py`
- `src/marten_runtime/channels/feishu/rendering.py` dropped further by extracting `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/rendering_support.py`
- `src/marten_runtime/runtime/llm_client.py` dropped further by extracting `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_provider_support.py`
- latest verification:
  - core regression bundle remained green for the affected runtime paths
  - full suite passed (`503` tests)
  - live `/messages` verification passed again on port `8004` with plain / builtin `time` / builtin `runtime` / MCP `get_me` / skill load flows all succeeding


Progress note (2026-04-11 / final closure):
- completed one more `interfaces/http` seam by adding `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/runtime_tool_registration.py`
- `bootstrap_runtime.py` now delegates builtin `time` registration plus family-tool registration / checkpoint-availability helper and dropped further to `410` lines
- fresh closure verification after that seam:
  - docs entry-path check: `missing=[]`
  - focused composition-root regression: `72` tests pass
  - full suite: `503` tests pass
  - live `/messages` verification passed again on port `8005` with plain / builtin `time` / builtin `runtime` / MCP `get_me` / skill load all succeeding

- closure re-check: fresh live `/messages` verification on port `8006` also passed for plain / builtin `time` / builtin `runtime` / MCP `get_me` / skill load.
