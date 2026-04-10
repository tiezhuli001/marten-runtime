# marten-runtime

<div align="center">

面向私有 agent 场景的 simplified openclaw-style runtime，聚焦 `channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel` 主链。

[English](./README.md) · [文档索引](./docs/README.md) · [架构演进](./docs/ARCHITECTURE_EVOLUTION_CN.md) · [Harness 设计](./docs/2026-03-29-private-agent-harness-design.md) · [Conversation Lanes 设计](./docs/2026-03-30-conversation-lanes-provider-resilience-design.md) · [配置面说明](./docs/CONFIG_SURFACES.md)

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Runtime](https://img.shields.io/badge/runtime-private--agent-black?style=flat-square)

</div>

`marten-runtime` 是一个收敛的私有 agent runtime。它的目标不是做重型 workflow 平台，而是先把你自己的 agent、MCP 和 skill 托管到一条稳定、可诊断、可扩展的执行主链上。

## Overview

- `LLM + agent + MCP + skill` first
- `harness-thin, policy-hard, workflow-light`
- 支持 channel/user/conversation 级绑定与多 agent 路由
- 支持受治理的 runtime context assembly、会话回放与 working context 压缩
- skills 作为运行时一等输入，而不是静态文件摆设
- 支持 OpenAI-compatible provider，并带最小 retry/backoff 韧性
- 提供 Feishu websocket 接入和轻量 HTTP operator surface

## Why This Exists

很多 agent 项目要么停在 prompt demo，要么过早扩张到 queue、planner、复杂 worker 编排。`marten-runtime` 刻意不走那条路线，而是先把真正要跑通的私有 agent 主链打稳。

当前唯一优先的链路是：

`channel -> binding -> agent -> LLM -> MCP -> skill -> LLM -> channel`

如果一个改动不能直接增强这条链路，它就不应该排到高优先级。

## At A Glance

| 层 | 职责 |
| --- | --- |
| `channel` | HTTP / Feishu 输入、进度事件和最终回包 |
| `binding` | 把 channel/user/conversation 稳定绑定到正确 agent |
| `agent` | app 层策略、可用工具和 bootstrap prompt |
| `runtime` | 上下文拼装、模型调用、tool loop、诊断 |
| `capabilities` | MCP 工具和文件型 skills |

## Core Flow

```mermaid
flowchart LR
    A["HTTP / Feishu 消息"] --> B["Gateway + Binding"]
    B --> C["Agent Router"]
    C --> D["Runtime Context Assembly"]
    D --> E["LLM"]
    E -->|"tool call"| F["MCP / Builtin Tool"]
    F --> E
    E --> G["Channel Delivery"]
```

## Current Scope

当前 MVP 的 A/B 主线已经实现：

- 多主 agent 私有配置加载与稳定路由优先级
- HTTP 入站 `requested_agent_id` 已能真实命中选中的 agent
- selected agent 身份已真实下沉到 LLM request
- runtime context assembly 已具备受治理 replay、working context 压缩和长对话回归测试
- skills first-class runtime integration
- provider retry/backoff resilience

当前仍然明确 deferred：

- 薄 per-agent model-profile 动态切换
- per-agent app manifest / bootstrap prompt 切换
- durable session persistence

同样明确暂不做：

- queue-first execution
- durable delivery outbox
- heartbeat / cron / proactive jobs
- hybrid memory promotion
- planner / swarm 编排

当前正在收敛实现的 MVP 例外：

- 一个通过聊天注册的 GitHub 热门仓库日报路径
- 该路径要求已经配置 GitHub MCP，且 MCP 至少提供 `search_repositories` 这类 repo discovery 能力
- 业务逻辑仍放在 skill 中，平台只补一层很薄的 automation bridge
- 自动任务查询能力保持收敛：模型侧只暴露 `automation` family tool；operator 侧保留 `GET /automations`
- 自动任务增删改停恢复同样保持收敛，只通过 builtin tools 完成，不额外引入本地 automation MCP
- 这不代表仓库正在扩成通用 proactive jobs / workflow 平台

## 升级日志

最近一轮 MVP 收敛更新：

- GitHub 热榜已收敛到 repo-local MCP sidecar：`github_trending.trending_repositories`
- 已从 active 代码、测试、automation 数据中移除 legacy `github_hot_repos_digest` skill 面
- 历史 automation 记录会在 store 边界自动迁移到 canonical `github_trending_digest`
- GitHub 热榜 Feishu 卡片现在会明确说明“按 GitHub Trending 页面顺序”，且不会重复展示抓取时间
- 自动任务 `automation` family tool 统一承载 `register/list/detail/update/delete/pause/resume`
- 保持 `LLM + agent + skill + MCP first`，没有为 GitHub 热榜增加 runtime 业务特判
- 增加会话级 conversation lanes，同一 `channel_id + conversation_id` 的 HTTP `/messages` 和 Feishu interactive turn 会按 FIFO 串行处理
- 增强 provider resilience，对 `429`、`502`、`503`、`504` 做 retryable 归一化，并输出稳定的 provider-specific error code
- 增强 Feishu 诊断面，能直接看到最近一次入站对应的 `session_id`、`run_id`、`llm_request_count` 和 `tool_calls`
- 修复 Feishu 实链不稳定因素：重复语义重放、单次 runtime 异常打断 websocket、空白消息触发错误可见回复，以及重复 websocket 事件覆盖最近 accepted 状态

## Repository Layout

- `src/marten_runtime/`：runtime、channels、MCP、skills、sessions、diagnostics
- `config/*.toml`：运行时策略和默认值
- `config/bindings.toml`：channel/user/conversation 到 agent 的绑定规则
- `apps/<app_id>/app.toml`：app manifest
- `apps/<app_id>/*.md`：bootstrap prompt 资产
- `skills/`：共享文件型 skills
- `.env.example`：本地 secrets 模板
- `mcps.example.json`：MCP 连接模板
- `docs/`：设计、计划、检查清单与配置说明
- `tests/`：主链相关单元测试与契约测试

## Getting Started

### Requirements

- Python `3.11`、`3.12` 或 `3.13`
- 一个可用的 OpenAI-compatible provider 凭据
- 如果要跑真实集成，还需要可选的 Feishu 和 MCP 凭据

### Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

### Configure

```bash
cp .env.example .env
cp mcps.example.json mcps.json
```

配置边界：

- `.env`：只放 secrets 和机器本地 override
- `mcps.json`：只放实时 MCP server 定义
- `config/*.example.toml`：公开提交的模板默认值
- `config/*.toml`：对应模板的本地覆盖文件
- `apps/<app_id>/*.md`：放 bootstrap 和 agent 行为资产

最小可运行配置：

- 在 `.env` 设置一个 provider key，例如 `MINIMAX_API_KEY` 或 `OPENAI_API_KEY`
- 只有需要本地覆盖时才把 `config/*.example.toml` 复制成 `config/*.toml`
- 只有需要外部工具时才在 `mcps.json` 配置 MCP
- 只有准备好了 Feishu bot 时才通过本地 `config/channels.toml` 打开 Feishu

当前公开仓库的配置形态：

- 提交：`config/agents.toml`、`config/bindings.toml`、`config/*.example.toml`
- 本地忽略覆盖：`config/platform.toml`、`config/models.toml`、`config/channels.toml`、`config/mcp.toml`

## Privacy And Open-Source Hygiene

仓库按模板优先的方式准备开源：

- 提交 `.env.example`，不提交真实 `.env`
- 提交 `mcps.example.json`，不提交真实 `mcps.json`
- secrets 只保留在本地环境或被忽略的本地文件里
- 文档不保留本地路径、真实 token、聊天标识或运维快照

默认 `.gitignore` 已经忽略本地 secrets、MCP 连接文件、数据库和运行时产物。

## Run

```bash
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

常用端点：

- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
- `POST /sessions`
- `POST /messages`
- `GET /automations`
- `GET /diagnostics/runtime`
- `GET /diagnostics/session/{session_id}`
- `GET /diagnostics/run/{run_id}`
- `GET /diagnostics/trace/{trace_id}`

其中 `GET /diagnostics/run/{run_id}` 会暴露 `llm_request_count` 和 `tool_calls`，便于确认一次 turn 是否真的走了预期的 `LLM -> tool -> LLM` 主链。

## Testing

Milestone A 重点回归：

```bash
PYTHONPATH=src python -m unittest tests.test_bindings tests.test_router tests.test_runtime_context tests.test_skills tests.test_runtime_loop tests.test_provider_retry tests.test_feishu -v
```

全量测试：

```bash
PYTHONPATH=src python -m unittest -v
```

建议直接运行上面的命令进行本地全量验证，不要依赖文档中固定的测试数量。

## Documentation

建议阅读顺序：

1. [docs/README.md](./docs/README.md)
2. [docs/ARCHITECTURE_EVOLUTION_CN.md](./docs/ARCHITECTURE_EVOLUTION_CN.md)
2. [docs/2026-03-29-private-agent-harness-design.md](./docs/2026-03-29-private-agent-harness-design.md)
3. [docs/2026-03-30-conversation-lanes-provider-resilience-design.md](./docs/2026-03-30-conversation-lanes-provider-resilience-design.md)
4. [docs/2026-03-30-self-improve-design.md](./docs/2026-03-30-self-improve-design.md)
5. [docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md](./docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md)
6. [docs/CONFIG_SURFACES.md](./docs/CONFIG_SURFACES.md)
