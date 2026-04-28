# Progressive Disclosure + LLM-First Capability Design

## 1. Goal

本设计用于收敛 `marten-runtime` 当前在 skill 与 MCP 能力暴露上的实现方向，使其符合以下长期原则：

- progressive disclosure
- LLM first
- harness first

目标不是把 runtime 做成更大的 orchestration 平台，而是把能力暴露方式改成更薄、更稳、更可扩展的 harness 形态：

1. 默认只向模型暴露紧凑的能力摘要，而不是完整技能正文或全量工具 schema
2. 让模型自己决定是否需要展开某个 skill 或 MCP 能力，而不是由宿主用 `if/else` 预先做聊天类型分类
3. 让 skill 与 MCP 在未来数量持续增长时仍然可插拔、可维护、可观测

这份设计是能力装配层设计，不涉及：

- automation 生命周期边界变化
- adapter 边界变化
- durable queue / worker 平台
- 通用 workflow engine

## 2. Source-Of-Truth Constraints

以下约束是本设计的硬边界，后续实现不得偏离。

### 2.1 Skills Directory Boundary

`skills` 目录采用单层插件式结构，对齐 `codex` / `opencode` 的技能目录风格。

允许的结构：

```text
skills/
  skill_a/
    SKILL.md
    script/
    assets/
    references/
  skill_b/
    SKILL.md
```

明确约束：

- `skills/` 下只能直接放 skill 目录
- 不引入 `system/`、`shared/`、`app/`、`users/` 等二级分类目录
- skill 的启用、优先级、作用域不能依赖目录层级表达
- skill 是否可见、是否启用，应该由 metadata 或 runtime policy 决定

### 2.2 MCP Reload Boundary

`mcps.json` 的改动通过重启服务生效，这是合理边界。

明确约束：

- 不要求 runtime 在进程内热更新 `mcps.json`
- 不要求 MCP server 配置变更实时自动生效
- MCP tool discovery 可以在运行中按需调用 server 获取，但 server config 本身以进程启动时为准

### 2.3 Harness Boundary

宿主是 harness，不是 agent 思维替代层。

明确约束：

- 宿主不负责消息语义分类
- 宿主不负责“这句像搜索 / 这句像闲聊 / 这句像时间查询”的业务分流
- 宿主只负责能力目录、按需装配、执行、权限控制、诊断

### 2.4 LLM-First Boundary

模型必须自己做能力选择。

明确约束：

- 模型决定是否要加载某个 skill
- 模型决定是否要展开某个 MCP server 的工具列表
- 模型决定是否真正发起工具调用
- 宿主不能继续通过 turn 级 `if/else` 裁剪能力面来替模型做决策

### 2.5 Progressive Disclosure Boundary

默认暴露的是 summary，不是 detail。

明确约束：

- 默认只暴露 skill summary
- 默认只暴露 builtin capability summary
- 默认只暴露 MCP server summary
- skill 正文、MCP tool schema、MCP tool 明细只能按需展开

### 2.6 Non-Expansion Boundary

本设计不允许借机扩大系统中心。

明确约束：

- 不引入通用 capability orchestration framework
- 不引入新的 agent router 分支系统
- 不引入按聊天类型分类的 policy engine
- 不引入动态插件 marketplace / 远程 skill 安装中心
- 不引入新的 durable memory / workflow / worker 层

## 3. Problem Statement

当前 `marten-runtime` 在能力暴露上存在两类问题：

### 3.1 Skill Loading Path Has The Wrong Shape

当前 skill 侧虽然有可发现性，但不是 OpenClaw 风格的“summary only + load on demand”。

当前实现：

- [SkillLoader.load_all()](../src/marten_runtime/skills/loader.py) 每次扫描所有 `SKILL.md`
- [SkillService.build_runtime()](../src/marten_runtime/skills/service.py) 每个 turn 都读取完整 skill body
- runtime 最终只渲染 summary 给模型，但正文已经提前全部读入内存并参与组装

问题：

- skill 数量增长后，加载成本线性增加
- “默认全量读取正文”不符合 progressive disclosure
- 当前目录结构也带有 `system/shared/app` 的工程分层，不符合单层插件式 skill 目录约束

### 3.2 MCP Exposure Path Is Still Too Static

当前 MCP 侧已经有配置和 discovery，但运行模型仍然依赖启动期的静态工具注册。

当前实现：

- [load_mcp_servers()](../src/marten_runtime/mcp/loader.py) 在启动时读取 `mcps.json`
- [discover_mcp_tools()](../src/marten_runtime/mcp/discovery.py) 在启动时发现工具
- [build_http_runtime()](../src/marten_runtime/interfaces/http/bootstrap.py) 在启动时把所有 MCP tool 注册进全局 `ToolRegistry`

问题：

- 新增 MCP server 或工具时，需要重启才能生效，这本身没问题
- 真正的问题是：重启后仍然把全量 MCP tool 直接作为模型可见工具面暴露
- 当 MCP server 与 tool 越来越多时，prompt 和 tool surface 会继续膨胀

### 3.3 Current Turn-Level Narrowing Is A Symptom Fix

最近为了降低延迟，加了 turn 级工具收窄逻辑。

这类逻辑的问题不在于“写得不够聪明”，而在于方向本身不对：

- 它依赖宿主提前判断意图
- 它依赖消息内容分类
- 它会不断长出新的 if/else
- 它让 harness 变成 agent 决策替代层

这和 `LLM first` 原则冲突。

## 4. Review Of Strong Reference Patterns

### 4.1 OpenClaw / OTTClaw

吸收的正确模式：

- skill 只先给 summaries
- skill 正文按需加载
- MCP 先给 server summary，再按需看 detail / call

典型证据：

- OTTClaw 的 [loader.go](/Users/litiezhu/workspace/github/OTTClaw/internal/skill/loader.go) 明确写了“服务启动时只加载 HEAD；LLM 需要时通过 get_skill_content 懒加载 CONTENT”
- OTTClaw 的 [agent.go](/Users/litiezhu/workspace/github/OTTClaw/internal/agent/agent.go) 在 system prompt 中只注入 skills summaries
- OTTClaw 的 [mcp.go](/Users/litiezhu/workspace/github/OTTClaw/internal/tool/mcp.go) 用统一入口做 `list/detail/call`

不应照搬的模式：

- OTTClaw 仍有 [MatchIntent()](/Users/litiezhu/workspace/github/OTTClaw/internal/mcp/registry.go) 这种关键词匹配式 MCP server 预筛选
- 这仍然是宿主基于消息文本做能力推断，工程化味道太重

### 4.2 Nanobot

吸收的正确模式：

- host 负责声明式能力装配
- runtime 不应该提前把一切细节塞给模型
- agent 的工作环境应该由“可声明的能力集合”组成，而不是分支型路由器

本设计吸收的是方向：

- harness 负责 capability declaration
- 模型负责 capability selection

### 4.3 NanoClaw

吸收的正确模式：

- 少抽象
- 少分支
- 少核心膨胀
- 用最小机制解决问题

对本项目的实际要求是：

- 不做 capability framework 大重构
- 不引入四五个新中心模块
- 只保留少数几个必要原语

## 5. Final Target Shape

最终目标只保留三个原语：

1. `skill summaries`
2. `host-declared capability catalog`
3. `on-demand expansion`

这是一个薄 harness 设计，不是多层平台设计。

### 5.1 Skill Summaries

默认注入到 prompt 的 skill 信息应当只包含：

- `skill_id`
- `name`
- `description`
- `aliases`
- `tags`（可选）
- `examples`（可选，必须短）
- `always_on`（若存在）

默认不注入：

- skill 全文
- skill 下 references 内容
- script 目录内容

### 5.2 Host-Declared Capability Catalog

默认注入到 prompt 的 capability catalog 应当只包含：

- builtin capability family summaries
- MCP server summaries
- 必要的使用原则

catalog 只回答两个问题：

1. 有哪些能力
2. 大致什么时候用

它不应提前把所有 schema 细节展开。

### 5.3 On-Demand Expansion

模型需要更多上下文时，运行时只提供极少数展开入口：

- `skill.load(skill_id)`
- `mcp.list(server)`
- `mcp.detail(server, tool)` 或等价查询
- `mcp.call(server, tool, args)`

这几个入口就是渐进式披露的全部机制。

## 6. Minimal Architecture

### 6.1 Components To Keep

保留现有这些方向：

- skill metadata parsing
- skill filtering
- MCP config loading from `mcps.json`
- MCP tool discovery / invocation client
- runtime loop
- diagnostics surfaces

### 6.2 Components To Remove Or Downgrade

需要删除或降级的内容：

- turn 级 `_resolve_turn_allowed_tools(...)` 这类基于消息内容的业务分流
- 基于“plain/time/search/automation”之类聊天类型的宿主决策
- 预先把所有 MCP tool 作为模型可见工具长期暴露

### 6.3 Minimal New Primitives

最多新增或重塑以下原语：

1. `SkillCatalog`
- 负责扫描单层 `skills/` 目录
- 默认只产出 skill summaries

2. `CapabilityCatalog`
- 负责汇总 builtin families + MCP servers 的 summaries

3. `OnDemandExpansion`
- 负责 `skill.load` 与 `mcp.list/detail/call`
- 只在当前 run 内扩展细节，不作为全局常驻展开

注意：

- 这三个原语不一定要对应三个重型类
- 可以只是现有模块上的职责重分配
- 不允许为了“概念完整”而造新的大抽象层

## 7. Skill Design Constraints

### 7.1 Directory Contract

技能目录必须满足：

```text
skills/
  my_skill/
    SKILL.md
```

可选子目录：

- `script/`
- `assets/`
- `references/`

禁止：

- `skills/system/...`
- `skills/shared/...`
- `skills/app/...`
- `skills/users/...`

### 7.2 Loading Contract

默认加载只读取 `SKILL.md` 的 head/front-matter 与必要摘要段。

按需加载时才读取：

- skill 正文
- references
- assets
- script 说明

### 7.3 Visibility Contract

skill 可见性不依赖目录层级表达。

允许由 metadata 表达：

- enabled / disabled
- allowed_agents
- allowed_channels
- always_on

但不允许用目录树表达权限语义。

## 8. MCP Design Constraints

### 8.1 Config Contract

MCP server 来源以 `mcps.json` 为准。

允许：

- 进程启动时读取 `mcps.json`
- 重启后生效

不要求：

- 运行中监听文件变化
- 运行中自动重建 registry

### 8.2 Exposure Contract

默认不把每个 MCP tool 都注册成模型第一轮可见 function。

默认只暴露：

- server name
- server description
- server capabilities summary

按需再展开：

- server 下 tool list
- tool description
- tool schema

### 8.3 Execution Contract

MCP 具体调用仍由 host 执行。

模型不能直接越过 host 使用 MCP。

host 负责：

- server 生命周期
- transport
- timeout
- retry
- error normalization

模型只做选择与参数生成。

## 9. Prompt Construction Rules

### 9.1 Default Prompt Must Stay Compact

默认 system / working prompt 中允许出现：

- role / mission
- tool usage principles
- skill summaries
- capability catalog summaries
- current session context

默认 prompt 中不允许出现：

- 所有 skill 正文
- 所有 MCP tools schema
- 所有 builtin tool schema

### 9.2 Prompt Should Guide Expansion

prompt 必须明确告诉模型：

- 如果需要更详细 skill 指令，调用 `skill.load`
- 如果需要某个 MCP server 的工具列表，调用 `mcp.list`
- 如果需要具体工具细节，再看 detail 或直接调用

prompt 的职责是告诉模型“如何按需展开”，而不是提前把所有细节塞进去。

## 10. Anti-Patterns

以下做法在本设计中明确判定为错误方向：

### 10.1 Turn-Type Classification

错误示例：

- 识别“这句像时间查询”然后只给 `time`
- 识别“这句像搜索”然后只给搜索工具
- 识别“这句像普通聊天”然后不给任何能力

原因：

- 这是宿主替模型做能力选择
- 逻辑会持续膨胀
- 违背 LLM first

### 10.2 Full Pre-Expansion

错误示例：

- 默认把所有 skill 正文拼进 prompt
- 默认把所有 MCP tool schema 注册成第一轮可见 function

原因：

- 不符合 progressive disclosure
- 能力越多越难扩展
- 会导致 prompt/tool 面指数膨胀

### 10.3 Directory-Semantics Coupling

错误示例：

- 用 `system/shared/app/users` 目录层级表达能力可见性

原因：

- 插件扩展不自然
- 目录结构承担了太多 runtime 语义
- 不符合 `skills/` 平铺插件约束

## 11. Current-State Review Against Target

### 11.1 What Already Aligns

当前仓库已经具备一些可复用基础：

- skill markdown parsing
- skill filtering
- MCP config loading
- MCP discovery client
- runtime loop diagnostics

### 11.2 What Is Misaligned

当前偏移点：

1. skills 目录结构偏工程化
- 目前 roots 仍是 `skills/system`、`skills/shared`、app-local skills

2. skill 读取方式不符合 summary-only
- 当前每次 build runtime 都全量读完整正文

3. MCP tool 面仍然偏静态全量暴露
- 当前启动时 discovery 后直接注册入 `ToolRegistry`

4. turn 级 if/else 收窄方向错误
- 它是 symptom fix，不是最终形态

## 12. Migration Direction

本设计不直接写实施细节，但要求迁移顺序必须遵守“先去工程化，再去扩能力面”的原则。

推荐顺序：

### Phase 1: Fix Skill Shape

- 收敛 skill 目录到单层 `skills/*/SKILL.md`
- skill runtime 改成默认只读 summary
- 增加 `skill.load`

成功标准：

- 新 skill 放到 `skills/` 下即可被 catalog 看见
- 默认 prompt 不再读取全部 skill 正文

### Phase 2: Fix MCP Shape

- host 仅在启动时读取 `mcps.json`
- 默认 prompt 只暴露 MCP server summaries
- 增加按需 `mcp.list/detail/call`

成功标准：

- 新增 MCP server 经重启后可见
- 默认第一轮不再暴露全量 MCP tool schema

### Phase 3: Remove Turn-Type Narrowing

- 删除基于消息文本的 turn 级能力裁剪
- 用 capability catalog + on-demand expansion 替代

成功标准：

- 宿主不再做 plain/time/search 业务分类
- 模型仍能稳定完成常见任务

## 13. Verification Requirements

设计落地时必须验证以下事实：

### 13.1 Skill Extensibility

- 新增 `skills/new_skill/SKILL.md` 后，runtime 能发现该 skill
- 默认 prompt 只出现该 skill summary
- 模型可以按需触发 `skill.load(new_skill)`

### 13.2 MCP Extensibility

- 修改 `mcps.json` 后重启服务，新增 server 可见
- 默认 prompt 只出现新 server summary
- 模型可以按需 `mcp.list(server)` 并进一步调用工具

### 13.3 No Host Intent Routing

- runtime 不再包含“聊天类型 -> 工具面”的业务分支
- 普通对话、搜索类对话、任务类对话都通过同一 capability-selection 机制工作

### 13.4 Prompt Compactness

- 对比当前实现，默认 prompt 长度应显著下降
- MCP/server/skill 增多时，默认 prompt 不应线性携带全部细节

## 14. Final Design Decision

最终设计采用以下最小原则组合：

- 吸收 OpenClaw / OTTClaw 的 `skill summary only + load on demand`
- 吸收 Nanobot 的 `host 负责声明式能力装配`
- 吸收 NanoClaw 的 `少抽象、少分支、少核心膨胀`

因此最终不采用：

- 多层 capability framework
- 聊天类型分类器
- turn 级 if/else 能力路由器
- 默认全量工具/技能细节注入

最终只保留三个薄原语：

1. `skill summaries`
2. `capability catalog`
3. `on-demand expansion`

这就是本项目在 skill 与 MCP 能力扩展上的长期目标形态。
