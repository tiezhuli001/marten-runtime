# Test Suite Slimming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拆分超大测试文件、收敛重复 helper / scripted doubles / fixtures，让测试结构映射当前 runtime 子系统边界，而不是继续把所有行为堆在单文件里。

**Architecture:** 测试瘦身不改变被测行为，只改变测试组织方式和共享测试工具的落点。优先按“运行时子系统边界”拆分，而不是按纯技术层拆分。

**Tech Stack:** Python `unittest`、repo-local fixtures under `tests/`

---

## Unified Kickoff Prompt For Coding Agents

This plan is about making the test suite smaller and easier to evolve, not about changing what the runtime guarantees.

Protect these project goals:
- **LLM + agent + MCP + skill first**
- **harness-thin, policy-hard, workflow-light**

Your allowed moves:
- extract shared test helpers
- split oversized suites by runtime subdomain
- reduce redundant multi-layer coverage
- keep one clear unit layer plus one clear integration/contract layer

Your forbidden moves:
- do not rewrite production semantics while “fixing” tests
- do not rewrite assertions during file moves unless the move itself proves they are wrong
- do not silently drop important coverage because discovery still passes
- do not merge unrelated topics just to reduce file count

Execution discipline:
- prefer move-without-semantic-change first
- preserve test names when practical
- extract helpers before sharding mega-files
- run focused suites after every migration family
- finish with discovery + full-suite verification

---

## Scope And Hotspots

**Primary oversized files:**
- `tests/test_runtime_loop.py`
- `tests/test_feishu.py`
- `tests/test_tools.py`
- `tests/test_contract_compatibility.py`
- `tests/test_runtime_mcp.py`

**Candidate shared helpers:**
- `tests/http_app_support.py`
- ad-hoc scripted doubles inside large test files
- repeated runtime/bootstrap setup code across `test_runtime_loop.py`, `test_gateway.py`, `test_feishu.py`, `test_acceptance.py`

---

## Target Layout

**Recommended target directories:**
- Create: `tests/runtime_loop/`
- Create: `tests/feishu/`
- Create: `tests/tools/`
- Create: `tests/contracts/`
- Create: `tests/runtime_mcp/`
- Create: `tests/support/`

**Recommended helper modules:**
- Create: `tests/support/runtime_builders.py`
- Create: `tests/support/scripted_llm.py`
- Create: `tests/support/mcp_fixtures.py`
- Create: `tests/support/feishu_builders.py`

---

## Chunk 1: Create the shared support layer first

### Task 1: Deduplicate test setup primitives

**Files:**
- Create: `tests/support/runtime_builders.py`
- Create: `tests/support/scripted_llm.py`
- Create: `tests/support/mcp_fixtures.py`
- Create: `tests/support/feishu_builders.py`
- Modify: `tests/http_app_support.py`
- Test: `tests/test_runtime_loop.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_gateway.py`
- Test: `tests/test_acceptance.py`

- [x] **Step 1: Identify duplicated setup code**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "ScriptedLLMClient|build_.*runtime|create_.*app|conversation_id|tool_history|run_history" tests/test_runtime_loop.py tests/test_feishu.py tests/test_gateway.py tests/test_acceptance.py
```
Expected: 列出重复 builder / factory / fixture 片段。

- [x] **Step 2: Extract one helper at a time with failing import updates**

Start with the safest shared primitives:
- scripted LLM replies
- runtime bootstrap builders
- Feishu event / payload builders
- MCP result payload helpers

- [x] **Step 3: Run focused regression after each helper extraction**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.runtime_loop.test_forced_routes \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_context_status_and_usage \
  tests.runtime_loop.test_automation_and_trending_routes \
  tests.feishu.test_rendering \
  tests.feishu.test_delivery \
  tests.feishu.test_websocket_service \
  tests.test_gateway \
  tests.test_acceptance
```
Expected: PASS。

Progress note (2026-04-11):
- added `/Users/litiezhu/workspace/github/marten-runtime/tests/support/app_repo_builders.py` to remove repeated temporary repo/app bootstrap setup from `tests/test_acceptance.py`
- added `/Users/litiezhu/workspace/github/marten-runtime/tests/support/scripted_llm.py` to move runtime-loop-specific scripted/failing doubles out of `tests/test_runtime_loop.py`
- added `/Users/litiezhu/workspace/github/marten-runtime/tests/support/domain_builders.py` to centralize temporary automation/self-improve sqlite fixture setup reused by `tests/test_runtime_loop.py` and `tests/test_tools.py`
- helper extraction is still intentionally pre-sharding; no legacy mega-file is deleted yet because behavior-family migration has not started

- [ ] **Step 4: Commit helper-layer extraction**

```bash
git add tests/support tests/http_app_support.py tests/test_runtime_loop.py tests/test_feishu.py tests/test_gateway.py tests/test_acceptance.py
git commit -m "test: extract shared runtime support helpers"
```

---

## Chunk 2: Split `test_runtime_loop.py` by behavior families

### Task 2: Break the largest runtime-loop file into subsystem suites

**Files:**
- Create: `tests/runtime_loop/test_forced_routes.py`
- Create: `tests/runtime_loop/test_direct_rendering_paths.py`
- Create: `tests/runtime_loop/test_tool_followup_and_recovery.py`
- Create: `tests/runtime_loop/test_context_status_and_usage.py`
- Create: `tests/runtime_loop/test_automation_and_trending_routes.py`
- Modify/Delete: `tests/test_runtime_loop.py`

- [x] **Step 1: Group existing tests by behavior family**

Suggested buckets:
- forced routes / query hardening
- automation / trending route hardening
- direct render and tool follow-up
- runtime context status / usage / compaction
- GitHub MCP shortcut / recovery flows

- [x] **Step 2: Move one class or one family at a time**

Rules:
- preserve existing test names when possible
- do not rewrite assertions while moving
- keep imports via `tests/support/` thin

Progress note (2026-04-11):
- created `/Users/litiezhu/workspace/github/marten-runtime/tests/runtime_loop/test_automation_and_trending_routes.py`
- moved 7 runtime-loop tests covering automation list/detail/register and trending route handling out of `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- created `/Users/litiezhu/workspace/github/marten-runtime/tests/runtime_loop/test_context_status_and_usage.py`
- moved 13 runtime-loop tests covering compaction, runtime context status, and usage tracking out of `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
- completed the remaining runtime-loop migrations into:
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/runtime_loop/test_forced_routes.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/runtime_loop/test_direct_rendering_paths.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/runtime_loop/test_tool_followup_and_recovery.py`
- deleted the legacy umbrella file `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py` after the one-to-one move finished

- [x] **Step 3: Re-run the runtime-only focused suite after each move**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.runtime_loop.test_forced_routes \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_context_status_and_usage \
  tests.runtime_loop.test_automation_and_trending_routes
```
Expected: PASS。

Progress note (2026-04-11):
- interim regressions passed for the migrated families before the umbrella file was deleted
- expanded regression later passed with the shard-based suites plus `tests.test_gateway` and `tests.test_acceptance`
- final runtime-loop target suite passed as written once all five family files existed

- [x] **Step 4: Remove or reduce the legacy umbrella file**

Preferred end state:
- `tests/test_runtime_loop.py` deleted, or
- retained only as a thin import wrapper during migration

- [ ] **Step 5: Commit runtime-loop sharding**

```bash
git add tests/runtime_loop tests/test_runtime_loop.py tests/support
git commit -m "test: shard runtime loop coverage by behavior family"
```

---

## Chunk 3: Split `test_feishu.py`, `test_tools.py`, `test_contract_compatibility.py`, `test_runtime_mcp.py`

### Task 3: Align large test files with runtime subdomains

**Files:**
- Create: `tests/feishu/test_rendering.py`
- Create: `tests/feishu/test_delivery.py`
- Create: `tests/feishu/test_websocket_service.py`
- Create: `tests/tools/test_automation_tool.py`
- Create: `tests/tools/test_runtime_and_skill_tools.py`
- Create: `tests/tools/test_self_improve_tool.py`
- Create: `tests/contracts/test_gateway_contracts.py`
- Create: `tests/contracts/test_runtime_contracts.py`
- Create: `tests/runtime_mcp/test_github_shortcuts.py`
- Create: `tests/runtime_mcp/test_followup_recovery.py`
- Modify/Delete: `tests/test_feishu.py`
- Modify/Delete: `tests/test_tools.py`
- Modify/Delete: `tests/test_contract_compatibility.py`
- Modify/Delete: `tests/test_runtime_mcp.py`

- [x] **Step 1: Create empty target modules with import smoke**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
for path in [
    'tests/feishu/test_rendering.py',
    'tests/feishu/test_delivery.py',
    'tests/feishu/test_websocket_service.py',
    'tests/tools/test_automation_tool.py',
    'tests/tools/test_runtime_and_skill_tools.py',
    'tests/tools/test_self_improve_tool.py',
    'tests/contracts/test_gateway_contracts.py',
    'tests/contracts/test_runtime_contracts.py',
    'tests/runtime_mcp/test_github_shortcuts.py',
    'tests/runtime_mcp/test_followup_recovery.py',
]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text('import unittest\n', encoding='utf-8')
PY
```
Expected: 新目录可被 `unittest` 发现。

- [x] **Step 2: Migrate tests family-by-family**

Order:
1. Feishu rendering / delivery / websocket
2. Tool families
3. Runtime MCP shortcuts / recovery
4. Contract compatibility

Progress note (2026-04-11):
- created `/Users/litiezhu/workspace/github/marten-runtime/tests/feishu/test_rendering.py`
- created `/Users/litiezhu/workspace/github/marten-runtime/tests/feishu/test_delivery.py`
- created `/Users/litiezhu/workspace/github/marten-runtime/tests/feishu/test_websocket_service.py`
- created `/Users/litiezhu/workspace/github/marten-runtime/tests/support/feishu_builders.py` to hold shared fake delivery clients / transports and websocket frame builder
- deleted `/Users/litiezhu/workspace/github/marten-runtime/tests/test_feishu.py` after moving all 74 Feishu tests
- tools / runtime_mcp / contracts subdomain sharding now all live under `tests/tools/`, `tests/runtime_mcp/`, and `tests/contracts/`

- [x] **Step 3: Run focused suites after each family migration**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src python -m unittest -v \
  tests.feishu.test_rendering \
  tests.feishu.test_delivery \
  tests.feishu.test_websocket_service \
  tests.tools.test_automation_tool \
  tests.tools.test_runtime_and_skill_tools \
  tests.tools.test_self_improve_tool \
  tests.runtime_mcp.test_github_shortcuts \
  tests.runtime_mcp.test_followup_recovery \
  tests.contracts.test_gateway_contracts \
  tests.contracts.test_runtime_contracts
```
Expected: PASS。

Progress note (2026-04-11):
- focused subdomain suite passed with:
  - `tests.feishu.test_rendering`
  - `tests.feishu.test_delivery`
  - `tests.feishu.test_websocket_service`
  - `tests.tools.test_automation_tool`
  - `tests.tools.test_runtime_and_skill_tools`
  - `tests.tools.test_self_improve_tool`
  - `tests.runtime_mcp.test_github_shortcuts`
  - `tests.runtime_mcp.test_followup_recovery`
  - `tests.contracts.test_gateway_contracts`
  - `tests.contracts.test_runtime_contracts`
- expanded shard regression also passed with the legacy chunk-2 and gateway / acceptance suites included

- [x] **Step 4: Remove legacy mega-files once coverage is fully moved**

Progress note (2026-04-11):
- deleted:
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_feishu.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_tools.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py`

- [ ] **Step 5: Commit subdomain sharding**

```bash
git add tests/feishu tests/tools tests/contracts tests/runtime_mcp tests/test_feishu.py tests/test_tools.py tests/test_contract_compatibility.py tests/test_runtime_mcp.py
git commit -m "test: split oversized suites by runtime subdomain"
```

---

## Chunk 4: Final verification for test-suite slimming

- [x] **Step 1: Run discovery to ensure new layout is found**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest discover -s tests -p 'test*.py' -v
```
Expected: PASS，且没有因为目录化导致漏测。

- [x] **Step 2: Run the full suite again**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v
```
Expected: PASS。

- [x] **Step 3: Capture size delta for the old hotspots**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
for path in [
    'tests/test_runtime_loop.py',
    'tests/test_feishu.py',
    'tests/test_tools.py',
    'tests/test_contract_compatibility.py',
    'tests/test_runtime_mcp.py',
]:
    p = Path(path)
    print(path, p.exists(), sum(1 for _ in p.open('r', encoding='utf-8')) if p.exists() else 0)
PY
```
Expected: mega-files 被删除或显著缩小。

Progress note (2026-04-11):
- `PYTHONPATH=src python -m unittest discover -s tests -p 'test*.py' -v` passed (`477` tests)
- `PYTHONPATH=src python -m unittest -v` passed (`477` tests)
- hotspot size delta check confirmed all five legacy mega-files now return `False 0`


Progress note (2026-04-11 / final closure):
- the shard-based test layout remained stable through the final core/doc slimming follow-up slice
- closure verification after the last `bootstrap_runtime` seam still passed:
  - focused composition-root regression: `72` tests
  - full suite: `503` tests
  - fresh live `/messages` matrix on port `8005` also passed, confirming the reorganized suites still protect the real chain
- for the 2026-04-11 test-suite-slimming baseline, no migration or cleanup item remains open

- closure re-check: fresh live `/messages` verification on port `8006` also passed for plain / builtin `time` / builtin `runtime` / MCP `get_me` / skill load.
