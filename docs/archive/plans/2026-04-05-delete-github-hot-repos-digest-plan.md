# 2026-04-05 Safe Removal Plan For `github_trending_digest`

## Goal

安全删除仓库内的 `github_trending_digest` skill，并保持以下边界不被破坏：

- 交互式 GitHub trending / hot repos 请求继续走：
  - `LLM -> mcp -> github_trending.trending_repositories -> renderer`
- 普通 GitHub repo/code/issues/PR/release 查询继续走官方 GitHub MCP
- 已有 automation / scheduler / store / display / tests 不因为 skill 删除而断裂
- 不引入新的 runtime GitHub 专用 if/else
- 不为了兼容删除而把 automation 层做成通用的“skill 缺失兜底平台”

---

## Current Reality

当前已经确认：

1. **交互主链上，`github_trending_digest` 对 trending 已非必要**
   - 真实链路 `run_a2d2f279` 已证明：
     - 不需要 `skill(load github_trending_digest)`
     - 也能正确走 `github_trending.trending_repositories`

2. **真正的剩余依赖在 automation 标识层**
   - 当前大量代码、测试、以及可能存在的历史数据把：
     - `skill_id = github_trending_digest`
   - 当作 recurring digest 的稳定标识

3. **当前 skill 不只是“热榜 skill”**
   - `skills/github_trending_digest/SKILL.md` 仍包含：
     - GitHub MCP 读写选择规则
     - repo/code/issues/PR/release 查询提示
     - trending/digest 约束
   - 仓库当前没有另一个 GitHub skill 可直接接替它

因此本次删除不是“删一个孤立 skill 文件”，而是：

> **先把 automation 对该 skill id 的语义依赖迁走，再确认普通 GitHub MCP 主链不因 skill 删除而明显退化，最后删除 skill 本体。**

---

## Non-Goals

本次不做：

- 不回退到 skill 驱动 trending 主链
- 不在 runtime 里增加 “如果没有 skill 就特殊处理 GitHub 热榜” 的分支
- 不修改 `github_trending` MCP sidecar 的职责边界
- 不引入复杂 migration framework
- 不在第一版做数据库通用迁移平台
- 不批量重命名历史 `automation_id`
- 不做首版 SQLite 批量 rewrite / data migration

---

## Safety Principles

删除必须遵循：

1. **先兼容，后移除**
2. **先迁移 automation 标识，再删 skill 文件**
3. **历史 job 不能因为 skill 文件删除就失效**
4. **删 skill 不应改变 MCP-first 主链**
5. **首版只做运行时兼容 + 新注册默认值切换，不做历史数据批量重写**
6. **历史 `automation_id` 维持不变，manual trigger / dispatch dedupe 不受影响**

---

## Target Strategy

### Phase 1: Introduce a new automation-level canonical identifier

把“GitHub trending digest automation”的稳定标识从：

- `github_trending_digest`

迁到一个**不再暗示 skill 文件存在**的新标识：

- `github_trending_digest`

这个新 id 只用于：

- 新注册 automation 的 canonical `skill_id`
- automation 展示 / dispatch 兼容判断
- 新测试的主真相

不用于：

- 重命名已有 `automation_id`
- 在 runtime core 新增 GitHub 路由分支

---

### Phase 2: Define the compatibility model explicitly

首版兼容模型固定为：

- **新注册**：输入 `github_trending_digest` 或 `github_trending_digest`，都 canonicalize 为 `github_trending_digest`
- **历史存量记录**：保留原始 `skill_id`，不做批量 rewrite
- **读取展示**：old/new id 都显示为同一业务名称
- **automation dispatch**：old/new id 都走同一条 digest 路径
- **manual trigger / delete**：仍只按 `automation_id` 工作，不碰 skill id 迁移

### Why this shape

这样可以：

- 先把“能跑”和“能删”稳定下来
- 避免对 SQLite 历史数据做工程化迁移
- 避免影响 dispatch window 的 `automation_id + scheduled_for` 去重键

---

### Phase 3: Make the fingerprint rules explicit

这是本次计划必须单列的一步。

当前 `semantic_fingerprint` 依赖 `skill_id`，见：

- `src/marten_runtime/automation/models.py`

因此任何涉及 `skill_id` canonicalize / update / create 的路径，都必须明确处理 fingerprint。

### Required rule

- 当 create / update 路径改变了 `skill_id`、`schedule_kind`、`schedule_expr`、`timezone`、`prompt_template`、`delivery_target` 等参与语义去重的字段时：
  - `semantic_fingerprint` 必须重算

### Important constraint

- 不允许出现“`skill_id` 已变成新 canonical 值，但 `semantic_fingerprint` 仍然是旧值”的状态
- 不允许用大而全的 migration registry 来解决这个点
- 应在 automation model/store/update 这一薄边界解决

---

### Phase 4: Keep compatibility strictly inside the automation boundary

兼容层允许放在：

- `automation` models / helpers
- `register_automation_tool.py`
- `automation_view.py`
- `bootstrap_handlers.py` 中的 automation dispatch skill 解析边界
- 与 automation CRUD 直接相关的 adapter / tool 层

兼容层禁止放在：

- `runtime/loop.py`
- `tools/builtins/mcp_tool.py`
- LLM system prompt / renderer
- 面向所有 skill 的通用 fallback 平台

兼容判断应收敛为：

- 仅识别 `github_trending_digest`
- 和 `github_trending_digest`

而不是做成“只要 skill 文件缺失就兜底”。

---

## CRUD Contract To Keep Stable

为了防止编码时跑偏，本次计划把 automation 的行为契约定死如下：

### Register

- 输入 `skill` / `skill_id` 若是：
  - `github_trending_digest`
  - `github_trending_digest`
- 一律 canonicalize 成：
  - `github_trending_digest`
- 默认生成的 `automation_id` 也基于新 canonical id 生成

### List

- old/new skill id 都显示统一业务名
- 不要求列表返回里暴露 canonical skill id
- 重点是用户视角一致、名称不漂移

### Detail

- 第一版保持返回 **persisted raw value** 更安全
- 不在 detail 读取时偷偷写回数据库
- 若历史记录是 `github_trending_digest`，detail 可继续看到旧值

### Update

- 如果 update 请求显式带 `skill_id`：
  - old/new id 都 canonicalize 为 `github_trending_digest`
- 一旦 update 影响到语义字段：
  - 必须重算 `semantic_fingerprint`

### Delete / Pause / Resume / Manual Trigger

- 继续只依赖 `automation_id`
- 不参与 skill id 迁移
- 不批量更改历史 job 的 `automation_id`

---

## Recommended Thin Helper

推荐新增一个很薄的 helper，例如：

- `src/marten_runtime/automation/skill_ids.py`

只负责：

- canonicalize automation skill/template ids
- 判断 old/new GitHub digest id
- 提供统一 display alias

建议 API 维持极简：

- `canonicalize_automation_skill_id(skill_id: str) -> str`
- `is_github_trending_digest_skill_id(skill_id: str) -> bool`
- `display_name_for_automation_skill_id(skill_id: str) -> str | None`

避免做成“大而全 skill registry”。

---

## Execution Plan

### Step 1: Add failing tests for the real compatibility surface

先补 red tests，覆盖以下 slice：

1. **new canonical id**
   - register / list / detail / update / delete 可用

2. **backward compatibility for old persisted jobs**
   - 历史 `github_trending_digest` job 仍能：
     - list
     - detail
     - manual trigger
     - dispatch

3. **dispatch after skill deletion**
   - old/new digest job 都不要求 skill 文件存在

4. **fingerprint correctness**
   - register old id 与 new id 应视为同一语义任务
   - update old -> new / new -> new 后 fingerprint 正确重算
   - 不产生重复注册

5. **non-trending GitHub smoke**
   - 至少保留一个普通 GitHub MCP 请求烟测，确认删除该 skill 不会让 repo/code/issues/PR 类请求明显退化

---

### Step 2: Add thin canonicalization helpers

改动点建议：

- `src/marten_runtime/automation/skill_ids.py`

要求：

- 只处理 GitHub digest old/new id
- 不做通用 skill fallback
- 供 register / view / dispatch / adapter 复用

---

### Step 3: Wire canonicalization into registration and update flows

改动点：

- `src/marten_runtime/tools/builtins/register_automation_tool.py`
- `src/marten_runtime/tools/builtins/update_automation_tool.py`
- 如有必要，收口到 automation model/store 层统一重算 fingerprint

要求：

- 新注册一律使用新 canonical id
- update 显式改 skill_id 时也走 canonicalization
- 任何语义字段变更后 fingerprint 正确刷新

必须避免：

- register 用 canonical 值，但 update 留 raw 值
- skill_id 已 canonicalize，但 fingerprint 还是旧值

---

### Step 4: Wire compatibility into presentation only, not data rewrite

改动点：

- `src/marten_runtime/tools/builtins/automation_view.py`
- 如确有必要，再最小化调整 list/detail tool 的返回形态

要求：

- old/new id 呈现统一业务名
- 不在读取时写回数据库
- detail 第一版允许保留 persisted raw `skill_id`

---

### Step 5: Wire narrow compatibility into automation dispatch

改动点：

- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`

聚焦：

- `_resolve_automation_skills(...)`

目标：

- GitHub trending digest automation 不再依赖 skill 文件存在
- old/new id 都能继续触发成功
- 范围严格限于 GitHub digest automation 兼容

必须避免：

- 只要 skill 找不到就一律静默跳过
- 扩成平台级 fallback

---

### Step 6: Update tests to the new source of truth

测试策略：

#### canonical behavior tests

主真相切到：

- `github_trending_digest`

#### compatibility tests

保留少量但关键的旧 id 覆盖：

- `github_trending_digest`

至少覆盖：

- persisted old record list/detail
- manual trigger
- dispatch without skill file
- display alias

#### skill tests

- 先收缩 `tests/test_skills.py` 中对真实 GitHub skill fixture 的依赖
- 再删除：
  - `tests/test_github_trending_digest.py`

---

### Step 7: Delete skill file only after compatibility is green

删除目标：

- `skills/github_trending_digest/SKILL.md`

只有在以下条件全部满足后才允许删除：

1. 新 canonical automation id 已落地
2. old id 兼容路径已覆盖测试
3. recurring digest 不再依赖该 skill 文件 load
4. 真实交互链路已验证无需该 skill
5. 真实 automation trigger 已验证无需该 skill 文件
6. 至少一条普通 GitHub MCP 非-trending 烟测通过

---

### Step 8: Run targeted verification

至少跑：

```bash
cd /Users/litiezhu/workspace/github/marten-runtime
PYTHONPATH=src python -m unittest \
  tests.test_automation \
  tests.test_automation_store \
  tests.test_automation_dispatch \
  tests.test_data_access_adapter \
  tests.test_tools \
  tests.test_contract_compatibility \
  tests.test_runtime_loop \
  tests.test_skills -v
```

如果 fingerprint 重算逻辑落在 model/store，还应确保相关新增测试进入上述集合。

---

### Step 9: Run full regression

```bash
cd /Users/litiezhu/workspace/github/marten-runtime
PYTHONPATH=src python -m unittest -v
```

---

### Step 10: Real-chain verification

#### Interactive trending verification

请求：

- `帮我看下今天 github 热门仓库`

要求：

- 不触发 `skill(load github_trending_digest)`
- 使用：
  - `mcp.list`
  - `mcp.call(server_id=github_trending, tool_name=trending_repositories)`

#### Automation verification

至少验证一条 GitHub trending recurring job：

1. register
2. list/detail
3. manual trigger

要求：

- 即使 job 使用旧 id，也能成功触发
- 新注册 job 使用新 canonical id
- dispatch 不依赖 skill 文件存在

#### Non-trending GitHub smoke

至少验证一条非 trending GitHub 请求，例如：

- repo 查询
- issue/PR 查询
- release/tag 查询

要求：

- 删除 skill 后没有出现明显的 GitHub MCP 主链退化
- 如果确实发现退化，应先补最薄替代说明/能力入口，再考虑删除 skill

---

## Acceptance Criteria

完成时，必须同时满足：

1. `github_trending_digest` skill 文件已删除
2. 新增 canonical automation id：`github_trending_digest`
3. 历史 `github_trending_digest` automation 仍能展示和触发
4. 新注册 automation 不再生成旧 id
5. 历史 `automation_id` 未被批量重命名
6. 首版未引入 SQLite 批量迁移框架
7. `semantic_fingerprint` 对 canonicalization / update 行为正确
8. 交互式 GitHub trending 请求不再依赖 skill
9. 全量测试通过
10. 真实交互链路通过
11. 真实 automation 链路通过
12. 至少一条非-trending GitHub MCP 烟测通过

---

## Required File Change Checklist

### Must change

- `src/marten_runtime/tools/builtins/register_automation_tool.py`
- `src/marten_runtime/tools/builtins/update_automation_tool.py`
- `src/marten_runtime/tools/builtins/automation_view.py`
- `src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- `src/marten_runtime/automation/models.py` 或其他负责 fingerprint 重算的薄边界
- `tests/test_automation.py`
- `tests/test_automation_store.py`
- `tests/test_automation_dispatch.py`
- `tests/test_data_access_adapter.py`
- `tests/test_tools.py`
- `tests/test_contract_compatibility.py`
- `tests/test_runtime_loop.py`
- `tests/test_skills.py`
- `skills/github_trending_digest/SKILL.md` (final delete)
- `tests/test_github_trending_digest.py` (final delete)

### Recommended docs sync

- `README.md`
- `README_CN.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/archive/plans/2026-04-05-github-trending-mcp-plan.md`
- `docs/archive/plans/2026-04-05-delete-github-hot-repos-digest-plan.md`
- `STATUS.md`

---

## Rollback Strategy

如果删除过程中出现历史 automation 无法触发，或 GitHub MCP 非-trending 主链明显退化：

1. 恢复 skill 文件删除
2. 保留新 canonical id 代码
3. 保留 fingerprint / dispatch / presentation 的兼容修复
4. 先让兼容层稳定，再决定是否做第二次删除

不要为了快速通过而：

- 在 runtime core 增加 GitHub 专用兜底
- 在 mcp builtin 写 GitHub 热榜专用路由
- 把 automation 兼容扩成通用 skill fallback 平台
- 直接批量 rewrite 历史 `automation_id`

---

## Anti-Drift Rules For The Coding Agent

出现以下情况说明方案偏了：

- 想在 `runtime/loop.py` 写 GitHub digest 特判
- 想在 `mcp_tool.py` 里写“热门仓库优先某工具”分支
- 想保留 skill 文件只是为了历史数据不报错
- 想把 automation 兼容扩成通用 skill fallback 平台
- 想跳过 automation backward compatibility 直接删 skill
- 想直接批量迁移 SQLite 数据来掩盖 fingerprint / dispatch 设计问题
- 想偷偷重命名历史 `automation_id`
- 只验证 trending，不验证普通 GitHub MCP 请求

如果发生这些倾向，应立即停下并回到：

> **automation id canonicalization + 窄兼容层 + fingerprint 正确性 + 非-trending smoke check**

这个主方案。
