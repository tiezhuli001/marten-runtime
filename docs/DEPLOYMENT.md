# Deployment Guide

This guide is the shortest deployment path for `marten-runtime`.

Goal:

- get one runtime process up quickly
- keep the required configuration small
- verify the service with a few obvious checks
- add Feishu, MCP, and Langfuse only when you actually need them

## Recommended Path

For most deployments, use this order:

1. choose one runtime shape:
   - local process for development
   - Docker container for isolated deployment
2. set one provider credential
3. start the HTTP runtime
4. verify `/healthz`, `/readyz`, and `/diagnostics/runtime`
5. add optional integrations one by one

## Deployment Shapes

Use one of these two shapes:

- Local process
  - best for source-level development, debugging, and rapid iteration
- Docker container
  - best for isolated deployment, reproducible startup, and cleaner runtime dependencies

For deployment-facing usage, Docker is now the recommended default shape.

If you want one stable operator command instead of a long `docker run ...`, use `docker compose`.

## Minimal Deployment

This is the smallest useful setup.

### 1. Requirements

- Python `3.11`, `3.12`, or `3.13`
- one OpenAI-compatible provider credential

### 2. Bootstrap

```bash
./init.sh
```

What it does:

- creates or reuses `.venv`
- installs dependencies
- creates `.env` from `.env.example` when missing
- creates `mcps.json` from `mcps.example.json` when missing
- runs a local smoke check

### 3. Minimum config

The committed default runtime now uses the shared `default` profile.

The shortest current setup is:

```env
OPENAI_API_KEY=
```

The committed default model for that profile is `gpt-5.4`.

If you want another provider or model, redefine `profiles.default` in a local `config/models.toml`.

Keep everything else at defaults unless you need local overrides.

### 4. Start the runtime

```bash
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

### 5. Verify the process

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Healthy signs:

- `/healthz` returns `status = ok`
- `/readyz` returns `status = ready`
- `/diagnostics/runtime` shows the expected app and LLM profile

## Copy-Paste Quick Start

If you want the shortest possible path, use this exact sequence:

```bash
./init.sh
```

Edit `.env` and set one provider key, then start the runtime:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

In another terminal, verify the process:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Then send one minimal HTTP message:

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

Expected result:

- the response is HTTP `200`
- the JSON contains `session_id`
- the final event contains `run_id`

If you want one more confirmation step, open:

```bash
curl -sS http://127.0.0.1:8000/diagnostics/run/<run_id>
```

## Docker Deployment

Docker is the recommended deployment path when you want a cleaner runtime boundary.

### 1. Build the image

From the repository root:

```bash
docker build -t marten-runtime:local .
```

### 2. Prepare runtime config

Use runtime-injected config instead of baking secrets into the image.

Minimum env file for the committed default runtime:

```env
OPENAI_API_KEY=
```

The committed default model is `gpt-5.4`.

If you want another provider or model, redefine the shared `default` profile in a local `config/models.toml`.

Example:

```toml
default_profile = "default"

[profiles.default]
provider = "openai"
model = "gpt-5.4"
tokenizer_family = "openai_o200k"
supports_provider_usage = true
```

Optional server overrides:

```env
SERVER_PORT=8000
SERVER_PUBLIC_BASE_URL=http://127.0.0.1:8000
```

Recommended practice:

- keep secrets in a local `.env`
- pass them with `--env-file .env`
- mount local overrides only when you actually need them

### 3. Run the container

The minimal isolated shape is:

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  marten-runtime:local
```

That is enough for the default HTTP runtime.

### 4. Verify the container

In another terminal:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Healthy signs stay the same:

- `/healthz` returns `status = ok`
- `/readyz` returns `status = ready`
- `/diagnostics/runtime` shows the expected runtime profile

### 5. Optional mounts

Use mounts only for live local overrides.

Mount local MCP config:

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/mcps.json:/app/mcps.json:ro" \
  marten-runtime:local
```

Mount local TOML overrides:

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

Use `config/models.toml` when you want to redefine the shared `default` profile or add extra profiles.

Use `config/agents.toml` only when you want to change which profile a specific agent runs.

Persist local SQLite data:

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  marten-runtime:local
```

### 6. One-file operator command

If you want one practical default command for operators, use:

```bash
docker run --rm \
  --name marten-runtime \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/mcps.json:/app/mcps.json:ro" \
  marten-runtime:local
```

This keeps:

- image contents stable
- secrets outside the image
- data persistent across container restarts
- MCP definitions easy to replace

## Docker Compose Deployment

`docker compose` is recommended when you want the deployment command to stay short and repeatable.

### 1. Base compose path

The repository now includes a root [compose.yaml](../compose.yaml).

For the committed default runtime baseline:

```bash
docker compose up -d --build
```

That path uses:

- the root `compose.yaml`
- `.env` as the runtime env file
- `./data` as the persistent data directory
- the current repository baseline for agent and model config

Then verify:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

### 2. Provider selection

`compose.yaml` now mounts the whole local `config/` directory into the container.

That keeps provider selection generic:

- set the matching secret in `.env`
- redefine `profiles.default` in local `config/models.toml` when you want another provider or model
- restart the stack

Example local `config/models.toml` for the committed default OpenAI path:

```toml
default_profile = "default"

[profiles.default]
provider = "openai"
model = "gpt-5.4"
tokenizer_family = "openai_o200k"
supports_provider_usage = true
```

Example local `config/models.toml` for a MiniMax path:

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

If `.env` does not contain the API key required by the active `profiles.default`, the service exits during startup.

### 3. Useful compose controls

Stop the stack:

```bash
docker compose down
```

Tail logs:

```bash
docker compose logs -f
```

Use a different env file:

```bash
MARTEN_RUNTIME_ENV_FILE=.env.production docker compose up -d --build
```

Use a different host port:

```bash
MARTEN_RUNTIME_HOST_PORT=18080 docker compose up -d --build
```

### 4. When compose is the better default

Prefer `docker compose` when you want:

- one checked-in deployment entry
- stable restarts and log access
- fewer copy-paste flags
- a clean path for later reverse-proxy or extra sidecars

## Simple Local Operator Workflow

Once the server is up, the shortest useful operator loop is:

1. create or reuse config through templates
2. start the server
3. hit `/diagnostics/runtime`
4. send one HTTP `/messages` request or one Feishu message
5. inspect `/diagnostics/run/{run_id}` when needed

Useful endpoints:

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

## Optional Integrations

Add these only when the minimal HTTP runtime is already healthy.

### Feishu

Add Feishu when you want live chat ingress.

Required local pieces:

- `FEISHU_APP_ID` in `.env`
- `FEISHU_APP_SECRET` in `.env`
- optional `FEISHU_BASE_URL` override in `.env`
- local `config/channels.toml` with:
  - `[feishu].enabled = true`
  - `connection_mode = "websocket"`
  - `auto_start = true`

Then verify:

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Look for:

- `channels.feishu.connection_mode = websocket`
- `channels.feishu.websocket.connected = true`

For the real-chain procedure, use [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md).

### MCP

Add MCP only when you need external tools.

Required file:

- root `mcps.json`

Recommended pattern:

- start from `mcps.example.json`
- keep the file empty until you need a server
- add one server at a time

Then verify:

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Look for discovered MCP servers and tool surfaces.

### Langfuse

Add Langfuse only when you want external tracing.

Required `.env` keys:

```env
LANGFUSE_BASE_URL=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

Then verify:

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Look for:

- `observability.langfuse.enabled`
- `observability.langfuse.configured`
- `observability.langfuse.healthy`

## Config Ownership

Keep config simple by using each file for one purpose:

- `.env`
  - secrets and machine-local overrides
- `config/*.example.toml`
  - published defaults
- `config/*.toml`
  - optional local overrides only
- `mcps.json`
  - live MCP server definitions only
- `apps/<app_id>/*.md`
  - prompt/bootstrap assets

For the full mapping, use [CONFIG_SURFACES.md](./CONFIG_SURFACES.md).

## Deployment Notes

Current deployment reality:

- the runtime path is ready for deployment-oriented setup work
- durable session persistence is still intentionally pending
- same-process conversation continuity is available
- cross-restart durable session continuity is not the current baseline

This means the simplest current deployment shape is:

- one runtime process or one Docker container
- template-first config
- runtime diagnostics as the first operator surface
- optional Feishu, MCP, and Langfuse added incrementally

## Recommended Deployment Shapes

Use the smallest shape that matches your current goal:

### 1. Local HTTP-only quick start

Use this when you want the fastest proof that the runtime is alive.

- one local process
- one provider key
- no Feishu
- no MCP
- no Langfuse

### 2. Operator development setup

Use this when you want the runtime plus diagnostics and optional external tools.

- one local process
- one provider key
- optional MCP
- optional Langfuse
- Feishu only if you are validating the chat path

### 3. Live chat setup

Use this when you need the real Feishu path.

- one runtime process
- provider key
- Feishu credentials
- optional MCP depending on the scenario
- optional Langfuse if you want external tracing

This ordering is intentional:

- HTTP-only first
- then diagnostics and external tools
- then live chat ingress

That keeps deployment simple and makes failures easier to isolate.

## Fast Troubleshooting

### `./init.sh` stops with provider credential missing

Cause:

- `.env` does not contain `OPENAI_API_KEY` or `MINIMAX_API_KEY`

Fix:

- set one provider key in `.env`
- rerun `./init.sh`

### `/readyz` is not ready

Check:

- provider credentials
- local config overrides
- startup logs from the running process

### Feishu is not connected

Check:

- `config/channels.toml`
- Feishu credentials in `.env`
- websocket connection fields in `/diagnostics/runtime`

### MCP tools are missing

Check:

- `mcps.json`
- MCP credentials
- discovered tool list in `/diagnostics/runtime`

### Langfuse is configured but unhealthy

Check:

- Langfuse credentials
- network reachability
- `observability.langfuse` fields in `/diagnostics/runtime`

## Suggested Reading Order

Use this order during deployment work:

1. [../README.md](../README.md)
2. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
3. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)
4. [ARCHITECTURE_EVOLUTION.md](./ARCHITECTURE_EVOLUTION.md)
