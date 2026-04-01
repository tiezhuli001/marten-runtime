# Self-Improve Design

## 1. Goal

在不把 `marten-runtime` 扩成通用 memory / workflow 平台的前提下，加入一个窄范围、可审计、可回滚的 self-improve 机制，让默认主 agent 能从“重复失败 + 后续成功修复”中沉淀高价值长期约束。

第一阶段目标不是做 OTTClaw 式完整 agent memory，而是补一条受控旁路：

- 记录 runtime 中的高价值失败与修复证据
- 通过专用 skill 归纳候选 lessons
- 通过严格 gate 决定是否进入长期 prompt
- 以 runtime-managed `SYSTEM_LESSONS.md` 片段注入 system prompt

主链仍保持为：

- `channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel`

self-improve 是围绕主链的窄控制面，不是新的执行骨架。

## 2. Source-Of-Truth Constraints

- 保持项目中心仍然是 `LLM + agent + MCP + skill`
- 不把仓库扩成通用 memory / notes / persona 平台
- 不自动改写人工维护的 `AGENTS.md`
- lessons 的长期生效载体必须与人工 bootstrap 资产分层
- 只对 `default assistant agent` 生效，不按 Feishu channel 或 conversation 隔离
- lesson 进入长期 prompt 必须有高价值门槛，不能因为单次偶发错误污染 prompt
- self-improve 的触发与存储可以复用现有 SQLite 和 automation scheduler，但不要顺势扩成 worker-first 平台

## 3. Why Not OTTClaw-Style Full Memory Now

OTTClaw 的 self-improve 不只是“多几个 skill”，还包含：

- 用户级技能加载与自生成技能目录
- `notes` / `persona` / `user_kv` 三类持久 memory
- notes/persona 注入 system prompt
- self-improving skill usage / eviction 生命周期

这些能力在 OTTClaw 是一致的系统设计，但对当前 `marten-runtime` 来说过宽。当前仓库已经明确收敛在薄 runtime、清晰主链、窄 control plane。直接照搬会带来：

- 抽象面过早膨胀
- memory 写入边界不清
- prompt 污染风险扩大
- 自我提升从“受控经验沉淀”滑向“通用长期记忆”

结论：

- 第一阶段不做通用 `memory(target=notes)` API
- 只做 self-improve 所需的专用 evidence/candidate/lesson 存储
- 先建立可验证的经验沉淀回路，再决定未来是否需要推广成更通用的 memory 层

## 4. Scope

### 4.1 In Scope

- 为默认主 agent 增加 runtime-managed `SYSTEM_LESSONS.md`
- 记录结构化 failure / recovery evidence
- 新增一个 shared `self_improve` skill 负责候选 lesson 归纳
- 新增一个 lesson gate，控制候选 lesson 是否进入长期 prompt
- 复用现有 automation/scheduler 做定期归纳
- 增加 diagnostics / operator introspection，用于查看 self-improve 状态

### 4.2 Out Of Scope

- 通用 `notes` / `persona` / `user_kv` memory surface
- 用户自生成技能目录、自增长 skill eviction 策略
- 多 agent 共享经验池
- 跨 app / 跨 runtime 的全局 lesson 继承
- 每轮实时在线反思
- 自由改写整份 bootstrap prompt
- 自动修改 `AGENTS.md`
- 通用 workflow / worker / durable queue 演进

## 5. Intended Lifecycle

第一阶段的 self-improve 生命周期为：

1. runtime 记录高价值失败证据
2. 后续相似任务成功时，记录 recovery 证据
3. 实时阈值或定时任务触发一次归纳流程
4. `self_improve` skill 读取 evidence，产出 candidate lessons
5. `lesson gate` 判断 candidate 是否值得长期生效
6. 通过 gate 的 lesson 被写入 `SYSTEM_LESSONS.md`
7. bootstrap 在后续 turn 中注入 `SYSTEM_LESSONS.md`

简化数据流：

`runtime failure/recovery evidence -> self_improve skill -> lesson candidate -> lesson gate -> SYSTEM_LESSONS.md -> bootstrap prompt`

## 6. Runtime Scope And Identity

### 6.1 Why Not Channel Scope

lessons 不应按 Feishu channel 或 conversation 绑定，因为这些是交互入口边界，而不是 agent 行为边界。

### 6.2 Why Default Assistant Agent Scope

当前仓库的核心学习对象是默认主 assistant agent。它承载：

- 主要 bootstrap 指令
- 大部分工具调用决策
- MCP / skills 主链行为

因此第一阶段 lessons 作用域定为：

- `default assistant agent`

在当前实际部署上，这几乎等价于 runtime 主 agent 级别，但比“整个 runtime 全局共享”更准确，也给未来多 agent 演进保留了边界。

## 7. Persistence Model

第一阶段只增加专用 SQLite 存储，不暴露为通用 memory API。

### 7.1 `runtime_failure_events`

记录失败证据。

建议字段：

- `failure_id`
- `agent_id`
- `run_id`
- `trace_id`
- `session_id`
- `error_code`
- `error_stage`
- `tool_name`
- `provider_name`
- `summary`
- `fingerprint`
- `created_at`

用途：

- 支持按时间窗口、fingerprint、error_code 聚合
- 给 self-improve skill 提供稳定证据，而不是依赖零散日志文本

### 7.2 `runtime_recovery_events`

记录“同类失败后来如何被修好”。

建议字段：

- `recovery_id`
- `agent_id`
- `run_id`
- `trace_id`
- `related_failure_fingerprint`
- `recovery_kind`
- `fix_summary`
- `success_evidence`
- `created_at`

第一阶段不做复杂因果推断，只做弱关联：

- 同 agent
- 相近时间窗口
- 相同或兼容 fingerprint

### 7.3 `lesson_candidates`

记录 skill 归纳出的候选 lessons。

建议字段：

- `candidate_id`
- `agent_id`
- `source_fingerprints`
- `candidate_text`
- `rationale`
- `status` (`pending` / `accepted` / `rejected`)
- `score`
- `created_at`

### 7.4 `system_lessons`

记录最终已生效的长期 lessons。

建议字段：

- `lesson_id`
- `agent_id`
- `lesson_text`
- `source_fingerprints`
- `active`
- `created_at`
- `superseded_at`

## 8. Evidence Collection

### 8.1 Failure Evidence

第一阶段只记录高价值失败，不追求完整事件仓库。

优先覆盖：

- provider-specific failures
- `RUNTIME_LOOP_FAILED`
- `TOOL_LOOP_LIMIT_EXCEEDED`
- tool call rejected / tool contract failures

### 8.2 Recovery Evidence

recovery 证据是第一阶段质量控制的关键，因为只看失败会产生大量负面禁令，缺少“后来怎样修好”的可执行知识。

第一阶段 recovery 只要求：

- failure 之后出现最终 `final` 成功
- 同 agent
- 与先前 fingerprint 有足够近似
- 可提炼出明确修复动作摘要

### 8.3 Noise Discipline

不记录：

- 单纯的空白 turn 噪音
- 不可归因的偶发网络抖动文本
- 无法形成稳定规则的一次性环境问题

## 9. Triggering Model

第一阶段采用双触发，但仍保持很薄。

### 9.1 Threshold Trigger

当某类 failure fingerprint 在短窗口内连续出现达到阈值时，触发一次归纳。

默认建议：

- 阈值：`3`
- 时间窗口：最近 `24` 小时
- 防抖：同一 fingerprint 在同一窗口内只创建一次 pending 归纳触发，直到有新的 recovery 或窗口滚动后才允许再次触发

这里触发的是“归纳候选 lesson”，不是直接写入长期 prompt。

### 9.2 Scheduled Trigger

复用现有 automation/scheduler，定期执行 self-improve 归纳。

建议方式：

- 一个 narrow internal automation
- isolated turn
- 显式 `skill_id = self_improve`
- 默认不需要用户可见 final delivery

调度建议：

- 每 6 小时或每天一次

### 9.3 Why Scheduled-First

定时归纳为主、阈值触发为辅，原因是：

- 给 recovery 证据留时间补齐
- 避免每次失败都打扰主链
- 更容易控制 lesson 噪音

## 10. Skill Design

新增 shared skill：

- `skills/shared/self_improve/SKILL.md`

职责：

- 读取近期 failure / recovery evidence
- 归纳 candidate lessons
- 明确指出证据链与推荐理由
- 只生成候选，不直接写最终长期 prompt

skill 内容必须收敛：

- 只总结重复失败和后续修复
- 只产出稳定、可执行的规则
- 禁止输出一次性环境细节
- 禁止改写 `AGENTS.md` 或其他 bootstrap 资产

## 11. Lesson Gate

### 11.1 Why A Separate Gate

`SYSTEM_LESSONS.md` 非常宝贵，不能让 LLM 自由改写整份文件。因此必须把：

- candidate generation
- long-term acceptance

拆开。

### 11.2 Gate Shape

推荐采用双层 gate：

1. LLM gate
- 判断 candidate 是否高价值、可长期化

2. deterministic engineering checks
- 长度限制
- 去重
- 冲突检查
- source evidence 非空
- topic/fingerprint merge 规则

### 11.3 Acceptance Rules

候选 lesson 只有同时满足这些条件才允许 accepted：

- 基于重复 failure 模式，或基于 failure + 明确 recovery 证据
- 能转化为稳定规则，而不是历史偶发事实
- 不依赖临时环境值、路径、一次性用户状态
- 与现有 `AGENTS.md` / `BOOTSTRAP.md` / active lessons 不冲突
- 足够短，值得占用长期 prompt 空间

## 12. `SYSTEM_LESSONS.md` Management

### 12.1 File Role

第一阶段长期 lessons 存放在：

- `apps/example_assistant/SYSTEM_LESSONS.md`

这个文件是：

- runtime-managed
- 可审计
- 可回滚
- 与人工维护的 `AGENTS.md` 分层

### 12.2 Write Policy

第一阶段不允许 LLM 重写整份文件。只允许：

- append 新 lesson
- supersede 同 topic / fingerprint 的旧 lesson
- dedupe 合并近似 lesson

并保留 source evidence 元信息。

### 12.3 Active File Semantics

为避免 bootstrap 注入规则歧义，第一阶段明确采用下面的文件语义：

- `SYSTEM_LESSONS.md` 只保存当前 active lessons
- 已 supersede 或 rejected 的 lessons 不写回该文件，只保留在 SQLite 记录中
- bootstrap 对 `SYSTEM_LESSONS.md` 的判断规则是“文件存在且包含至少一条 active lesson”
- 因此 bootstrap 不需要再解析 active/inactive 标记；文件内容本身就是 active set 的导出结果

## 13. Bootstrap Integration

当前 bootstrap 已通过 `load_bootstrap_prompt(...)` 组装多个 app 资产。第一阶段只需扩展这一层：

- 如果 app 根目录存在 `SYSTEM_LESSONS.md`
- 且其中有 active lessons
- 则作为单独 section 拼接到 system prompt

建议 section 名：

- `Runtime Learned Lessons`

这样分层语义清晰：

- `AGENTS.md`: 人工维护的稳定原则
- `BOOTSTRAP.md`: 任务导向或运行约束
- `SYSTEM_LESSONS.md`: runtime 自动沉淀出的高价值经验

## 14. Internal Module Boundaries

推荐新增一个窄模块族，而不是把 self-improve 逻辑散落到 runtime/automation/skills 各处。

### 14.1 Evidence Store

职责：

- 持久化 failure / recovery / candidate / lesson
- 提供窄查询接口

### 14.2 Evidence Recorder

职责：

- runtime turn 结束时记录失败和修复证据

### 14.3 Self-Improve Skill Surface

职责：

- 让 LLM 在 skill 约束下归纳 candidate lessons

### 14.4 Lesson Gate / Lesson Writer

职责：

- 审核 candidate
- 受约束地更新 `SYSTEM_LESSONS.md`

实现边界：

- lesson gate 的 LLM 判断应使用一个窄输入、窄输出的结构化调用
- 不允许该判断流程拥有 MCP、builtin tools 或自由工具调用能力
- 输入只包括 candidate 文本、evidence 摘要、已有 active lessons 摘要、相关 bootstrap 规则摘要
- 输出必须是结构化 verdict，例如：
  - `accept: bool`
  - `reason: str`
  - `normalized_lesson_text: str`
  - `topic_key: str`
- 在 LLM verdict 之后，仍必须执行 deterministic checks，LLM 不能单独决定最终写文件

### 14.5 Scheduled Summarizer

职责：

- 用 automation/scheduler 触发归纳

## 15. Diagnostics And Operator Visibility

第一阶段至少增加这些诊断面：

- 当前 active lesson 数
- 最新 candidate 状态
- 最新 self-improve run 状态
- 最近被接受或拒绝的 lesson 摘要

要求：

- 不暴露完整用户原始消息
- 不暴露 secrets
- 不把完整内部 prompt 文本直接暴露到 diagnostics

建议最小字段：

- `self_improve.enabled`
- `self_improve.agent_id`
- `self_improve.active_lessons_count`
- `self_improve.latest_candidate_status`
- `self_improve.latest_candidate_created_at`
- `self_improve.latest_lesson_created_at`
- `self_improve.latest_accepted_lesson_summary`
- `self_improve.latest_rejected_lesson_summary`

## 16. Risks And Trade-Offs

### 16.1 Accepted

- lesson 归纳仍然带有 LLM 判断噪音
- recovery 关联是弱关联，不保证完美因果
- `SYSTEM_LESSONS.md` 仍可能出现需要人工清理的低质量条目

### 16.2 Mitigated

- 通过 candidate 层和 gate 降低 prompt 污染风险
- 通过单独文件分层，避免自动污染 `AGENTS.md`
- 通过 agent-scope 控制误伤范围

### 16.3 Avoided

- 通用 memory 平台
- 自增长 skill 平台
- worker-first 自我学习系统
- 高频自动重写 bootstrap

## 17. Verification Strategy

第一阶段完成后至少要验证：

- runtime 失败会落入 evidence store
- 后续成功 turn 能产出 recovery evidence
- self-improve automation 能读取 evidence 并生成 candidates
- gate 只让高价值 candidate 进入 active lessons
- `SYSTEM_LESSONS.md` 被 bootstrap 注入但不替代 `AGENTS.md`
- diagnostics 能反映 self-improve 当前状态
- 没有把 runtime 扩成新的 memory/workflow 平台

## 18. Outcome

第一阶段完成后，`marten-runtime` 将具备一个窄范围、可验证、可持续演进的 self-improve 回路：

- 主链不变
- lessons 可审计
- prompt 注入受控
- 学习来源以“失败 + 修复”证据为核心
- 不偏离 `harness-thin, policy-hard, workflow-light`
