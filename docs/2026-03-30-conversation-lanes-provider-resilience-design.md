# Conversation Lanes And Provider Resilience Design

## 1. Goal

在不把 `marten-runtime` 改造成 durable worker 平台的前提下，补齐当前 live 链路的两个稳定性缺口：

- 同一会话消息可能乱序、交错、并发踩踏
- LLM/provider 偶发 timeout 或短暂上游故障时，当前恢复能力不够强

本设计采用两阶段推进，但第一阶段必须先落地并保持主链可验证。第一阶段要把 interactive entrypoints 改成会话级串行排队，但不扩到 durable worker/backbone：

- Phase 1:
  - per-conversation in-memory mailbox / lane queueing
  - stronger provider retry + normalized diagnostics
  - no durable queue / worker cutover
- Phase 2:
  - durable queue / worker backbone
  - recoverable jobs and cross-process coordination

## 2. Source-Of-Truth Constraints

- 保持主链为 `channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel`
- runtime 仍然是 thin harness，不引入 workflow-platform 式大编排
- 不用 GitHub-specific 或 Feishu-specific 业务分支来掩盖并发问题
- 允许 narrow runtime-local control plane，例如 lane manager、provider retry policy、diagnostics
- 第一阶段优先保证 interactive chain 通，且对现有 live path 的扰动最小

## 3. Phase 1 Non-Goals

第一阶段明确不做：

- durable queue
- worker polling / worker pool
- automation scheduler 重构
- deferred delivery replay
- session persistence 重构
- 多进程 / 多节点互斥

## 4. Current Reality

当前 repo 已经有这些基础：

- Feishu websocket 单实例 lock，避免同一 app 起多个 websocket 消费进程
- Feishu inbound receipt dedupe 和 semantic short-window dedupe
- runtime loop 已有基础 provider retry wrapper
- delivery 已有 retry / dead-letter
- `/diagnostics/queue` 仍是占位返回，不反映真实会话执行状态

当前缺口也很明确：

- websocket 当前“逐条 await”只在一个入口上形成近似串行，不能作为显式会话串行语义
- HTTP `/messages`、Feishu inbound 对同一会话没有统一 mailbox 约束
- provider retry 只覆盖基础 transport/timeout，没有明确分类 `429/502/503/504`
- provider failures 在 run diagnostics 里的可观测性不够细，外层大多只看到 `RUNTIME_LOOP_FAILED`

## 5. Why Not Durable Queue-First Now

直接改成 durable queue / worker-first 会同时改变：

- HTTP / Feishu interactive contract
- runtime turn 执行时机
- final delivery 语义
- 诊断和运维面

这会把“先稳住当前 live chain”和“长期平台演进”绑死在一轮改动里，风险过高，也与仓库现阶段“thin harness, skill-first”原则不一致。

结论：

- Phase 1 要在 interactive entrypoints 引入 queueing 语义
- 但 Phase 1 仍然不做 durable queue / worker cutover
- Phase 2 再把这套 lane queue 语义升级为可恢复的 durable queue / worker

## 6. Recommended Architecture

### 6.1 Phase 1: In-Memory Conversation Lanes

新增一个 focused 模块：

- `src/marten_runtime/runtime/lanes.py`

职责不是 durable workflow 平台，而是“会话级 in-memory mailbox / queue 管理器”。

建议模型保持最小：

- `LaneKey`
  - `channel_id`
  - `conversation_id`
- `LaneItem`
  - `enqueue_id`
  - `lane_key`
  - `message_id`
  - `trace_id`
  - `enqueued_at`
- `ConversationLaneManager`
  - `enqueue(...)`
  - `mark_started(...)`
  - `mark_finished(...)`
  - `stats()`

关键原则：

- 同一个 `LaneKey` 同时最多允许一个 active run，但允许后续请求排队
- 不同 lane 继续并发
- lane 生命周期和一个 runtime turn 绑定，不和 websocket frame 生命周期绑定
- queue 是“单进程内存态”，第一阶段接受这一限制

### 6.2 Lane Key Choice

第一阶段 lane key 推荐为最小会话边界：

- `channel_id + conversation_id`

原因：

- `conversation_id` 是最核心的会话边界
- `channel_id` 防止不同 channel 复用同名 conversation
- 当前目标只是防止同一对话的 interactive turn 交错
- `app_id` / `agent_id` 维度属于未来多 app / 多 bot 演进问题，Phase 1 不需要先做复杂化

### 6.3 Entry Behavior

#### HTTP `/messages`

HTTP 是最适合定义明确 contract 的入口。

建议行为：

- 请求进入同 lane queue
- 当前无 active run 时立刻开始执行
- 当前已有 active run 时排队等待，前一个 turn 完成后自动执行

建议响应：

- 对调用方仍返回正常 `200`
- 不把 overlap 暴露成错误
- 同 lane 内响应顺序与入队顺序一致
- 如需可观测性，队列状态通过 diagnostics 暴露，而不是通过 409 合约暴露

#### Feishu websocket inbound

Feishu 同样不适合把 overlap 变成 visible 错误消息。

建议行为：

- event 进入同 lane queue
- 同 chat 内按顺序串行执行
- 每个 event 都应最终产出自己的正常 turn 结果
- 不向频道发送 busy fallback reply

这和 OTTClaw 前端 busy 时先排队、前一个 turn 完成后继续发送的 UX 方向一致，只是这里要落在 runtime harness 层。

### 6.4 Runtime Integration Point

lane 应尽量包在入口外层，而不是嵌进 `RuntimeLoop` 内部。

原因：

- `RuntimeLoop` 是纯 turn execution unit，更适合关注 LLM/tool loop
- lane 是“谁有权开始 turn”的 admission control
- 入口层最清楚 `channel_id/conversation_id/message_id`

因此推荐改动点：

- `src/marten_runtime/interfaces/http/bootstrap.py`
- `src/marten_runtime/interfaces/http/app.py`
- `src/marten_runtime/channels/feishu/service.py`

第一阶段只接入 interactive entrypoints：

- HTTP `/messages`
- Feishu inbound interactive turns

automation scheduler 和 final delivery 保持现状，不在这一阶段改造。

## 7. Provider Resilience Design

### 7.1 Current State

当前 `OpenAIChatLLMClient.complete()` 已经使用 `with_retry(...)`，这是正确基础，但还缺：

- retryable HTTP 状态分类不完整
- backoff 没有 jitter
- run diagnostics 对 provider attempts / normalized error 不够透明
- runtime loop 将过多 provider failure 折叠为通用失败

### 7.2 Retry Policy

第一阶段建议把 provider errors 分四类：

1. retryable transport
- `TimeoutError`
- `OSError`
- `provider_transport_error:*`

2. retryable upstream transient HTTP
- `429`
- `502`
- `503`
- `504`

3. fail-fast auth/config
- `401`
- `403`
- 缺 key、invalid base url、malformed request

4. fail-fast response/schema
- provider 返回结构不符合当前 parser 预期
- tool call arguments 结构异常但并非短暂网络错误

### 7.3 Backoff

第一阶段即可采用 bounded exponential backoff with jitter：

- attempts: 默认 `3`
- base: `0.25s`
- max: `2s`
- jitter: `0% - 20%`

目标不是吞掉所有 provider 问题，而是降低短暂 timeout / overload 对 live chain 的可见抖动。

### 7.4 Error Normalization

`ProviderTransportError` 继续保留，但需要补强：

- `error_code`
- `detail`
- `retryable`
- `attempt_count`
- `provider_name`
- `model_name`

`RuntimeLoop` 对 provider failure 的外层行为建议为：

- 对用户面仍维持稳定 fallback 文案，避免暴露实现细节
- 对 run history / diagnostics 保留具体 normalized error code

推荐错误码：

- `PROVIDER_TIMEOUT`
- `PROVIDER_TRANSPORT_ERROR`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_UPSTREAM_UNAVAILABLE`
- `PROVIDER_AUTH_ERROR`
- `PROVIDER_RESPONSE_INVALID`

外层 contract 仍可继续把最终 event_type 设为 `error`，但 `payload.code` 不应全部压成 `RUNTIME_LOOP_FAILED`。

## 8. Diagnostics

### 7.1 Replace Fake Queue Diagnostics

`/diagnostics/queue` 当前是占位值，Phase 1 应改成 lane diagnostics：

- `active_lane_count`
- `active_lanes`
- `queued_lane_count`
- `queued_items_total`
- `max_queue_depth`
- `last_enqueued_lane`

如果保留 endpoint 名称 `/diagnostics/queue` 以兼容现有 operator 路径，可以在返回体里明确 `mode = "conversation_lanes"`。

### 7.2 Runtime Diagnostics

`/diagnostics/runtime` 追加：

- `provider_retry_policy`
- `provider_last_error_code`
- `provider_last_error_detail`
- `provider_last_attempt_count`
- `lanes.summary`

要求：

- 不暴露密钥
- 不暴露完整 prompt / user text
- 可以暴露 run_id / trace_id / lane key

## 9. Phase 2 Target State

Phase 2 如有需要，再把 lane 语义升级成 durable queue / worker：

- inbound message 先持久化为 job
- worker 按 lane 领取并执行
- deferred sends 可恢复
- lane state 跨进程共享

Phase 2 新增能力：

- durable job table
- lease / heartbeat
- retry scheduling
- dead-letter for runtime jobs
- replay / requeue

但 Phase 2 不是 Phase 1 的前置条件。

## 10. Risks And Trade-Offs

### 10.1 Accepted In Phase 1

- lane 仅限单进程内存态，进程重启即丢
- 多实例部署下，lane 不提供跨实例互斥

### 10.2 Avoided In Phase 1

- 不引入新的 durable queue schema
- 不改写 scheduler 为 worker system
- 不把 runtime loop 拆成全异步 job orchestration

## 11. Verification Strategy

### Unit / contract

- same-lane overlap is queued and executed in FIFO order
- different lanes can proceed independently
- Feishu same-chat overlap is queued and does not create busy visible reply
- retryable provider failures succeed within policy
- non-retryable provider failures fail fast
- run history and diagnostics preserve normalized provider error codes

### Integration

- HTTP sequential and overlapping requests on same conversation
- Feishu duplicate / overlap repro on same chat

### Live smoke

- current service health still green
- same conversation overlap no longer creates two visible final replies
- transient provider timeout no longer immediately degrades into visible generic failure if retry can recover

## 12. Implementation Decision

执行顺序固定为：

1. Phase 1 design-compatible tests
2. in-memory conversation lanes
3. HTTP admission control
4. Feishu admission control
5. provider retry hardening
6. diagnostics sync
7. targeted verification
8. optional live smoke

只有在这条链路稳定后，才进入 Phase 2 durable queue 设计和实现。
