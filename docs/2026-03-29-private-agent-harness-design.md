# Private Agent Harness First-Wave Design

## Decision

需要先实现，但不需要把所有 openclaw 式能力一次做满。

对于 `marten-runtime` 当前目标:

- 对接 channel
- 支持多 agent
- 支持用户自定义 MCPs
- 支持用户自定义 skills
- 最终承载“我自己的私有 agent 和 skills”

下面 5 个 harness 需要进入当前 program，但要分成两个里程碑，而不是一起并行堆工程。

里程碑 A: intelligence spine first

1. gateway binding + multi-agent routing
2. live context rehydration
3. skills first-class runtime integration
4. provider transport resilience

里程碑 B: runtime hardening

5. per-conversation serialization
6. durable session persistence

更新:

- `per-conversation serialization` 已在 2026-03-30 的 conversation lanes hardening 中以单进程 FIFO 形式落地
- `durable session persistence` 仍然是后续阶段能力

不建议当前先做的能力:

- durable delivery queue
- heartbeat / cron / proactive runs
- hybrid memory promotion
- full async worker backbone

这些能力重要，但不是当前目标的前置条件。

## Execution Principle

实现顺序必须服从这个原则:

- 先打通 `channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel`
- 再补 durability / concurrency / persistence

如果某个实现步骤不能直接改善这条主链，它就不应该排在前面。

## Why These Five First

### 1. Session persistence + rehydration

没有持久化 session 和回灌上下文，agent 无法形成稳定人格、稳定任务连续性，也无法跨进程恢复。

### 2. Gateway binding + multi-agent routing

没有绑定层，`multi-agent` 只是配置存在，不是可托管能力。channel 来的消息无法稳定落到正确 agent。

### 3. Skills first-class

如果 skill 只是文件存在、但 LLM 启动时不知道、命中时也不注入正文，那它不是运行时能力，只是静态资产。

### 4. Per-conversation serialization

没有串行保护，同一个 chat/session 连续两条消息或 Feishu 重入事件会在逻辑上并发踩踏 session state、tool loop、delivery。

### 5. Provider resilience

真实链路里已经出现过 MiniMax timeout。没有最基础 retry/backoff/normalized errors，系统会在 live channel 上显得不稳定。

## Non-Goals For This Wave

- 不做 planner/swarm/sub-agent 编排
- 不做 durable channel outbox
- 不做 cron/heartbeat 主动任务系统
- 不做混合长期记忆策略
- 不做多节点分布式队列

## Alternatives Considered

### Approach A: 逐点热修

做法:

- 在现有文件上局部补 if/else
- 先把 skills 注进 prompt
- 再给 router 加几条规则

优点:

- 改动快

缺点:

- 会把 bootstrap、runtime loop、LLM request 进一步耦合
- 很快变成难以维护的条件分支网

结论:

- 不推荐

### Approach B: 引入一个明确的“runtime context assembly layer”

做法:

- 保持 harness-thin
- 在 intake/router 和 llm client 之间增加一个 context assembly 层
- 统一拼装:
  - session history
  - compacted context
  - active skill context
  - tool snapshot
  - system/bootstrap prompt

优点:

- 与当前 repo 方向一致
- 便于把 skills、session、routing 变成一等公民
- 后续可以平滑接 memory、heartbeat、async worker

缺点:

- 第一波需要补几个新的 focused modules

结论:

- **推荐**

### Approach C: 直接改成 queue-first / worker-first

做法:

- 所有 interactive traffic 全进 queue
- worker 负责 session、routing、delivery

优点:

- 长期形态更统一

缺点:

- 对当前 repo 改动过大
- 会阻塞正在工作的 live chain
- 把 MVP 需求和演进需求混在一起

结论:

- 当前不推荐

## Recommended Architecture

### 1. Runtime Assembly

新增一个显式的 runtime context assembly 层，职责是把“会被 LLM 看到的运行时上下文”集中构造，而不是分散在 bootstrap 和 llm client。

建议新增:

- `src/marten_runtime/runtime/context.py`

负责输出一个结构化对象，例如:

- `system_prompt`
- `conversation_messages`
- `working_context`
- `skill_snapshot`
- `activated_skill_ids`
- `activated_skill_bodies`
- `tool_snapshot`

`RuntimeLoop` 不直接拼 prompt，只请求 context assembler 产出一份当前 turn 的上下文，再交给 `LLMClient`。

### 2. Session Store Strategy

当前 `SessionStore` 不应该在第一批就直接做重型 cutover。正确做法是先抽象接口，再保留两层实现:

- in-memory adapter: 继续用于快速测试
- sqlite-backed adapter: 在 intelligence spine 打通后再接入真实 runtime

建议新增:

- `src/marten_runtime/session/store_protocol.py`
- `src/marten_runtime/session/in_memory_store.py`
- `src/marten_runtime/session/sqlite_store.py`
- `src/marten_runtime/session/history.py`

关键设计:

- session 主键仍然是 `session_id`
- `conversation_id` 维持唯一索引
- message history 单独表存储
- `active_agent_id`、`last_run_id`、`context_snapshot_id`、`updated_at` 可查询
- bootstrap/config snapshot ids 仍然冻结在 session 上

SQLite-first 即可，不需要现在做多节点。

执行要求:

- 先完成 `rehydration on live path`
- 再做 `sqlite persistence cutover`
- 不允许编码 agent 先从数据库 schema 开始

### 3. Context Rehydration

普通 turn 的 LLM request 需要按层回灌:

1. bootstrap/system prompt
2. always-on skills
3. compacted working context
4. recent session messages
5. current user message
6. tool history

建议新增:

- `src/marten_runtime/session/replay.py`

规则:

- 默认回放最近 `N` 条消息
- 超过 budget 时先压缩，再回放摘要 + 最近消息
- 继续复用已有 `compact_context(...)` / `rehydrate_context(...)`

### 4. Gateway Binding + Multi-Agent Routing

当前 router 只会在 `requested_agent_id / active_agent_id / default_agent` 之间做 fallback。第一波需要引入绑定层。

建议新增:

- `config/bindings.toml`
- `src/marten_runtime/config/bindings_loader.py`
- `src/marten_runtime/agents/bindings.py`

绑定规则建议支持:

- `channel_id`
- `chat_id` / `conversation_id`
- `user_id`
- optional `mention_required`
- target `agent_id`

匹配优先级:

1. explicit requested agent
2. exact `(channel_id, conversation_id)`
3. exact `(channel_id, user_id)`
4. channel default agent
5. session active agent
6. app default agent

这样可以支持:

- 某个 Feishu 私聊固定绑定某个私有 agent
- 某个群只绑定某个 agent
- HTTP channel 用默认 agent

### 5. Skills First-Class Integration

第一波需要把 skill 分成两层:

- startup-visible skill heads
- turn-level activated skill bodies

建议新增:

- `src/marten_runtime/skills/service.py`
- `src/marten_runtime/skills/selector.py`

职责:

- runtime 启动时 discover + filter + snapshot
- always-on skill 直接注入 system/runtime context
- 非 always-on skill 把 head 列表给 LLM
- 当前 turn 根据 message / channel / agent / explicit mention 选择激活 skill

第一波 activation 策略不要过度复杂，建议:

- explicit mention 命中
- exact skill id / skill name 命中
- tag / keyword 命中
- always-on 直接启用

先不做 embedding / semantic retrieval。

### 6. Per-Conversation Serialization

第一波不要直接上完整 queue-first，先加轻量 lane guard。

建议新增:

- `src/marten_runtime/runtime/lanes.py`

职责:

- 按 `channel_id + conversation_id` 生成 lane key
- 同一 lane 同时只允许一个 active run
- 后来的请求:
  - 可以阻塞等待短时间
  - 或直接返回可观测错误码 `CONVERSATION_BUSY`

建议默认:

- HTTP: fail-fast 返回 `409`
- Feishu: 记录日志并丢弃到可诊断错误事件，避免消息乱序

### 7. Provider Resilience

建议把 provider HTTP transport 包一层 resilience policy，而不是把 retry 写死在 channel 或 app 层。

建议新增:

- `src/marten_runtime/runtime/provider_retry.py`

职责:

- classify retryable errors
- timeout retry
- exponential backoff
- normalized error codes

第一波只做:

- timeout
- transient network errors
- 5xx

不要做:

- multi-provider failover
- provider hedging

## File Plan

### Create

- `config/bindings.toml`
- `src/marten_runtime/config/bindings_loader.py`
- `src/marten_runtime/agents/bindings.py`
- `src/marten_runtime/runtime/context.py`
- `src/marten_runtime/runtime/lanes.py`
- `src/marten_runtime/runtime/provider_retry.py`
- `src/marten_runtime/skills/service.py`
- `src/marten_runtime/skills/selector.py`
- `src/marten_runtime/session/store_protocol.py`
- `src/marten_runtime/session/in_memory_store.py`
- `src/marten_runtime/session/sqlite_store.py`
- `src/marten_runtime/session/replay.py`
- `tests/test_bindings.py`
- `tests/test_session_sqlite.py`
- `tests/test_runtime_context.py`
- `tests/test_runtime_lanes.py`
- `tests/test_provider_retry.py`

### Modify

- `src/marten_runtime/interfaces/http/bootstrap.py`
- `src/marten_runtime/interfaces/http/app.py`
- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/llm_client.py`
- `src/marten_runtime/agents/router.py`
- `src/marten_runtime/session/store.py`
- `src/marten_runtime/skills/filter.py`
- `tests/test_router.py`
- `tests/test_session.py`
- `tests/test_skills.py`
- `tests/test_runtime_loop.py`
- `tests/test_feishu.py`

## Rollout Order

### Milestone A: make the intelligence spine real

1. binding + routing
2. context assembly + rehydration
3. skills first-class
4. provider resilience

达成标志:

- LLM 请求能看到绑定后的 agent 身份
- LLM 请求能看到 session replay / working context
- LLM 请求能看到 skill heads 和 activated skill bodies
- MCP 主链不回退
- provider timeout 不再随机打断核心链路

### Milestone B: make the runtime safe and durable

1. per-conversation serialization
2. durable session store

更新:

- `per-conversation serialization` 已通过 conversation lanes Phase 1 落地
- 当前剩余未完成的 Milestone B 核心项是 durable session store

说明:

- durable session store 在架构上很重要
- 但实现上不能抢在 intelligence spine 前面
- 先抽 store interface，再落 sqlite adapter，避免“为了数据库而数据库”

## Expected Outcomes

完成第一波后，系统应满足:

- 同一个 Feishu 私聊或群可以稳定绑定到指定 agent
- runtime 启动后 LLM 知道可用 skills 摘要
- 命中的 skill 正文会被装载到当前 turn
- session 历史和 compacted context 会进入普通 LLM turn
- 同一 conversation 不会出现并发 run 踩踏
- 上游 provider 短暂 timeout 不再直接把最终用户请求打成随机失败

## Acceptance Criteria

### Functional

- `bindings.toml` 能控制特定 channel/user/chat 的 agent 绑定
- `RuntimeLoop` 能接收 context assembler 输出的 session history 和 skill context
- `LLMRequest` 能承载 session replay 和 active skills
- 同一 conversation 并发请求时，第二个请求得到稳定、可预期结果
- provider timeout 触发 retry 后，请求仍能成功完成或返回规范化错误

### Non-Functional

- HTTP 入口仍保持 thin
- `mcps.json` 仍然是连接层
- `config/*.toml` 仍然是治理层
- live Feishu chain 不因这些改造而丢失已修复的 card / dedupe / hidden progress 行为

## Test Expectations

预期新增或更新测试覆盖:

- router/binding precedence tests
- sqlite session persistence and reload tests
- runtime context assembly tests
- skill startup snapshot and activation tests
- concurrent conversation guard tests
- retryable provider transport tests
- end-to-end HTTP -> LLM -> MCP path regression tests
- Feishu inbound routing + delivery regression tests

预期结果:

- targeted tests 全绿
- 全量 `PYTHONPATH=src python -m unittest -v` 仍然通过
- live diagnostics 仍能显示 MCP discovery 和 Feishu websocket connected

## Recommendation

建议把这组能力作为**同一个 harness program**来做，但严格分成两个里程碑，不要并行乱改。

推荐顺序:

1. bindings
2. context assembly + rehydration
3. skills integration
4. provider resilience
5. serialization
6. sqlite session backend cutover
