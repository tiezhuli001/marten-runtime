# Thin Multi-Provider OpenAI-Compat Design

Date: 2026-04-20  
Status: Draft for review  
Scope: design only; implementation stays for the next stage after design review

## Goal

为 `marten-runtime` 增加一个薄的多 provider 接入层，解决当前单一 `openai` transport 工厂的扩展瓶颈，同时保持 harness 边界清晰。

本设计的目标只有四个：

1. 支持 `openai`、`minimax`、`kimi` 三个 provider。
2. 保持密钥继续由 `.env` 承载，不把 secret 写进配置文件。
3. 把“provider 连接信息”和“model profile 选择”拆开，避免继续把 provider 差异硬塞进一个 client。
4. 在 provider 不可用、429/529、超时、空输出等情况下，允许以 profile 为单位做薄 failover。

本设计服务的主链仍然是：

`channel -> binding -> agent -> runtime loop -> llm client -> builtin tool / MCP / skill -> llm client -> channel`

## Design Outcome

这份设计完成后，`marten-runtime` 应具备以下明确结果：

1. `config/providers.toml` 成为 provider 连接配置入口。
2. `config/models.toml` 只描述 profile、模型名、上下文参数和可选 fallback profile。
3. runtime 能根据 `profile -> provider_ref -> adapter` 构造正确的 LLM client。
4. `openai`、`minimax`、`kimi` 三者都通过同一个 `openai_compat` adapter 接入。
5. provider 故障时 runtime 能按设计切换到 fallback profile，而不是靠人工改代码换 provider。
6. 诊断面能清楚说明本次请求用了哪个 profile、哪个 provider、是否发生 failover、为什么发生。

## Current Repository Baseline

当前仓库的 LLM 接入点已经有一个薄骨架，但它仍然是单 provider 形态。

### Existing strengths

1. `models.toml` 已经有 profile 概念。
2. `build_llm_client()` 已经是一个集中入口。
3. runtime、subagent、diagnostics 已经统一依赖 `model_profile`。
4. `OpenAIChatLLMClient` 已经拥有 retry、usage 归一化、tool call、Responses API 处理等主链能力。

### Current gaps

1. `ModelProfile` 当前把 provider 和连接参数混在一起。
2. `build_llm_client()` 当前写死 `provider == "openai"`。
3. `minimax` 只是伪装成 “openai + base_url” 的特殊 profile，不是明确的 provider。
4. 还没有 provider registry，无法在不改代码的前提下增加新的 OpenAI-compatible provider。
5. 还没有 profile 级 failover 机制，provider busy / timeout / empty output 时只能人工切换。

## Source-Of-Truth Constraints

以下约束是本设计的硬边界。

### 1. Harness Boundary

宿主只负责：

- provider 配置解析
- transport 组装
- provider 级重试与 failover
- usage 归一化
- 诊断记录

宿主不负责：

- 推断用户意图该用哪个工具
- 替模型决定调用 builtin / MCP / skill
- 通过 provider 选择替代 agent 决策

### 2. Thin Provider Boundary

当前阶段只做一个 API family adapter：

- `openai_compat`

不引入：

- OpenClaw 式 provider hook/plugin 平台
- LiteLLM 依赖
- 远程 provider marketplace
- 抽象过深的 capability framework

### 3. Secret Boundary

所有 secret 保持在 `.env`：

- `OPENAI_API_KEY`
- `MINIMAX_API_KEY`
- `KIMI_API_KEY`

`providers.toml` 只允许保存：

- `adapter`
- `base_url`
- `api_key_env`
- 可选非敏感 header / query 约定

### 4. Scope Boundary

当前阶段只支持：

- `openai`
- `minimax`
- `kimi`

当前阶段明确不做：

- `anthropic`
- `bedrock`
- `gemini`
- OAuth provider
- 流式 transport 重构
- 多 adapter 并行框架

### 5. Cleanup Boundary

当前阶段不保留原来的单 provider 历史代码作为长期兼容层。

明确约束：

- 新路径稳定后，原来的单 provider 旧实现直接删除
- 不保留“旧工厂 + 新工厂”双轨长期共存
- 不保留“旧 profile 字段 + 新 profile 字段”双写
- 不保留仅为迁移存在的 compat wrapper、compat helper、shim 层

仓库的 source of truth 必须始终只有一套当前实现。

### 6. Failover Boundary

failover 是 host 的运行时稳定性能力，不是语义 routing。

具体约束：

- failover 单位是 `profile`
- failover 触发原因必须是 transport / provider 级失败
- failover 不能改变 tool policy
- failover 不能引入“根据用户消息内容选择 provider”的逻辑
- failover 不能重新执行已经产生副作用的 tool 调用
- failover 必须有明确的触发阶段边界，不能在任意中间状态下盲目重放整轮请求

## Non-Goals

本设计明确不处理：

1. agent 级 prompt 改写
2. tool exposure 策略变化
3. session / memory / compaction 设计变化
4. provider 间 response 语义完全统一平台
5. 自动 provider 打分、自动 provider 学习、动态成本优化
6. 长期兼容旧的单 provider 配置和旧工厂代码

## Terms

为避免后续文档和实现混乱，这里锁定术语。

### Provider

指一个可配置的模型服务连接，例如：

- `openai`
- `minimax`
- `kimi`

它描述“连到哪儿、用哪个 env 变量取密钥、走哪个 adapter”。

### Adapter

指一类协议族的 transport 实现。

当前阶段只有一个：

- `openai_compat`

它不是某个品牌，而是一组兼容 `/chat/completions` 或 `/responses` 风格 API 的 provider 适配层。

### Profile

指 agent 运行时选择的模型配置条目。

它描述：

- 用哪个 provider
- 用哪个 model
- 上下文窗口参数
- 可选 fallback profiles

agent 继续只绑定 profile，不直接绑定 provider。

## Approaches Considered

### Approach A — keep extending the current single OpenAI client

做法：

- 继续在 `OpenAIChatLLMClient` 里加更多分支
- 在 `models.toml` 里继续塞 `base_url`、`api_key_env`
- 用 `if provider == ...` 方式逐个扩展

优点：

- 短期改动少

缺点：

- `ModelProfile` 会继续同时承担“profile 选择”和“provider 连接”两层职责
- provider 增长后，`llm_client.py` 会继续膨胀
- 很难把 failover、诊断和连接配置做清楚

结论：

- 不推荐

### Approach B — provider registry + one openai_compat adapter

做法：

- 新增 `providers.toml`
- profile 引用 `provider_ref`
- 建立薄 provider registry
- 把现有 OpenAI 路径提升为 `openai_compat` adapter

优点：

- 当前需求范围内最薄
- 新增 OpenAI-compatible provider 基本只需改配置
- 保持密钥在 `.env`
- 和现有 runtime loop / diagnostics 结构兼容

缺点：

- 需要一次性整理配置加载和 client factory 入口

结论：

- **推荐**

### Approach C — full provider plugin architecture

做法：

- 引入 OpenClaw 风格 provider hooks / manifest / runtime plugin

优点：

- 可扩展性强

缺点：

- 明显超出当前仓库体量
- 当前只支持 `openai`、`minimax`、`kimi` 时收益过低
- 容易把 harness 扩成平台

结论：

- 当前阶段不推荐

## Recommended Architecture

推荐采用：

**provider registry + profile binding + one openai_compat adapter + profile-level failover**

### 1. Configuration split

配置面拆成两个文件：

- `config/providers.toml`
- `config/models.toml`

职责分离如下：

#### `providers.toml`

负责 provider 连接配置。

建议格式：

```toml
[providers.openai]
adapter = "openai_compat"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[providers.minimax]
adapter = "openai_compat"
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"

[providers.kimi]
adapter = "openai_compat"
base_url = "https://api.moonshot.cn/v1"
api_key_env = "KIMI_API_KEY"
```

允许的可选字段：

- `extra_headers`
- `supports_responses_api`
- `supports_chat_completions`
- `header_env_map`

当前阶段不需要的字段：

- `cost`
- `oauth`
- `catalog`
- `auth_profile`

这些字段的语义在当前阶段必须固定：

- `extra_headers`
  - 只允许非敏感固定值
- `header_env_map`
  - 值是 `header_name -> env_var_name`
  - 只在确有 provider 要求额外认证 header 时使用
- `supports_responses_api`
  - 明确声明该 provider 是否支持 `/responses`
- `supports_chat_completions`
  - 明确声明该 provider 是否支持 `/chat/completions`

当前阶段不允许隐式猜测 provider 能力。

实现必须遵守：

- 当 model 需要 `/responses`，但 provider 标记 `supports_responses_api = false` 时，直接报明确配置错误
- 当 model 需要 `/chat/completions`，但 provider 标记 `supports_chat_completions = false` 时，直接报明确配置错误
- 不做“先试一个 endpoint，失败后再猜另一个”的隐式 fallback

#### `models.toml`

负责 profile 和模型选择。

建议格式：

```toml
default_profile = "openai_gpt5"

[profiles.openai_gpt5]
provider_ref = "openai"
model = "gpt-5.4"
tokenizer_family = "openai_o200k"
supports_provider_usage = true
fallback_profiles = ["kimi_k2", "minimax_m25"]

[profiles.kimi_k2]
provider_ref = "kimi"
model = "kimi-k2"
tokenizer_family = "openai_o200k"
supports_provider_usage = true

[profiles.minimax_m25]
provider_ref = "minimax"
model = "MiniMax-M2.5"
tokenizer_family = "openai_o200k"
supports_provider_usage = true
```

### 2. Provider config loader

新增：

- `src/marten_runtime/config/providers_loader.py`

职责：

- 解析 `providers.toml`
- 产出 `ProviderConfig` / `ProvidersConfig`
- 做最小字段校验

建议数据结构：

- `ProviderConfig`
  - `adapter`
  - `base_url`
  - `api_key_env`
  - `extra_headers`
  - `supports_responses_api`
  - `supports_chat_completions`
- `ProvidersConfig`
  - `providers: dict[str, ProviderConfig]`

边界：

- 不负责读取真实 API key
- 不负责构造 client
- 不负责 failover

完成定义：

- 能从缺省文件或真实文件稳定加载 provider 配置
- 缺失 provider、缺失 adapter、重复 provider 名称时给出明确错误
- 不读取 secret 值本身
- 对 `supports_responses_api` / `supports_chat_completions` 的缺失和非法组合给出明确错误

### 3. Model profile loader refinement

调整：

- `src/marten_runtime/config/models_loader.py`

变更方向：

- `ModelProfile.provider` 改成 `provider_ref`
- 去掉 `base_url`
- 去掉 `api_key_env`
- 新增 `fallback_profiles: list[str] = []`

边界：

- 仍然只负责 profile
- 不吸收 provider 连接信息

完成定义：

- profile 只能通过 `provider_ref` 引用 provider
- fallback profile 名称可解析
- 保留现有 context window / tokenizer / usage 配置能力
- 原来的 `base_url` / `api_key_env` profile 字段从主实现中删除，不作为长期兼容字段保留

### 4. Provider registry

新增：

- `src/marten_runtime/runtime/provider_registry.py`

职责：

- 根据 `profile + providers config` 解析“本次该用哪个 provider config”
- 暴露统一查询接口给 `build_llm_client()`

建议职责范围：

- `resolve_provider(profile, providers_config)`
- `resolve_fallback_profiles(profile, models_config, providers_config)`

边界：

- 不直接发请求
- 不承载 retry
- 不承载 failover 执行

完成定义：

- 对任一 profile 能稳定解析 primary provider
- 对含 fallback 的 profile 能解析出 fallback provider 链
- 引用不存在 provider 时在启动期或第一次解析期给出明确错误

### 5. OpenAI-compatible adapter

现有：

- `OpenAIChatLLMClient`

建议重构为：

- `OpenAICompatLLMClient`

建议位置：

- `src/marten_runtime/runtime/llm_adapters/openai_compat.py`

职责：

- 处理 OpenAI-compatible provider 的 transport
- 处理 `/chat/completions` 与 `/responses`
- 处理 tool schema 映射
- 处理 usage 归一化
- 处理 provider diagnostics

它应服务于：

- OpenAI 官方
- MiniMax OpenAI-compatible gateway
- Kimi OpenAI-compatible gateway

边界：

- 不知道 provider 叫 OpenAI 还是 Kimi
- 只知道当前 provider config 的 base URL、headers、capabilities
- 不根据消息语义决定 provider

完成定义：

- 给定任意 `openai_compat` provider config，能正常发送请求
- 对 GPT-5 family 继续走 `/responses`
- 对其它 OpenAI-compatible model 保持当前兼容路径
- usage / tool call / final text 解析不退化
- provider 能力声明和实际 endpoint 选择规则一致，没有隐式 endpoint 猜测

### 6. Client factory

当前：

- `build_llm_client()` 直接写死 `provider == "openai"`

建议改为：

- 通过 `provider_ref -> ProviderConfig.adapter` 决定构造哪个 client

目标伪代码：

```python
provider = provider_registry.resolve_provider(profile, providers_config)

if provider.adapter == "openai_compat":
    return OpenAICompatLLMClient(...)

raise ValueError(f"unsupported_llm_adapter:{provider.adapter}")
```

边界：

- factory 只负责构造
- 不承载请求时 failover 逻辑

完成定义：

- `openai`、`minimax`、`kimi` 三个 profile 都能通过同一个 factory 构造 client
- 不再需要在 profile 上写 `base_url` / `api_key_env`
- 原来的单 provider factory 分支删除，不保留死代码

### 7. Profile-level failover

新增薄 failover 机制，建议位置：

- `src/marten_runtime/runtime/llm_failover.py`

职责：

- 当 primary profile 请求失败时，判断是否允许切换到 fallback profiles
- 顺序尝试 fallback profiles
- 记录 failover 过程用于 diagnostics

允许触发 failover 的错误：

- `PROVIDER_UPSTREAM_UNAVAILABLE`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_TIMEOUT`
- `PROVIDER_TRANSPORT_ERROR`
- `PROVIDER_RESPONSE_INVALID`
- `EMPTY_FINAL_RESPONSE`

当前阶段不触发 failover 的情况：

- 鉴权错误
- 配置错误
- tool payload 解析错误
- 业务逻辑错误

### Failover trigger stage

failover 不是“任意失败都整轮重放”，而是分阶段的。

当前阶段只允许两种触发时机：

1. `llm_first` 阶段失败
   - 还没有 tool side effect
   - 可以安全地切到 fallback profile 并重试整轮首个 LLM 请求
2. `llm_second` 阶段失败，且失败原因属于允许 failover 的 provider 级错误
   - tool 调用已经完成，tool result 已经存在
   - 允许切到 fallback profile，只重试“基于既有 tool result 的最终回复生成”

当前阶段明确不允许：

- 在 tool 执行过程中切换 provider
- 因 tool 执行失败而切换 provider
- 重新执行已经完成的 tool 调用，只为了让另一个 provider 再看一遍

这样做的原因是：

- failover 的目标是 provider 可用性兜底
- tool 是否执行、执行了什么结果，仍然保持当前 run 的既有事实
- host 不应因为 provider 切换而制造重复副作用

边界：

- failover 不能改 prompt
- failover 不能改 tool policy
- failover 不能做 provider 意图分类

完成定义：

- primary profile 失败时，runtime 能按顺序尝试 fallback profiles
- 最终 run diagnostics 能明确显示尝试链和失败原因
- 所有 fallback 都失败时，返回最后一个归一化错误，同时保留完整尝试记录
- `llm_first` 与 `llm_second` 两个阶段的 failover 行为可区分、可诊断
- failover 不会造成重复 tool side effect

### 8. Diagnostics surface

需要增强：

- `/diagnostics/runtime`
- `/diagnostics/run/{run_id}`

新增字段建议：

#### `/diagnostics/runtime`

- `provider_count`
- `providers`
  - `provider_ref`
  - `adapter`
  - `base_url`
  - `api_key_env`
- `default_profile`

#### `/diagnostics/run/{run_id}`

- `model_profile`
- `provider_ref`
- `attempted_profiles`
- `attempted_providers`
- `failover_trigger`
- `final_provider_ref`

边界：

- 诊断只暴露 env 变量名，不暴露 secret

完成定义：

- operator 能看清当前 runtime 加载了哪些 provider
- operator 能看清某次 run 是 primary 成功还是 fallback 成功
- operator 能分辨 provider busy、provider empty output、config error 三类问题

## Module Boundaries And Done Criteria

这一节把每个模块的边界和“什么才算完成”锁死，避免实现阶段继续发散。

### Module A — provider config loading

文件：

- `config/providers.toml`
- `src/marten_runtime/config/providers_loader.py`

负责：

- provider 元数据

不负责：

- secret 读取
- client 创建
- request failover

完成标准：

- provider 配置能独立加载和校验
- 配置错误能在启动期或第一次解析时明确暴露

### Module B — profile loading

文件：

- `config/models.toml`
- `src/marten_runtime/config/models_loader.py`

负责：

- profile 到 provider 的引用
- model 名称
- 上下文和 usage 配置
- fallback profile 链

不负责：

- provider transport 细节

完成标准：

- profile 语义保持单一
- 不再携带 base URL 和 key env

### Module C — provider registry

文件：

- `src/marten_runtime/runtime/provider_registry.py`

负责：

- 解析 profile 对应的 provider

不负责：

- transport
- retry
- diagnostics 持久化

完成标准：

- 能稳定解析 primary 和 fallback provider 链

### Module D — openai_compat adapter

文件：

- `src/marten_runtime/runtime/llm_adapters/openai_compat.py`

负责：

- OpenAI-compatible transport family

不负责：

- provider registry
- failover orchestration

完成标准：

- `openai`、`minimax`、`kimi` 都能通过同一 adapter 发请求
- 当前已验证的 tool / usage / diagnostics 能力不退化

### Module E — failover orchestration

文件：

- `src/marten_runtime/runtime/llm_failover.py`
- runtime loop 接入点

负责：

- fallback profile 尝试顺序
- failover reason 归档

不负责：

- provider 选择的语义判断

完成标准：

- 只在允许错误上切 fallback
- 不引入多余 prompt / routing 工程逻辑

### Module F — diagnostics

文件：

- `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- run history 相关结构

负责：

- 向 operator 暴露 provider 尝试链与最终结果

不负责：

- transport 控制

完成标准：

- 能看清配置、运行结果、失败原因

## Definition Of Correctness

这部分定义“什么才是对的”，实现阶段必须按这个标准验收。

### Correct configuration behavior

1. 把新 provider 加进 `providers.toml` 后，不需要改 `llm_client.py`。
2. 新增一个指向该 provider 的 profile 后，agent 可以直接切到它。
3. 密钥缺失时，错误应明确指向缺失的 env 变量名。

### Correct runtime behavior

1. primary profile 成功时，不触发 failover。
2. primary profile 在允许错误上失败时，按声明顺序尝试 fallback profiles。
3. failover 成功后，tool use、usage 和 diagnostics 仍然完整。
4. failover 全部失败时，run history 仍能完整呈现尝试链。
5. `llm_second` 的 failover 只重试最终回复生成，不重新执行工具。

### Correct harness behavior

1. provider 选择不依赖用户消息语义。
2. host 不替 LLM 决定工具。
3. adapter 只处理协议和 transport，不处理业务意图。

### Correct security behavior

1. secret 不写入 `providers.toml`。
2. diagnostics 不返回 secret 值。
3. provider 额外 header 如未来允许配置，也只能走非敏感值或 env 名称映射。

## Testing Design

实现阶段至少应覆盖以下测试。

### 1. Config loader tests

- `providers.toml` 正常加载
- 缺失 provider
- 缺失 adapter
- 缺失 `api_key_env`
- profile 引用不存在 provider
- fallback profile 引用不存在 profile

### 2. Factory tests

- `openai` profile 能构造 `openai_compat` client
- `minimax` profile 能构造 `openai_compat` client
- `kimi` profile 能构造 `openai_compat` client
- 未支持 adapter 返回明确错误

### 3. Adapter tests

- OpenAI official chat path
- GPT-5 Responses path
- OpenAI-compatible tool call path
- usage 归一化保持正确
- provider extra headers 注入正确

### 4. Failover tests

- primary 成功不切换
- 429 触发 fallback
- 529 触发 fallback
- timeout 触发 fallback
- `EMPTY_FINAL_RESPONSE` 触发 fallback
- auth error 不触发 fallback
- `llm_first` failover 不产生 tool side effect
- `llm_second` failover 复用既有 tool result，不重复执行 tool
- provider 不支持所需 endpoint 时返回明确配置错误

### 5. Diagnostics tests

- runtime diagnostics 暴露 providers 列表
- run diagnostics 暴露 attempted profiles/providers
- failover 成功和失败两条路径都有明确记录

### 6. Live verification

实现完成后至少做这几条 live smoke：

1. OpenAI profile 基础问答
2. Kimi profile 基础问答
3. MiniMax profile 基础问答
4. primary profile 故障时 fallback 到次级 profile
5. Feishu 真实消息一条普通对话
6. Feishu 一条显式工具请求

## Migration Plan

### Step 1

新增 `providers.toml` 和 provider loader，但先不改 runtime 调用路径。

退出标准：

- 新配置能被加载
- 在迁移期，旧 `models.toml` 仍可被兼容读取一次，或者由一次性改写脚本转换为新格式

### Step 2

收窄 `models.toml`，让 profile 改为引用 `provider_ref`。

退出标准：

- profile 语义清晰
- 旧格式 `base_url` / `api_key_env` 不再作为长期 source of truth

### Step 3

提取 `openai_compat` adapter，并让 factory 通过 registry 构造 client。

退出标准：

- 三个 provider 都能构造 client

### Step 4

接入 profile-level failover。

退出标准：

- 允许错误下能切 fallback

### Step 5

增强 diagnostics 和 live 验证。

退出标准：

- operator 可观测信息完整

## Risks And Guardrails

### Risk 1 — provider config over-expansion

风险：

- 把 `providers.toml` 做成大而全的平台配置

约束：

- 当前只保留连接级字段

### Risk 2 — adapter grows into semantic router

风险：

- 在 adapter 里继续长出消息语义判断

约束：

- adapter 只处理协议兼容

### Risk 3 — failover becomes hidden policy engine

风险：

- 为了“更智能”而引入按请求内容切 provider

约束：

- failover 只依据 provider 错误码和空输出

### Risk 4 — provider capability guessing reintroduces ugly fallback logic

风险：

- 为了兼容“可能支持也可能不支持”的网关，在 adapter 内部增加 endpoint 猜测和多段 fallback

约束：

- provider 能力通过配置显式声明
- endpoint 选择由 `model family + provider capability flags` 决定
- 不做“先打一枪再说”的隐藏分支

### Risk 5 — migration leaves dead compatibility code in the repository

风险：

- 实现完成后保留旧字段、旧工厂、旧 helper，导致仓库同时存在两套 source of truth

约束：

- 每完成一个迁移块，就删除该块替换掉的旧代码
- 测试只验证新路径，不同时维护新旧双路径

## Final Recommendation

采用：

- `providers.toml` 承载 provider 连接元数据
- `.env` 承载 secret
- `models.toml` 只承载 profile 和模型选择
- `provider registry + openai_compat adapter + profile-level failover`

这是当前阶段最薄、最稳、最符合 `marten-runtime` harness 边界的多 provider 方案。
