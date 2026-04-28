# 部署指南

这份文档提供 `marten-runtime` 的最短部署路径。

目标是：

- 用尽量少的步骤把 runtime 跑起来
- 把必需配置压到最小
- 用少量直观检查确认服务健康
- 只在真正需要时再加 Feishu、MCP 和 Langfuse

## 推荐路径

对大多数部署场景，建议按这个顺序做：

1. 先选择部署形态：
   - 本地进程
   - Docker 容器
2. 配置一个 provider 凭据
3. 启动 HTTP runtime
4. 检查 `/healthz`、`/readyz`、`/diagnostics/runtime`
5. 再按需逐个打开可选集成

## 部署形态

当前建议保留两种部署形态：

- 本地进程
  - 适合开发、调试、源码级排查
- Docker 容器
  - 适合隔离部署、稳定复现启动过程、收敛运行环境依赖

面向部署时，Docker 现在是更推荐的默认形态。

如果你希望把部署命令进一步收短、变成一个稳定入口，优先使用 `docker compose`。

## 最小部署

这是当前最小可用的部署方式。

### 1. 环境要求

- Python `3.11`、`3.12` 或 `3.13`
- 一个 OpenAI-compatible provider 凭据

### 2. 初始化

```bash
./init.sh
```

它会：

- 创建或复用 `.venv`
- 安装依赖
- 在缺失时从 `.env.example` 创建 `.env`
- 在缺失时从 `mcps.example.json` 创建 `mcps.json`
- 跑一轮本地 smoke 检查

### 3. 最小配置

当前提交态默认 runtime 使用共享的 `default` profile。

最短路径是：

```env
OPENAI_API_KEY=
```

这个默认 profile 对应的提交态默认模型是 `gpt-5.4`。

如果你想切到别的 provider 或模型，在本地 `config/models.toml` 里重定义 `profiles.default` 即可。

其他配置保持默认即可，只有需要本地覆盖时再加。

### 4. 启动 runtime

```bash
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

### 5. 检查进程健康

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

健康信号：

- `/healthz` 返回 `status = ok`
- `/readyz` 返回 `status = ready`
- `/diagnostics/runtime` 能看到预期的 app 和 LLM profile

## 可直接复制的 Quick Start

如果你想走最短路径，直接按这组命令做：

```bash
./init.sh
```

在 `.env` 里设置一个 provider key 后，启动 runtime：

```bash
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

在另一个终端检查进程：

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

然后发一个最小 HTTP 消息：

```bash
curl -sS http://127.0.0.1:8000/messages \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_id": "http",
    "user_id": "demo",
    "conversation_id": "quickstart-http",
    "message_id": "msg-1",
    "body": "hello"
  }'
```

预期结果：

- 返回 HTTP `200`
- JSON 里有 `session_id`
- 最后一个 event 里有 `run_id`

如果要把这次请求路由到非默认 agent，就在同一个 JSON payload 里补 `requested_agent_id`。

如果还想再确认一步，可以打开：

```bash
curl -sS http://127.0.0.1:8000/diagnostics/run/<run_id>
```

## Docker 部署

如果你希望运行环境更隔离、启动方式更稳定，推荐直接使用 Docker。

### 1. 构建镜像

在仓库根目录执行：

```bash
docker build -t marten-runtime:local .
```

### 2. 准备运行时配置

推荐把配置在运行时注入进容器，不要把 secrets 烘焙进镜像。

针对当前提交态默认 runtime，最小 env 文件是：

```env
OPENAI_API_KEY=
```

当前提交态默认模型是 `gpt-5.4`。

如果你想切到别的 provider 或模型，在本地 `config/models.toml` 里重定义共享的 `default` profile。

示例：

```toml
default_profile = "default"

[profiles.default]
provider = "openai"
model = "gpt-5.4"
tokenizer_family = "openai_o200k"
supports_provider_usage = true
```

可选 server 覆盖：

```env
SERVER_PORT=8000
SERVER_PUBLIC_BASE_URL=http://127.0.0.1:8000
```

推荐做法：

- secrets 保留在本地 `.env`
- 用 `--env-file .env` 注入
- 只有需要本地覆盖时才挂载额外文件

### 3. 启动容器

最小隔离部署形态：

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  marten-runtime:local
```

这个命令已经足够启动默认 HTTP runtime。

### 4. 检查容器

在另一个终端执行：

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

健康信号和本地部署一致：

- `/healthz` 返回 `status = ok`
- `/readyz` 返回 `status = ready`
- `/diagnostics/runtime` 能看到预期的 runtime profile

### 5. 可选挂载

只有需要实时本地覆盖时，再挂载这些文件。

挂载本地 MCP 配置：

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/mcps.json:/app/mcps.json:ro" \
  marten-runtime:local
```

挂载本地 TOML 覆盖：

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/config/platform.toml:/app/config/platform.toml:ro" \
  -v "$(pwd)/config/agents.toml:/app/config/agents.toml:ro" \
  -v "$(pwd)/config/models.toml:/app/config/models.toml:ro" \
  -v "$(pwd)/config/channels.toml:/app/config/channels.toml:ro" \
  marten-runtime:local
```

如果你要重定义共享的 `default` profile，优先挂载 `config/models.toml`。

如果你要改某个 agent 实际使用的 profile，再挂载 `config/agents.toml`。

持久化本地 SQLite 数据：

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  marten-runtime:local
```

### 6. 一条更实用的 operator 命令

如果你想给运维同学一条更接近默认值的命令，可以用：

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/mcps.json:/app/mcps.json:ro" \
  marten-runtime:local
```

这条命令能同时满足：

- 镜像内容稳定
- secrets 留在镜像外
- 容器重启后数据可保留
- MCP 定义可直接替换

## Docker Compose 部署

如果你希望部署命令更短、更稳定、更适合运维复用，推荐直接使用 `docker compose`。

### 1. 基础 compose 路径

仓库已经提供根目录 [compose.yaml](../compose.yaml)。

针对当前提交态默认 runtime，直接执行：

```bash
docker compose up -d --build
```

这条路径默认使用：

- 根目录 `compose.yaml`
- `.env` 作为运行时 env 文件
- `./data` 作为持久化数据目录
- 仓库当前默认的 agent / model 配置

然后检查：

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

### 2. Provider 选择方式

`compose.yaml` 现在会把整个本地 `config/` 目录挂进容器。

这让 provider 选择回到通用配置面：

- 在 `.env` 里放对应 secret
- 如果要换 provider 或模型，在本地 `config/models.toml` 里重定义 `profiles.default`
- 重启 compose stack

当前提交态默认 OpenAI 路径对应的本地 `config/models.toml` 例子：

```toml
default_profile = "default"

[profiles.default]
provider = "openai"
model = "gpt-5.4"
tokenizer_family = "openai_o200k"
supports_provider_usage = true
```

MiniMax 路径例子：

```toml
default_profile = "default"

[profiles.default]
provider = "openai"
model = "MiniMax-M2.5"
base_url = "https://api.minimaxi.com/v1"
api_key_env = "MINIMAX_API_KEY"
tokenizer_family = "openai_o200k"
supports_provider_usage = true
```

如果 `.env` 里没有 active `profiles.default` 需要的 API key，服务会在启动阶段直接失败并退出。

### 3. 常用 compose 控制命令

停止整套服务：

```bash
docker compose down
```

跟日志：

```bash
docker compose logs -f
```

切换 env 文件：

```bash
MARTEN_RUNTIME_ENV_FILE=.env.production docker compose up -d --build
```

切换主机端口：

```bash
MARTEN_RUNTIME_HOST_PORT=18080 docker compose up -d --build
```

### 4. 什么时候 compose 更适合做默认入口

以下场景优先使用 `docker compose`：

- 需要一个仓库内可复用的部署入口
- 需要稳定重启和统一看日志
- 想减少一长串命令参数
- 后面准备再接反向代理或其他 sidecar

## 简单运维路径

服务起来后，最短的运维路径是：

1. 用模板准备配置
2. 启动服务
3. 打开 `/diagnostics/runtime`
4. 发一个 HTTP `/messages` 请求或一条 Feishu 消息
5. 需要追查时再看 `/diagnostics/run/{run_id}`

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

## 可选集成

只有在最小 HTTP runtime 已经健康后，再逐个打开这些能力。

### Feishu

当你需要 live chat ingress 时再打开 Feishu。

本地必需项：

- `.env` 中有 `FEISHU_APP_ID`
- `.env` 中有 `FEISHU_APP_SECRET`
- 如需覆盖可加 `FEISHU_BASE_URL`
- 本地 `config/channels.toml` 至少包含：
  - `[feishu].enabled = true`
  - `connection_mode = "websocket"`
  - `auto_start = true`

然后检查：

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

重点看：

- `channels.feishu.connection_mode = websocket`
- `channels.feishu.websocket.connected = true`

真实链路验证流程请看 [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)。

### MCP

只有需要外部工具时再打开 MCP。

必需文件：

- 根目录 `mcps.json`

推荐方式：

- 从 `mcps.example.json` 开始
- 不需要时保持为空
- 一次只接一个 server

然后检查：

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

重点看 MCP server 是否被发现，以及工具面是否出现。

### Langfuse

只有需要外部 tracing 时再打开 Langfuse。

`.env` 需要：

```env
LANGFUSE_BASE_URL=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

然后检查：

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

重点看：

- `observability.langfuse.enabled`
- `observability.langfuse.configured`
- `observability.langfuse.healthy`

## 配置归属

为了保持部署简单，每类配置只放在一个地方：

- `.env`
  - secrets 和机器本地 override
- `config/*.example.toml`
  - 公开模板默认值
- `config/*.toml`
  - 可选本地覆盖
- `mcps.json`
  - 实时 MCP server 定义
- `apps/<app_id>/*.md`
  - prompt / bootstrap 资产

完整配置映射请看 [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)。

## 当前部署说明

当前部署层面的真实情况是：

- runtime 主链已经适合进入部署准备
- durable SQLite session persistence 已经进入基线
- 跨重启 session continuity 通过 bounded restore、session binding 持久化和 persisted compaction jobs 生效
- 会话切换继续保持显式控制面：`session.new` / `session.resume`，source session compaction 可以在后台完成

这意味着当前最简单的部署形态是：

- 一个 runtime 进程或一个 Docker 容器
- template-first 配置
- 先用 runtime diagnostics 作为 operator surface
- Feishu、MCP、Langfuse 按需逐步打开

## 推荐部署形态

根据当前目标，优先选择最小部署形态：

### 1. 本地 HTTP-only quick start

适合先确认 runtime 活着。

- 一个本地进程
- 一个 provider key
- 不开 Feishu
- 不开 MCP
- 不开 Langfuse

### 2. Operator 开发环境

适合带上诊断面和可选外部工具。

- 一个本地进程
- 一个 provider key
- 可选 MCP
- 可选 Langfuse
- 只有需要验证聊天路径时才开 Feishu

### 3. 实时聊天环境

适合验证真实 Feishu 路径。

- 一个 runtime 进程
- provider key
- Feishu 凭据
- 是否启用 MCP 取决于场景
- 如果需要外部 tracing，再开 Langfuse

这个顺序是刻意设计的：

- 先 HTTP-only
- 再加 diagnostics 和外部工具
- 最后再加 live chat ingress

这样部署过程更简单，问题也更容易定位。

## 快速排障

### `./init.sh` 提示 provider credential missing

原因：

- `.env` 里没有 `OPENAI_API_KEY` 或 `MINIMAX_API_KEY`

处理：

- 在 `.env` 里设置一个 provider key
- 重新执行 `./init.sh`

### `/readyz` 没有 ready

先检查：

- provider 凭据
- 本地 config override
- 启动日志

### Feishu 没连上

先检查：

- `config/channels.toml`
- `.env` 里的 Feishu 凭据
- `/diagnostics/runtime` 中的 websocket 字段

### MCP 工具没出现

先检查：

- `mcps.json`
- MCP 凭据
- `/diagnostics/runtime` 中的 discovered tools

### Langfuse 已配置但 unhealthy

先检查：

- Langfuse 凭据
- 网络可达性
- `/diagnostics/runtime` 中的 `observability.langfuse` 字段

## 推荐阅读顺序

部署过程中建议按这个顺序读：

1. [../README_CN.md](../README_CN.md)
2. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
3. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)
4. [ARCHITECTURE_EVOLUTION_CN.md](./ARCHITECTURE_EVOLUTION_CN.md)
