# Automation Domain Adapter Design

## 1. Goal

在不把 `marten-runtime` 扩成通用 workflow 平台、通用数据库 agent、或宽泛 control-plane backend 的前提下，把 `automation` 域纳入已经建立的薄 adapter 内核路线。

目标不是把 automation 全部系统内部机制抽象成一个大一统平台，而是把“用户可感知的 automation 资源层”收敛到统一 adapter 内核下，使主 agent 可以继续通过自然语言完成：

- 查询当前 automation
- 查询单个 automation 详情
- 创建 automation
- 修改 automation
- 删除 automation
- 暂停 / 恢复 automation

同时保持这些边界不变：

- 用户路径仍然是 `LLM + agent + skill + builtin tool`
- LLM 看到的是 automation 领域函数，不是表、SQL、裸 CRUD
- scheduler / dispatch window / delivery dedupe 仍然是系统内部实现细节
- automation 的注册、执行、cron 调度逻辑不因此被“平台化”

主链仍保持为：

- `channel -> binding -> agent -> LLM -> MCP/builtin tool -> LLM -> channel`

这里新增的只是统一 control-plane resource adapter，不是新的 runtime 骨架。

## 2. Source-Of-Truth Constraints

- 保持项目中心不变：`channel -> binding -> agent -> LLM -> MCP/tool -> skill -> LLM -> channel`
- 工程只是 harness，不取代 agent 决策
- 不对 LLM 暴露表名、SQL、自由 where 条件、通用 `crud(table=...)`
- 不把 automation scheduler 内部状态暴露成 agent 可直接操作的资源
- `automation` 纳入 adapter 时，只纳入“用户可感知的 automation 资源层”
- `register_automation` 可以继续作为 create 的自然语言入口，但底层应收敛到同一 resource 内核
- `pause_automation` / `resume_automation` 属于窄的领域 update，不单独抬升为平台概念
- 不在本阶段重构 `/automations/{id}/trigger`、due-window scheduler、dispatch window、delivery dedupe
- 不引入 generic memory、worker-first、durable queue、control-plane app framework

这里补一条长期默认原则，避免后续模块继续混淆：

- 后续新增模块如果主要需求是“表数据 / 持久化资源”的 CRUD，默认优先走 adapter 内核
- 后续新增模块如果主要需求是“定时触发 / 调度执行 / 生命周期管理”，默认优先走 automation 系统层

也就是说：

- adapter 负责资源 CRUD
- automation 负责注册、调度、触发、执行生命周期

这两层长期分离，不合并成一个宽泛 control-plane 平台。

## 3. Problem Statement

当前 `automation` 域已经有可用能力，但工程形态仍然是“按动作散落”：

- `register_automation`
- `list_automations`
- `update_automation`
- `delete_automation`
- `pause_automation`
- `resume_automation`

这些 builtin tools 都直接触达 `AutomationStore`，每个工具自己处理部分字段、过滤、返回结构。

这在 MVP 阶段是合理的，但继续扩展会出现几个问题：

1. automation 域的资源语义散在多个工具里
- 列表字段、详情字段、更新允许字段、返回格式容易慢慢分叉

2. 后续如果还有其他持久化域
- 每个域都重复写一套 list/get/update/delete glue code

3. self-improve 已经建立 adapter 内核
- automation 如果长期留在旧路径，control-plane 结构会变成两种风格并存

4. 如果未来直接追求“统一 CRUD”
- 很容易退化成对 LLM 暴露表结构或通用 DB 操作
- 这会偏离项目要的“领域能力优先”

因此，需要一个明确的 automation adapter 设计，既统一内核，又不裸露 CRUD 给 LLM。

## 4. Non-Goals

以下明确不属于本设计：

- 通用 SQL agent
- 面向 LLM 的统一 `create/read/update/delete(table, filters, values)` 接口
- 调度器内部表查询
- dispatch window 查询 / 删除 / 修复
- delivery receipt / dead-letter / delivery session 的 agent 侧管理
- 任意 automation 执行历史回放平台
- 通用 app / tenant / workflow runtime

## 5. Intended User Experience

用户通过自然语言表达 automation 管理意图，例如：

- “现在有哪些定时任务”
- “看一下晚上 11 点 50 那个任务的详情”
- “把这个任务改到早上 9 点”
- “暂停这个任务”
- “恢复那个 github 热榜任务”
- “删掉这个任务”

用户不需要知道：

- `automations` 表结构
- `automation_id` 如何生成
- `semantic_fingerprint`
- dispatch window 如何去重
- scheduler 如何计算 `scheduled_for`

预期行为：

1. 主 agent 识别出这是 automation 管理域
2. 命中 `automation_management` skill
3. skill 指导 LLM 先查再改，必要时做一次短澄清
4. builtin tool 暴露 automation 领域函数
5. builtin tool 底层统一走 adapter 内核
6. LLM 只负责把结果组织成自然语言回复

## 6. Scope

### 6.1 In Scope

- 把 automation 资源层纳入统一 adapter 内核
- 新增 automation 域 entity spec
- 收敛 automation 的 list / detail / create / update / delete 行为
- 把 pause / resume 明确建模为窄 update 行为
- 为 automation 域补一个显式 detail 工具
- 让现有 automation builtin tools 复用统一 adapter 内核，而不是各自直连 store
- 保持现有 `automation_management` skill 不变或只做最小必要更新

### 6.2 Out Of Scope

- 重做 automation 调度器
- 重做 automation 手动 trigger 路径
- 把 operator HTTP `/automations` 全量迁到 adapter
- 暴露 dispatch windows、delivery sessions、dead letters 给 LLM
- 把 GitHub digest skill 或 self-improve internal automation 做统一 workflow 编排

## 7. Domain Boundary

### 7.0 Resource CRUD vs Automation Lifecycle

这个设计要求长期区分两类能力：

- `adapter`
  - 负责资源层 CRUD
  - 关心“有哪些记录、详情是什么、如何增删改查”

- `automation`
  - 负责定时任务生命周期
  - 关心“如何注册、何时触发、如何调度、如何 dispatch、如何执行”

因此：

- 一个模块新增表操作时，默认优先进入 adapter
- 一个模块新增定时任务能力时，默认优先复用 automation

automation 本身作为“任务资源”可以被 adapter 查询和修改；
但 automation 的调度与执行生命周期，不能被回卷进 adapter。

### 7.1 What Counts As The Automation Resource Layer

应纳入 adapter 的是单个 automation job 资源本身，核心字段包括：

- `automation_id`
- `name`
- `app_id`
- `agent_id`
- `prompt_template`
- `schedule_kind`
- `schedule_expr`
- `timezone`
- `session_target`
- `delivery_channel`
- `delivery_target`
- `skill_id`
- `enabled`
- `internal`
- `semantic_fingerprint`

其中：

- `internal = true` 的 automation 资源默认不暴露给用户侧 list/detail
- `semantic_fingerprint` 是系统内去重字段，不应成为用户主视角，但可留在 adapter 返回中供 tool 内部判断

### 7.2 What Stays Outside The Resource Layer

以下对象仍然留在系统内部，不纳入 adapter：

- `automation_dispatch_windows`
- scheduler tick / due-window scan
- manual trigger dispatch envelope
- final delivery dedupe keys
- delivery session state

原因很简单：这些不是用户在对话里直接管理的“任务资源”，而是任务执行系统的内部控制状态。

## 8. Architecture

### 8.1 Layered Shape

继续使用四层结构：

1. `agent + selector`
- 识别 automation 管理意图

2. `skill`
- 提供 automation 领域语义、操作边界、推荐 tool 顺序

3. `domain builtin tools`
- 对 LLM 暴露稳定 automation 函数面

4. `adapter core`
- 对内统一组织 automation 资源层的 list/get/create/update/delete

### 8.2 Key Rule

统一的是 adapter 内核，不是 LLM 工具接口。

也就是说：

- 对工程内部：automation 与 self-improve 共用 adapter 模式
- 对 LLM：仍然是 automation 领域动作，不是“通用 CRUD”

## 9. Adapter Model

### 9.1 Existing Core

当前已经有：

- `src/marten_runtime/data_access/specs.py`
- `src/marten_runtime/data_access/adapter.py`

第一阶段只支持 `lesson_candidate` 的：

- `list_items`
- `get_item`
- `delete_item`

### 9.2 Required Extension For Automation

为了纳入 automation，需要把 adapter 内核扩成“资源级适配器”，支持：

```python
list_items(entity: str, *, filters: dict, limit: int) -> list[dict]
get_item(entity: str, *, item_id: str) -> dict
create_item(entity: str, *, values: dict) -> dict
update_item(entity: str, *, item_id: str, values: dict) -> dict
delete_item(entity: str, *, item_id: str) -> dict
```

这里的 `entity` 仍然是白名单枚举，而不是裸表名。

### 9.3 Entity Spec For Automation

建议新增：

- `entity = "automation"`

定义：

- primary id: `automation_id`
- allowed list filters:
  - `delivery_channel`
  - `delivery_target`
  - `enabled`
  - `include_disabled`
  - `skill_id`
- creatable: true
- updatable: true
- deletable: true
- detail visible: true

同时明确两组字段：

- allowed create fields
  - `automation_id`
  - `name`
  - `app_id`
  - `agent_id`
  - `prompt_template`
  - `schedule_kind`
  - `schedule_expr`
  - `timezone`
  - `session_target`
  - `delivery_channel`
  - `delivery_target`
  - `skill_id`
  - `enabled`
  - `internal`

- allowed update fields
  - `name`
  - `prompt_template`
  - `schedule_kind`
  - `schedule_expr`
  - `timezone`
  - `session_target`
  - `delivery_channel`
  - `delivery_target`
  - `skill_id`
  - `enabled`

`app_id`、`agent_id`、`internal` 不应作为普通用户对话更新字段开放。

## 10. Why Not Expose Generic CRUD To LLM

如果直接让 LLM 使用统一 CRUD/MCP，比如：

- `create_entity(entity="automation", values=...)`
- `update_entity(entity="automation", where=...)`

会出现几个问题：

1. prompt 会开始依赖内核协议而不是领域能力
2. 任何新字段都会变成 prompt surface
3. LLM 可能越过 skill 约束，试图修改不该改的字段
4. 很容易下一步就把 scheduler 内部状态也加进来

因此，这里仍然坚持：

- 对内可统一 CRUD 语义
- 对外必须保留 automation 领域工具名

## 11. Tool Surface

### 11.1 Approved Domain Tools For This Phase

本阶段对 LLM 暴露的 automation 工具固定为：

- `list_automations`
- `get_automation_detail`  <- 新增
- `register_automation`
- `update_automation`
- `delete_automation`
- `pause_automation`
- `resume_automation`

### 11.2 Create Naming Decision

本阶段决策已经固定：

- 不新增 LLM 可见的 `create_automation`
- 继续保留 `register_automation` 作为唯一用户侧 create 工具
- 工程内部 adapter 可以使用 create 语义，但这只是内核实现细节

原因：

- 当前用户和 skill 都已经围绕 `register_automation` 建立语义
- 本阶段目标是统一内核，不是切换用户工具协议
- 如果同时引入 `create_automation`，执行 agent 很容易扩大成一轮工具面重构

因此，后续实现不得自行引入面向 LLM 的 `create_automation`，除非有新的单独设计批准。

### 11.3 Pause / Resume Modeling

`pause_automation` 和 `resume_automation` 不单独进入 adapter 作为“特殊实体动作”，而是：

- tool 层仍保留 `pause_automation` / `resume_automation`
- tool 内部通过 adapter `update_item(..., values={"enabled": False/True})`

这样 LLM 看到的是窄领域动作，内核看到的是统一 update。

## 12. Detail Query

当前 automation 只有列表，没有显式 detail tool。

如果要把 automation 作为完整资源层纳入 adapter，必须补：

- `get_automation_detail`

理由：

- list 不应该无限扩大字段
- 详情查询是资源模型的基本能力
- 后续用户要“看这个任务具体配置”时，不应依赖列表里塞满所有字段

## 13. Resource Visibility Rules

### 13.1 Public Visibility

默认用户可见范围：

- `internal = false`

默认列表行为：

- 不返回 internal automation
- `include_disabled = false` 时只返回 enabled public jobs
- `include_disabled = true` 时返回 enabled + disabled public jobs

### 13.2 Mutation Safety

默认用户可做的 mutation：

- 更新 public automation
- 暂停 public automation
- 恢复 public automation
- 删除 public automation

默认不允许：

- 修改 internal automation
- 删除 internal automation
- 通过对话修改 scheduler 内部状态

如果未来需要内部 automation operator 能力，应该单独设计，不应偷渡到这次 adapter 方案里。

## 14. Register / Create Semantics

当前 `register_automation` 有一个 MVP 特性：

- 通过 `semantic_fingerprint` 做语义去重

这在 automation 领域仍然成立，不能因为进入 adapter 就丢掉。

因此 create 路径必须明确：

### 14.1 User-Facing Create

对于用户说“帮我加一个定时任务”，应继续保持：

- create 前走既有 registration normalization
- 通过 `semantic_fingerprint` 检查等价任务
- 命中等价任务时返回已有任务，而不是重复创建

### 14.2 Adapter Responsibility Boundary

adapter 不负责创造“语义去重策略”，但要允许 tool 层把规范化后的 create 委托给统一内核。

更具体地说：

- `register_automation` 工具继续负责：
  - payload 规范化
  - current-channel/current-target 解析
  - registration 等价语义

- adapter 负责：
  - 对 automation 资源做一致的 create/get/list/update/delete 访问

所以 create 路径是：

- `register_automation` tool
  -> registration normalization / dedupe
  -> adapter `create_item("automation", ...)`

而不是让 adapter 自己理解所有注册语义。

## 15. Store Changes

为避免 adapter 层继续绕回各工具的私有逻辑，`AutomationStore` / `SQLiteAutomationStore` 应补足最小资源操作能力：

- `list_public(...)`
- `get(...)`
- `save(...)`
- `update(...)`
- `delete(...)`

如果 detail / filter 需要更窄的行为，可再补：

- `list_public_filtered(...)`
- 或 adapter 自己在 `list_public` 结果上做白名单过滤

本阶段不要求 store 层暴露通用 query API，更不要求支持任意字段过滤。

## 16. Skill Impact

`automation_management` skill 不需要重写成“数据库技能”。

它仍然应该保持现在的角色：

- 把用户对 automation 的自然语言意图路由到 automation 领域工具
- 强调先查再改
- 必要时做一次短澄清
- 结束于 CRUD 结果，不顺手执行任务内容

如果新增 `get_automation_detail`，skill 应补一条建议顺序：

- list candidates when the target task is ambiguous
- get detail when the target task is already identified

## 17. Interaction With Self-Improve Adapter

automation 纳入 adapter 后，系统会形成两类域：

- `lesson_candidate` / self-improve
- `automation`

这正是想要的结构：

- 内核统一
- 域边界明确
- 对 LLM 暴露的仍然是领域工具

此时 adapter 内核可以被视为一个“runtime control-plane resource adapter”，但不能把它包装成一个给 LLM 使用的 generic resource tool。

## 18. Migration Strategy

### 18.1 Preferred Migration Order

为了减少执行 agent 漂移，建议按下面顺序推进：

1. 先把 automation 读路径纳入 adapter
- `list_automations`
- `get_automation_detail`

2. 再把 mutation 路径纳入 adapter
- `update_automation`
- `delete_automation`
- `pause_automation`
- `resume_automation`

3. 最后收敛 create 路径
- `register_automation`
- 不引入新的 LLM-visible `create_automation`

### 18.2 Why This Order

- 读路径风险最低
- detail 工具补完后，资源模型更稳定
- mutation 可以在 detail/list 完整后更容易验证
- create 最复杂，因为它包含 registration normalization 与 dedupe

## 19. Verification Requirements

设计完成后，后续实现至少要验证：

### 19.1 Unit / Contract

- automation adapter spec 只允许白名单 entity
- `list_automations` 改走 adapter 后行为不回退
- `get_automation_detail` 能准确返回单个 public automation
- `pause_automation` / `resume_automation` 通过 adapter update 保持原行为
- `delete_automation` 不影响 internal automation
- `register_automation` 继续保持语义去重

### 19.2 Runtime Path

- 用户消息“现在有哪些定时任务”仍命中 `automation_management`
- 用户消息“看看这个任务详情”可走 `get_automation_detail`
- 用户消息“暂停这个任务”仍是 `list -> pause`
- 用户消息“删除这个任务”仍是 `list/detail -> delete`

### 19.3 Live Behavior

- 真实 Feishu automation CRUD 不回退
- `run diagnostics` 里的 `tool_calls` 仍能反映领域工具，而不是 generic CRUD
- 不因为 adapter 重构而出现任务内容误执行

## 20. Acceptance Criteria

本设计对应的实现阶段完成时，应满足：

1. automation 资源层已纳入统一 adapter 内核
2. self-improve 与 automation 共用一套内部 adapter 模式
3. LLM 仍然只看到领域工具，不看到 generic CRUD
4. scheduler / dispatch / delivery 内部状态没有被暴露进 agent 对话面
5. 现有 automation CRUD 行为与 self-improve query/delete 行为都不回退
6. 文档清楚写明“统一的是内核，不是 LLM 工具面”

## 21. Open Decisions

这些点需要在 implementation plan 中明确，不应留给执行 agent 自己发挥：

### 21.1 `register_automation` vs `create_automation`

当前结论已经固定，不再开放给执行 agent 决策：

- 对外只保留 `register_automation`
- 对内允许 adapter 使用 create 语义
- 本阶段禁止新增 LLM 可见的 `create_automation`

### 21.2 Filter Breadth

决定项：

- automation list 第一轮允许哪些 filters

当前建议只允许：

- `delivery_channel`
- `delivery_target`
- `enabled`
- `include_disabled`
- `skill_id`

不要在第一轮开放 name substring、任意 timezone 查询等扩展过滤。

### 21.3 Internal Automation Visibility

决定项：

- 是否允许 detail 查询 internal automation

当前建议：

- 不允许用户侧 list/detail 看到 internal automation
- 与现有 `/automations` operator surface 保持一致

## 22. Final Direction

最终方向不是“搞一个统一 DB CRUD 工具”，而是：

- 建立统一的 runtime control-plane resource adapter 内核
- 让 `self_improve`、`automation`、以及后续其他持久化资源模块都能复用这套内核
- 但始终坚持对 LLM 暴露的是领域函数，不是通用数据库协议

同时长期坚持另一条线：

- 所有定时任务、调度、触发、执行生命周期问题，继续优先落在 automation 系统层
- 不把这部分重新抽进 adapter
- 不把 adapter 发展成 scheduler / worker / workflow 平台

这条路线既满足“工程内统一”，也不偏离“agent + skill + tool 优先、工程只是 harness”的项目目标。
