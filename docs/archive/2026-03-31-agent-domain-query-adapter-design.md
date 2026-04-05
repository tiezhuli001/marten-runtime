# Agent Domain Query Adapter Design

## 1. Goal

在不把 `marten-runtime` 扩成通用数据库 agent、通用 memory 平台、或工程化后台系统的前提下，增加一条面向主 agent 的“领域查询与窄管理”能力，让用户可以通过自然对话查询 runtime 中已经持久化的控制面信息。第一执行阶段只落在 self-improve 域，典型对象包括：

- self-improve 候选规则
- active lessons
- self-improve 摘要

第一阶段目标不是让 LLM 直接理解表结构并自由做 CRUD，而是建立一层薄的 domain adapter：

- 用户继续走 `LLM + agent + skill + tool`
- tool 对 LLM 暴露的是领域函数
- 底层复用统一 adapter 内核，减少每个模块重复写 SQLite/store 访问逻辑

主链仍保持为：

- `channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel`

这里新增的只是主链上的一个更清晰的 control-plane tool 面，不是新的执行骨架。

## 2. Source-Of-Truth Constraints

- 保持 `LLM + agent + skill + MCP` 优先，工程只是 harness。
- 不把项目扩成通用 DB admin / generic SQL agent。
- 不向 LLM 暴露表名、自由 SQL、通用 CRUD 协议。
- skill 负责领域意图路由，不负责拼数据库细节。
- 对 LLM 暴露的能力必须是领域对象操作，不是表操作。
- 统一 adapter 内核可以复用，但它应位于 tool 背后，不应成为 LLM 直接接口。
- 第一阶段只允许删除 `lesson_candidates`，不允许对 `system_lessons` 做删除。
- 不引入新的 worker-first 架构、调度骨架、或宽泛 memory 抽象。

## 3. Why Not Expose Generic CRUD Or SQL

如果让主 agent 直接使用统一 CRUD/MCP，传入表名、主键、过滤条件，会带来这些问题：

- schema 漂移会直接传导到 prompt 和 skill
- LLM 会开始依赖“表知识”，而不是“领域知识”
- 写权限边界会迅速变宽
- 新模块接入虽快，但系统语义会从 agent runtime 滑向 DB operator
- 这和当前项目“薄 runtime、清晰主链、窄 control plane”的方向冲突

因此本设计明确区分两层：

1. 对内：统一 adapter 内核
2. 对外：领域函数 tool 面

## 4. Intended User Experience

用户应当能够直接通过对话查询控制面信息，例如：

- “最近有哪些 self-improve 候选规则？”
- “把这个不合理的候选规则删掉”
- “看看当前生效的 lessons”

预期行为：

1. 主 agent 识别意图属于 `self_improve` 管理域
2. 命中对应 skill
3. skill 指导 LLM 使用合适的领域 tool
4. tool 返回结构化结果
5. LLM 负责把结果组织成自然语言回复

用户不需要知道：

- 数据库路径
- 表名
- 主键结构
- SQL 条件语法

## 5. Scope

### 5.1 In Scope

- 为主 agent 增加统一的领域查询能力入口
- 在仓库内新增一个统一 data adapter 内核
- 在 self-improve 域新增候选规则查询和删除能力
- 在 self-improve 域新增摘要型查询能力
- 让 skill 按领域路由到 self-improve 管理能力
- 保持现有 automation 管理路径原样可用，但不纳入第一执行阶段的 adapter 改造

### 5.2 Out Of Scope

- 通用 SQL 查询
- 面向 LLM 的裸表 CRUD
- active lesson 删除
- 通用 memory(target=...) 平台
- 任意跨域 join 查询
- 面向用户暴露“数据库”概念

## 6. Domain Model

第一阶段执行范围只落在 `self_improve` 域。`automation` 在这里仅作为后续可复用的参考领域，不属于本次 adapter 实现范围。

### 6.1 Automation Domain

领域对象：

- automation job

对话意图：

- 查看当前任务
- 查看任务详情
- 修改 / 暂停 / 恢复 / 删除任务

已有工具：

- `list_automations`
- `update_automation`
- `pause_automation`
- `resume_automation`
- `delete_automation`

这一领域在第一阶段不做 adapter 改造，只要求与新方案共存且不被破坏。

### 6.2 Self-Improve Domain

领域对象：

- lesson candidate
- active lesson
- evidence summary

第一阶段目标能力：

- 查看候选规则列表
- 查看单条候选规则详情
- 删除候选规则
- 查看当前 active lessons
- 查看 self-improve 摘要

## 7. Architecture

### 7.1 Layered Shape

采用四层结构：

1. `agent + selector`
- 判断用户请求是否属于 self-improve 管理域

2. `skill`
- 给 LLM 领域语义、操作边界、推荐 tool 顺序

3. `domain builtin tools`
- 暴露给 LLM 的稳定函数面

4. `adapter core`
- 对内统一组织 store 查询和窄删除能力

### 7.2 Adapter Core Responsibility

adapter 内核负责：

- 定义受支持的领域实体
- 定义该实体的主键、允许过滤项、允许返回字段
- 把通用 list/get/delete 语义映射到对应 store
- 为 tool 层提供统一但非数据库化的调用接口

它不负责：

- 对外暴露“表名”
- 生成 SQL
- 允许任意字段更新

### 7.3 Domain Tool Responsibility

对 LLM 暴露的是领域函数，例如：

- `list_lesson_candidates`
- `get_lesson_candidate_detail`
- `delete_lesson_candidate`
- `get_self_improve_summary`

而不是：

- `query_table`
- `delete_row`
- `update_entity`

## 8. Skill Routing

### 8.1 Automation Skill

保留现有 `automation_management` skill，继续负责：

- automation 相关查询
- automation 相关变更

这个 skill 在本设计中只是共存背景，不是第一阶段要改造的目标。

### 8.2 New Self-Improve Management Skill

建议新增一个窄 skill，例如：

- `self_improve_management`

职责：

- 识别“候选规则 / 自我提升 / lessons / 经验规则”等用户话术
- 指导 LLM 优先使用 self-improve 域工具
- 明确说明：
  - 可以查 candidate
  - 可以删除 candidate
  - 不允许删除 active lesson
  - 不要暴露数据库或表名给用户

## 9. Tool Surface

### 9.1 Self-Improve Tools

第一阶段新增：

- `list_lesson_candidates`
  - 支持按 `status`
  - 支持 `limit`

- `get_lesson_candidate_detail`
  - 按 `candidate_id` 查询

- `delete_lesson_candidate`
  - 按 `candidate_id` 删除
  - 仅允许删除 candidate 记录

- `get_self_improve_summary`
  - 返回 candidate 数量、active lesson 数量、最近 accepted/rejected 摘要

保留已有：

- `list_self_improve_evidence`
- `list_system_lessons`
- `save_lesson_candidate`

### 9.2 Automation Tools

保留现有 automation 管理工具，不在第一阶段迁移到 adapter。

如果 self-improve 路径验证稳定，可在下一阶段再决定是否把 automation 读路径逐步切到同一 adapter 内核。

## 10. Data Adapter Interface

建议新增一个窄接口，不直接暴露数据库含义：

```python
list_items(entity: str, *, filters: dict, limit: int) -> list[dict]
get_item(entity: str, *, item_id: str) -> dict
delete_item(entity: str, *, item_id: str) -> dict
```

其中：

- `entity` 仅允许第一阶段白名单值，例如 `lesson_candidate`
- `filters` 仅允许 entity spec 中声明的字段
- delete 只对白名单 entity 开放

这个接口只供 builtin tool 调用，不直接给 LLM。

## 11. Safety Rules

### 11.1 Candidate Delete Only

第一阶段只允许删除：

- `lesson_candidates`

不允许删除：

- `system_lessons`
- failure / recovery evidence
- automation dispatch history

### 11.2 No Freeform Query Language

不提供：

- SQL
- where-expression DSL
- 任意字段更新协议

### 11.3 No Table Leakage

skill 和 tool 回复中不强调：

- SQLite
- 表名
- schema 内部结构

这些信息属于 harness 内部。

## 12. Why This Still Preserves Agentness

这个方案不会把系统降级成“工程化后台”。

agent 的职责仍然是：

- 识别用户意图
- 命中正确 skill
- 判断是否需要调用工具
- 组合多步查询
- 解释结果
- 处理歧义

工程层只是：

- 稳定提供结构化能力
- 限制破坏性操作边界
- 复用通用适配逻辑

因此它仍然符合：

- `LLM + agent + skill + tool` 主导
- harness 负责安全和清晰边界

## 13. File And Module Boundaries

建议新增：

- `src/marten_runtime/data_access/adapter.py`
  - 统一 adapter 实现

- `src/marten_runtime/data_access/specs.py`
  - 第一阶段只包含 self-improve candidate 相关 entity 白名单与字段规则

- `src/marten_runtime/tools/builtins/list_lesson_candidates_tool.py`
- `src/marten_runtime/tools/builtins/get_lesson_candidate_detail_tool.py`
- `src/marten_runtime/tools/builtins/delete_lesson_candidate_tool.py`
- `src/marten_runtime/tools/builtins/get_self_improve_summary_tool.py`

- `skills/shared/self_improve_management/SKILL.md`

主要修改：

- `src/marten_runtime/self_improve/sqlite_store.py`
- `src/marten_runtime/interfaces/http/bootstrap.py`
- `tests/test_tools.py`
- `tests/test_skills.py`
- `tests/test_contract_compatibility.py`

## 14. Diagnostics And Operator Visibility

第一阶段无需增加宽泛 diagnostics 面，但至少应确保：

- 现有 runtime diagnostics 继续暴露 self-improve 摘要
- tool 结果能让用户通过对话拿到：
  - candidate count
  - candidate status
  - 最近 active lessons

如需新增 diagnostics，仅增加高层摘要，不暴露底层 adapter 内部实现细节。

## 15. Rollout Strategy

第一阶段按最小变更推进：

1. 先补 self-improve 域读取与 candidate 删除能力
2. 保持 automation 现有 CRUD 不动
3. 用统一 adapter 内核承接 self-improve 域读/删
4. 验证模型是否能稳定通过 skill 命中正确领域工具
5. 只有在这个路径稳定后，才考虑把更多控制面对象迁到同一 adapter

## 16. Success Criteria

满足以下条件视为完成：

- 用户能通过自然对话查询 self-improve 候选规则
- 用户能通过自然对话删除指定 candidate
- 用户能通过自然对话查询 active lessons
- 主 agent 不需要理解表名或 SQL
- 工程内部已有统一 adapter 内核可供后续领域复用
- 全量测试与一轮 live smoke 通过
