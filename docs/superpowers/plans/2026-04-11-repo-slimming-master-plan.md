# Repository Slimming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变当前已验证运行时行为的前提下，系统性缩小 `marten-runtime` 的核心代码集中度、测试维护成本和公开文档表面积。

**Architecture:** 本计划只做“行为保持型瘦身”：保留 thin-harness 主链与现有 fast-path guardrails，不引入新的 planner / intent router / policy center。执行顺序遵循“先锁行为，再拆结构，再归档文档，最后统一回归”的原则。

**Tech Stack:** Python 3.11+、FastAPI、`unittest`、Markdown docs、repo-local plans under `docs/superpowers/plans/`

---

## Unified Kickoff Prompt For Coding Agents

Use this plan as an execution contract, not as a refactor inspiration board.

Primary project goal to preserve:
- **LLM + agent + MCP + skill first**
- **harness-thin, policy-hard, workflow-light**

Your job in this slice:
- reduce repository weight, responsibility concentration, duplication, and doc noise
- preserve current validated runtime behavior unless the plan explicitly says otherwise
- prefer thin extraction, deduplication, and boundary clarification over redesign

Hard constraints:
- do **not** introduce a planner, workflow engine, intent-router subsystem, or policy center
- do **not** weaken capability exposure just to make files shorter
- do **not** silently change routing semantics, `llm_request_count`, diagnostics semantics, or direct-render behavior
- do **not** rename `example_assistant` or rewrite its product prompt stack as part of generic slimming
- do **not** treat `STATUS.md` as repository source of truth; it is local continuity only
- do **not** remove `README_CN.md` or `docs/ARCHITECTURE_EVOLUTION_CN.md`

Execution discipline:
- start with the smallest low-risk slice in the active chunk
- lock behavior with focused tests before structural edits
- move one seam at a time
- run the focused regression after each seam
- if behavior changes unexpectedly, stop and revert to the last verified boundary
- prefer documenting a mismatch over “fixing” product semantics that this plan did not authorize

When in doubt:
- preserve runtime truth
- preserve user-visible behavior
- preserve the main chain
- make the repo smaller without making the runtime dumber

---

## Project Goal Guardrails

All slimming work must continue to optimize for the repository's current product goal:

- **LLM + agent + MCP + skill first**
- **harness-thin, policy-hard, workflow-light**

This means coding agents must not let slimming drift into:
- a broader planner / workflow engine
- a host-side intent router expansion
- capability weakening that makes the model less able to choose tools/skills correctly
- prompt-surface shrinkage that harms the main runtime chain just to make files shorter

---

## Current Runtime Facts To Preserve

The current codebase does **not** treat `apps/example_assistant` as a pure sample app.

As of now it acts as the default runtime asset:
- `config/agents.toml` maps both `assistant` and `coding` agents to `app_id = "example_assistant"`
- `config/bindings.toml` routes both `http` and `feishu` default traffic to `agent_id = "assistant"`
- `apps/example_assistant/app.toml` sets `default_agent = "assistant"`
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py` explicitly loads `apps/example_assistant/app.toml` as the default app manifest
- `src/marten_runtime/config/agents_loader.py` also defaults unspecified agents to `app_id = "example_assistant"`

So for real runtime behavior today:
- a user message from **Feishu** normally routes to **agent `assistant`**
- that agent currently runs on **app `example_assistant`**

This creates a real naming / prompt-surface mismatch:
- the name `example_assistant` reads like a sample
- but the code uses it as the default production-facing runtime app

Slimming work must preserve this fact while making the boundary clearer.

---

## Execution Constraints For Coding Agents

Unless a separate follow-up plan explicitly says otherwise, coding agents must:

- preserve the current default runtime route (`feishu/http -> assistant -> example_assistant`)
- preserve Chinese documentation as a supported first-class reading path
- treat `STATUS.md` as local continuity only, not repository source of truth
- avoid silently renaming `example_assistant` or rewriting its prompts as part of generic slimming
- if touching `apps/example_assistant`, prefer clarifying/documenting/decoupling its role instead of changing product behavior

If the repo later wants:
- a new default app name
- richer default prompts / capability declarations
- a split between sample app and default runtime app

that should be handled as a **separate explicit product/architecture slice**, not hidden inside the slimming refactor.

---

## Baseline Evidence

**Repository hotspots (current snapshot):**
- Core code concentration:
  - `src/marten_runtime/runtime/loop.py` ~1051 lines
  - `src/marten_runtime/runtime/llm_client.py` ~655 lines
  - `src/marten_runtime/channels/feishu/service.py` ~723 lines
  - `src/marten_runtime/channels/feishu/rendering.py` ~479 lines
  - `src/marten_runtime/interfaces/http/bootstrap_runtime.py` ~542 lines
- Test concentration:
  - `tests/test_runtime_loop.py` ~2921 lines
  - `tests/test_feishu.py` ~2884 lines
  - `tests/test_tools.py` ~1562 lines
  - `tests/test_contract_compatibility.py` ~1291 lines
  - `tests/test_runtime_mcp.py` ~1091 lines
- Docs surface:
  - `docs/archive/` already >9500 lines and still healthy as归档层
  - active dated docs still包含一组 2026-04-09 evolution / stage-2 / execution 文档，和架构总览存在明显重叠
  - repo root 仍保留 tracked `STATUS.md`，与 `docs/README.md` / `docs/ARCHITECTURE_CHANGELOG.md` 中“STATUS 不是 repo truth”的规则存在张力

**Immediate low-risk wins already visible in code structure:**
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py` 存在 family-tool 注册重复块，适合作为第一批去重目标
- `src/marten_runtime/gateway/` 与 `src/marten_runtime/config/*_loader.py` 更像薄封装层，适合先做职责收敛
- `apps/example_assistant/` 与 `config/*.toml` 同时承担“示例 + 默认运行资产”角色，适合作为中期剥离目标

**Non-negotiable guardrails:**
- Preserve current runtime spine: `channel -> binding -> agent -> runtime context -> LLM -> tool/skill -> LLM/direct render -> channel`
- Route policy stays thin and visible; do not hide it in a new generic abstraction
- Archive before delete for docs/history-heavy assets
- Prefer split-by-seam over broad rewrites

---

## Workstreams

### Chunk 1: Core module slimming

**Plan:** `docs/superpowers/plans/2026-04-11-core-module-slimming-plan.md`

**Outcome:** 把当前体积和责任最集中的运行时文件拆成更清晰的薄边界，同时保持现有对外行为、测试语义和诊断字段稳定。

- [x] 执行 core plan 的基线锁定任务
- [x] 执行 `runtime` / `channel` / `interfaces` 的低风险拆分任务
- [x] 完成 focused regression + full regression

### Chunk 2: Test suite slimming

**Plan:** `docs/superpowers/plans/2026-04-11-test-suite-slimming-plan.md`

**Outcome:** 把超大测试文件按职责拆分，收敛重复 fixture / scripted doubles / helper 逻辑，降低后续演进的回归维护成本。

- [x] 执行 test plan 的目录重组与 helper 收敛任务
- [x] 按模块迁移超大测试文件，保持每一步可回归
- [x] 完成 focused regression + full regression

### Chunk 3: Documentation slimming

**Plan:** `docs/superpowers/plans/2026-04-11-documentation-slimming-plan.md`

**Outcome:** 把公开阅读路径收敛到 README / docs index / architecture evolution / changelog / ADR / config surfaces，归档分支期执行文档并处理 `STATUS.md` 的 source-of-truth 冲突。

- [x] 执行 doc plan 的 active-path 收敛任务
- [x] 归档重复 dated docs
- [x] 完成 docs index / README / archive index 对齐检查

### Chunk 4: Cross-track closure

**Files:**
- Verify: `docs/superpowers/plans/2026-04-11-core-module-slimming-plan.md`
- Verify: `docs/superpowers/plans/2026-04-11-test-suite-slimming-plan.md`
- Verify: `docs/superpowers/plans/2026-04-11-documentation-slimming-plan.md`

- [x] **Step 1: Re-run the mandatory focused suites**

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
  tests.test_gateway \
  tests.tools.test_automation_tool \
  tests.tools.test_runtime_and_skill_tools \
  tests.tools.test_self_improve_tool \
  tests.contracts.test_gateway_contracts \
  tests.contracts.test_runtime_contracts
```
Expected: PASS，且没有因为文件拆分导致 import / discovery 回归。

Progress note (2026-04-11):
- documentation slimming and test-suite slimming have landed in the working tree and passed their respective full regressions
- core module slimming is now started but incomplete:
  - baseline focused suite passed
  - `runtime/loop.py` shed one fallback summary seam into `runtime/tool_outcome_flow.py`
  - `bootstrap_runtime.py` removed duplicated family-tool registration truth
  - `llm_client.py` shed request-specific/tool-followup instruction assembly into `runtime/llm_request_instructions.py`
  - `interfaces/http` shed channel-event serialization, runtime diagnostics serialization, and Feishu service-provider construction into dedicated helper modules
- cross-track closure now has fresh evidence after the latest follow-up slices:
  - core regression bundle passed (`285` tests)
  - full suite passed (`503` tests)
  - docs entry-path check returned `missing=[]` and active docs root now only keeps 3 dated originals
  - fresh live `/messages` verification passed on ports `8002`, `8003`, and `8004`

- [x] **Step 2: Re-run the full suite**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v
```
Expected: PASS，全量 suite 绿色。

- [x] **Step 3: Re-check docs entry paths**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
must_exist = [
    'README.md',
    'docs/README.md',
    'docs/ARCHITECTURE_EVOLUTION.md',
    'docs/ARCHITECTURE_CHANGELOG.md',
    'docs/CONFIG_SURFACES.md',
    'docs/archive/README.md',
    'docs/superpowers/plans/2026-04-11-core-module-slimming-plan.md',
    'docs/superpowers/plans/2026-04-11-test-suite-slimming-plan.md',
    'docs/superpowers/plans/2026-04-11-documentation-slimming-plan.md',
]
missing = [p for p in must_exist if not Path(p).exists()]
print('missing=', missing)
raise SystemExit(1 if missing else 0)
PY
```
Expected: `missing=[]`

- [x] **Step 4: Capture final slimming delta**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
python - <<'PY'
from pathlib import Path
for root in ['src/marten_runtime','tests','docs']:
    total = 0
    for p in Path(root).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and '.egg-info' not in p.parts:
            try:
                total += sum(1 for _ in p.open('r', encoding='utf-8'))
            except Exception:
                pass
    print(root, total)
PY
```
Expected: 输出新的总体积快照，供 PR / review 使用。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-04-11-*.md README.md docs STATUS.md src tests
git commit -m "refactor: slim runtime, tests, and docs surfaces"
```

---

## Recommended Execution Order

1. 先执行 **documentation slimming** 中的“只归档、不删知识”步骤，降低阅读噪音。
2. 再执行 **core module slimming**，因为其风险最高、收益最大。
3. 然后执行 **test suite slimming**，把结构迁移跟着当前代码边界一起收敛。
4. 最后执行 cross-track closure。

## Stop Rules

- 任何一次拆分如果改变了 `llm_request_count`、tool route、diagnostics 字段或 direct-render 行为，立即停下并回到前一稳定点。
- 不要在同一提交里同时做“行为变化 + 结构迁移 + 文档归档”。
- `STATUS.md` 的最终命运要在 documentation plan 的决策点完成，不要半删半留。


Progress note (2026-04-11 / final closure):
- one final low-risk core slice was completed after the earlier cross-track note:
  - added `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/runtime_tool_registration.py`
  - reduced `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime.py` from `501` to `410` lines by moving tool-registration wiring into a dedicated helper module
- cross-track closure was then re-run end to end:
  - docs entry-path check: `missing=[]`
  - focused composition-root regression: `72` tests pass
  - full suite: `503` tests pass
  - fresh live `/messages` verification on port `8005`: plain / builtin `time` / builtin `runtime` / MCP `get_me` / skill load all pass
- for the current 2026-04-11 slimming baseline, the requested execution work is complete and verified

- closure re-check: fresh live `/messages` verification on port `8006` also passed for plain / builtin `time` / builtin `runtime` / MCP `get_me` / skill load.
