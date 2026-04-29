# 2026-04-05 GitHub Trending MCP Plan

## Goal

为 `marten-runtime` 增加一个**独立、窄、repo-local 的 MCP server**：`github_trending`，只提供 `trending_repositories` 工具，用真实 GitHub Trending 页面作为数据源，替代当前“GitHub 热门仓库”场景下依赖 skill + `search_repositories` 近似推导的路径。

目标主链：

- LLM 理解“GitHub 热门仓库 / trending / 今日开源热榜”
- 通过现有 `mcp` family tool 调用 `github_trending.trending_repositories`
- renderer 直接渲染榜单结果

不在 runtime 主链引入 GitHub 专用 if/else，不把 trending 逻辑塞进 builtin tool 或 renderer 特判。

---

## Why This Plan Exists

当前现状已验证：

- 上游官方 GitHub MCP（`ghcr.io/github/github-mcp-server`）**没有** `trending` 专用工具
- 现有 `search_repositories` 只能做近似搜索，不是 GitHub Trending 榜单真值
- 当前 skill 虽能改善“今天热门仓库”的语义，但会引入额外 LLM/tool 回合，不够稳，也不够薄

因此更符合 harness 的解法是：**把 trending 语义下沉为 MCP 能力，而不是继续堆 skill/prompt 规则。**

---

## Non-Goals

本次不做：

- 不扩写 runtime builtin GitHub tool
- 不修改 `src/marten_runtime/runtime/loop.py` 增加 GitHub 场景专用判断
- 不修改 `src/marten_runtime/tools/builtins/mcp_tool.py` 增加 `if user wants trending`
- 不实现 GitHub 全量 wrapper MCP
- 不实现 browser automation 抓取
- 不实现 token/cookie 登录态抓取
- 不引入复杂缓存、持久化、重试平台
- 不在第一版支持 developer trending
- 不在第一版支持 spoken language 过滤，除非实现代价几乎为零

---

## Design Constraints

### Must Keep

- 保持 `LLM + MCP + renderer` 主链
- 对模型来说，`trending_repositories` 仍然是**黑盒工具**
- runtime 继续只暴露 family-level `mcp`
- 新能力通过 `mcps.json` 配置接入
- 默认不要求 GitHub token
- 第一版只依赖公开 Trending 页面

### Must Avoid

- GitHub 专用 runtime 分支
- “如果用户说热门仓库就偷偷改工具”的隐式逻辑
- 让 renderer 知道“GitHub trending”业务语义
- skill 中继续承载 fallback 规则作为主真相

---

## Proposed Shape

### New MCP server

新增一个 repo-local MCP server：

- server_id: `github_trending`

建议放置为 repo 内独立实现，而不是 runtime builtin。

推荐落点（二选一，以更薄为准）：

1. `apps/github_trending_mcp/`
2. `src/marten_runtime/mcp_servers/github_trending.py`

### Chosen implementation location

本次实际实现选择：

- `src/marten_runtime/mcp_servers/github_trending.py`

原因：

- 与当前仓库的 `PYTHONPATH=src` 测试/运行方式天然兼容
- stdio 子进程可以直接用 `python -m marten_runtime.mcp_servers.github_trending`
- 仍然保持它是**独立 MCP 进程**，而不是 runtime builtin
- 比在 `apps/` 下再额外处理 import/cwd 更稳、更薄

### Exposed tool

只暴露一个工具：

- `trending_repositories`

### Input schema

第一版只保留最小参数集合：

```json
{
  "since": "daily",
  "language": "python",
  "limit": 10
}
```

字段定义：

- `since`: optional, enum = `daily | weekly | monthly`, default `daily`
- `language`: optional, string
- `limit`: optional, integer, default `10`, max `25`

### Output schema

返回结构化榜单，不让 LLM 自己猜：

```json
{
  "source": "github_trending",
  "since": "daily",
  "language": "python",
  "fetched_at": "2026-04-05T12:30:00+08:00",
  "items": [
    {
      "rank": 1,
      "full_name": "owner/repo",
      "name": "repo",
      "owner": "owner",
      "url": "https://github.com/owner/repo",
      "description": "short description",
      "language": "Python",
      "stars_total": 12345,
      "stars_period": 321,
      "forks_period": 12
    }
  ]
}
```

允许：

- `language` 为空
- `description` 为空
- `stars_period` 为空（如果页面解析不到）
- `forks_period` 为空

但必须保证：

- `since`
- `fetched_at`
- `items[*].rank`
- `items[*].full_name`
- `items[*].url`

---

## Data Source Strategy

### Source of truth

直接抓取：

- `https://github.com/trending`

使用 query params：

- `since=daily|weekly|monthly`
- `l=<language>`（如果语言不为空）

### Fetch strategy

第一版使用轻量 HTTP 请求 + HTML 解析：

- `httpx` 或标准库 HTTP
- 不引入浏览器自动化

### Parsing strategy

只解析 GitHub Trending 页面可稳定定位的核心字段：

- repo full_name
- repo URL
- description
- primary language
- total stars
- period stars（例如 “123 stars today”）

不要在第一版为了“页面更漂亮”解析过多弱结构字段。

---

## Implementation Plan

## Step 1: Add failing tests first

### Goal

先锁定 repo-local MCP server 的 contract，再写实现。

### Tests to add

建议新增：

- `tests/test_github_trending_mcp.py`

至少覆盖：

1. `trending_repositories` 默认参数：
   - 未传参数时默认 `since=daily`, `limit=10`

2. 参数校验：
   - `since` 非法时报错
   - `limit <= 0` 报错
   - `limit > 25` 被拒绝或裁剪（推荐拒绝，保持简单）

3. HTML 解析：
   - 给定固定 fixture HTML，能解析出至少 2 条 repo 记录
   - 正确提取：
     - `full_name`
     - `url`
     - `description`
     - `language`
     - `stars_total`
     - `stars_period`

4. 输出 schema：
   - 顶层包含 `source/since/fetched_at/items`
   - `items` 按页面顺序稳定赋值 `rank=1..n`

5. MCP server list_tools / call_tool contract：
   - server 对外暴露的工具名为 `trending_repositories`

### Fixtures

建议新增 fixture：

- `tests/fixtures/github_trending_daily.html`

必要时可再加：

- `tests/fixtures/github_trending_weekly.html`

但第一版尽量只用一个 fixture 即可。

---

## Step 2: Implement the repo-local MCP server

### Goal

把 trending 能力实现为独立 sidecar，不污染 runtime 核心。

### Files to add

推荐新增：

- `src/marten_runtime/mcp_servers/github_trending.py`

第一版实际实现收敛为**单文件 sidecar**，把：

- request model
- response model
- fetcher
- parser
- stdio MCP entrypoint

都放在同一个文件里，先保证边界清晰和实现最薄；后续只有在文件明显膨胀时再拆分。

### Internal module responsibilities

#### `models.py`

只定义：

- request model
- response model
- item model

不要带业务逻辑。

#### `fetcher.py`

负责：

- 构建 Trending URL
- 发 HTTP 请求
- 返回 HTML 文本

不要在这里解析 HTML。

#### `parser.py`

负责：

- 从 HTML 提取 repo 条目
- 生成结构化 `items`

不要在这里做网络请求。

#### `server.py`

负责：

- 暴露 MCP tool
- 参数校验
- 调用 fetcher + parser
- 产出最终结果

不要在这里做复杂缓存和策略逻辑。

---

## Step 3: Register the sidecar in `mcps.json`

### Goal

让 runtime 通过现有 MCP 机制发现并调用新 server。

### Config change

更新：

- `mcps.json`

新增一个 server，例如：

```json
{
  "servers": {
    "github_trending": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "marten_runtime.mcp_servers.github_trending"],
      "timeout_seconds": 30
    }
  }
}
```

实际 command/args 以可执行路径最稳为准。

### Important constraints

- 不要求 `GITHUB_PERSONAL_ACCESS_TOKEN`
- 不与现有 `github` server 混淆
- 不代理现有 GitHub MCP 的其他能力

---

## Step 4: Make it model-discoverable through existing MCP flow

### Goal

不改 runtime 行为，只确认当前 progressive MCP surface 能发现它。

### What to check

现有路径已经支持：

- `mcp.list`
- `mcp.detail`
- `mcp.call`

所以本步应该是**验证**而不是重构。

编码 agent 需要确认：

- `GET /diagnostics/runtime` 能看到新 server
- `mcp.detail(server_id=github_trending)` 能看到 `trending_repositories`
- 模型可通过现有 `mcp` family tool 调用它

### Do not do

- 不增加新的 builtin `github_trending`
- 不改 capability catalog 去硬编码 GitHub 分支

如果确实需要更好描述，只允许做**通用型小增强**，例如：

- 在 MCP server summary 里让新 server 名称/描述更清晰

但不要为 GitHub 热榜写特殊路由器。

---

## Step 5: Narrow the GitHub skill after MCP is working

### Goal

在 `trending_repositories` 可用后，把 `github_trending_digest` 从“主真相”降级为“补充说明”或进一步收缩。

### Recommended change

更新：


调整方向：

- 删除 fallback 规则作为主路径
- 优先要求：
  - GitHub trending 类请求先看 MCP 是否提供 `trending_repositories`
- 保留：
  - repo/code/issues/PR/release 等 GitHub 一般性读写说明

### Stretch goal

如果实测 `trending_repositories` 足够稳：

- 可以继续评估是否删掉 `github_trending_digest`
- 但这不属于本计划的第一阶段 done criteria

---

## Step 6: Verification

### Targeted tests

至少运行：

```bash
cd /Users/litiezhu/workspace/github/marten-runtime
PYTHONPATH=src python -m unittest tests.test_github_trending_mcp -v
PYTHONPATH=src python -m unittest tests.test_runtime_mcp tests.test_contract_compatibility -v
```

### Local MCP verification

需要做一个最小脚本或 smoke：

- 启动 runtime
- 调 `/diagnostics/runtime`
- 确认 `github_trending` 被发现

### Real chain verification

至少验证一个真实请求：

- `帮我看下今天 github 热门仓库`

然后查看：

- `/diagnostics/run/{run_id}`

必须确认：

- 调到的是 `mcp`
- 目标 server 是 `github_trending`
- 目标 tool 是 `trending_repositories`
- 最终回答不再依赖 `search_repositories` 拼 stars

### Success criteria for the real run

- 不需要 `time`
- 不需要 fallback
- 不需要 `skill(load github_trending_digest)` 才能答对
- 最终输出明确是 trending 榜单结果

---

## Exact Acceptance Criteria

本计划完成时，必须同时满足：

1. 上游无 trending 工具时，repo 内已补一个**独立 MCP sidecar**
2. sidecar 只暴露 `trending_repositories`
3. sidecar 默认不依赖 GitHub token
4. runtime 主链无 GitHub 专用分支
5. “今天 GitHub 热门仓库”真实链路能打到 `github_trending.trending_repositories`
6. 最终回答不再依赖 skill 中的 fallback 语义
7. 相关 tests 与 smoke 验证通过

---

## Anti-Drift Checklist For Coding Agent

实现过程中，出现以下任一情况应立即回退并重审：

- 想在 `runtime/loop.py` 增加 GitHub 热门仓库分支
- 想在 `tools/builtins/mcp_tool.py` 增加 trending 特判
- 想在 `renderer` 里写 GitHub 热榜业务格式判断
- 想继续依赖 skill 来约束“today/fallback/window”
- 想把整个 GitHub MCP 包一层全代理 wrapper
- 想引入浏览器自动化、缓存系统、数据库表、复杂重试平台

如果发生这些冲动，说明实现已经偏离“thin harness + MCP-first”目标。

---

## Suggested Execution Order For Coding Agent

1. 写 `tests/test_github_trending_mcp.py` + HTML fixture，先 red
2. 实现 parser + request validation，跑到 green
3. 实现 repo-local MCP server stdio entrypoint
4. 在 `mcps.json` 注册 `github_trending`
5. 跑 targeted MCP tests
6. 启动 runtime 做 `/diagnostics/runtime` smoke
7. 做真实链路验证
8. 收缩 GitHub skill 文案
9. 更新 `STATUS.md` / `docs/ARCHITECTURE_CHANGELOG.md` / 必要文档

---

## Files Expected To Change

高概率：

- `mcps.json`
- `docs/archive/plans/2026-04-05-github-trending-mcp-plan.md`
- `STATUS.md`
- `tests/test_github_trending_mcp.py`
- `tests/fixtures/github_trending_daily.html`

新增实现：

- `apps/github_trending_mcp/*`

低概率可选：

- `docs/ARCHITECTURE_CHANGELOG.md`
- `README.md`
- `README.md`

---

## Open Questions (Resolve During Implementation, Not Before)

这些不是 blocker，可以在实现时就地决策：

- `apps/github_trending_mcp/` 还是 `src/marten_runtime/mcp_servers/` 更薄
- 抓取使用 `httpx` 还是标准库
- `limit > 25` 是 reject 还是 clamp
- `stars_period` 解析不到时是 `null` 还是 `0`（推荐 `null`）

原则：选择**更薄、更少状态、更少耦合**的方案。
