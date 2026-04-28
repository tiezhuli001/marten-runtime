# Config Surfaces

This page answers one question: which value belongs in which file.

## Rules

- `.env` only carries secrets and optional machine-local overrides.
- `config/agents.toml` carries the runtime agent registry and selected-agent execution shape.
- `config/*.example.toml` carries the published default templates.
- `config/*.toml` is optional and should exist only for local overrides.
- `apps/<app_id>/app.toml` carries app manifest and app-local bindings.
- `apps/<app_id>/*.md` carries bootstrap assets for the model.
- `mcps.json` carries the live MCP server definitions and any optional tool hints.

## Where To Configure What

| Need | File | Key |
| --- | --- | --- |
| Provider secrets | `.env` | `OPENAI_API_KEY`, `MINIMAX_API_KEY`, `KIMI_API_KEY` |
| Local OpenAI-compatible base URL override | `.env` | `OPENAI_API_BASE`, `MINIMAX_API_BASE`, `KIMI_API_BASE` |
| Provider connection metadata | `config/providers.example.toml` or local `config/providers.toml` | `[providers.*]`, `adapter`, `base_url`, `api_key_env`, capability flags |
| Default model/profile selection | `config/models.example.toml` or local `config/models.toml` | `default_profile`, `[profiles.*]`, `provider_ref`, `fallback_profiles` |
| Runtime agent registry and agent-local app/profile/tool selection | `config/agents.toml` | `[agents.*]`, `enabled`, `app_id`, `allowed_tools`, `prompt_mode`, `model_profile`, `role` |
| Runtime bind host/port defaults | `config/platform.example.toml` or local `config/platform.toml` | `[server].host`, `[server].port` |
| Optional public HTTP base URL | `config/platform.example.toml` or local `config/platform.toml` | `[server].public_base_url` |
| Session replay turn budget | `config/platform.example.toml` or local `config/platform.toml` | `[runtime].session_replay_user_turns` |
| Local host/port override | `.env` | `SERVER_HOST`, `SERVER_PORT` |
| Local public base override | `.env` | `SERVER_PUBLIC_BASE_URL` |
| Session replay turn override | `.env` | `SESSION_REPLAY_USER_TURNS` |
| Feishu enable/mode/autostart | `config/channels.example.toml` or local `config/channels.toml` | `[feishu].enabled`, `connection_mode`, `auto_start` |
| Feishu inbound scope restriction | `config/channels.example.toml` or local `config/channels.toml` | `[feishu].allowed_chat_types`, `allowed_chat_ids` |
| Feishu reconnect policy | `config/channels.example.toml` or local `config/channels.toml` | `[feishu.websocket]` |
| Feishu delivery retry policy | `config/channels.example.toml` or local `config/channels.toml` | `[feishu.retry]` |
| Feishu credentials | `.env` | `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_BASE_URL` |
| Binding rules | `config/bindings.toml` | `[[bindings]]` |
| MCP stdio/http/docker connection | `mcps.json` | `servers.<id>.transport`, `command`, `args`, `env`, `cwd`, `url`, `headers` |
| MCP optional tool hints | `mcps.json` | `servers.<id>.tools[]` |
| App binding / manifest | `apps/<app_id>/app.toml` | app-local fields |
| Model bootstrap instructions | `apps/<app_id>/*.md` | `AGENTS.md`, `TOOLS.md`, `SOUL.md`, `BOOTSTRAP.md` |

## Provider Selection And Failover

Provider ownership is split cleanly:

- `config/providers*.toml` owns provider connection metadata and capability flags
- `config/models*.toml` owns `default_profile`, each profile's `provider_ref`, and `fallback_profiles`
- `.env` only carries secrets plus optional machine-local base URL overrides

Failover order belongs to `fallback_profiles` only. Do not duplicate provider order in `.env` or channel-specific config.

## Agent Registry And Selected-Agent Routing

Agent ownership is split cleanly:

- `config/agents.toml` owns the runtime-visible agent ids and each agent's `app_id`, `allowed_tools`, `prompt_mode`, and `model_profile`
- `config/bindings.toml` owns channel/user/conversation routing defaults
- inbound `requested_agent_id` can explicitly select one configured agent for a turn
- the selected agent determines which app manifest and bootstrap assets are loaded for the live request

When you want to route one agent to another app, tool surface, or model profile, change `config/agents.toml`.

## Runtime-Owned Persistence Paths

The continuity layer has two runtime-owned storage roots and neither is a published operator tuning surface:

- sessions persist in `data/sessions.sqlite3`
- thin user memory persists under `data/memory/`

Thin user memory stores explicit cross-session user facts and preferences. Session history and self-improve lessons remain separate runtime slices.

## Session Restore Contract

Session restore stays on the thin runtime path, remains bounded, and now survives process restart through the SQLite-backed session store.

Runtime-owned restore shape:

- prompt base
- compacted summary
- recent `8` user turns by default
- recent `3` tool outcome summaries
- thin memory

Operator surface:

- default replay budget lives at `[runtime].session_replay_user_turns = 8`
- local override lives at `SESSION_REPLAY_USER_TURNS`
- `session.new` and `session.resume` may enqueue source-session compaction work while keeping the target restore immediate
- this slice keeps one replay knob only

## Current GitHub Hot Repos Automation Slice

This slice is intentionally narrow:

- the user asks the main agent in chat to register a recurring digest
- the runtime stores a recurring automation record
- the operator surface can inspect current recurring jobs through `GET /automations`
- the main agent can inspect current recurring jobs through the narrow builtin `automation` family tool with `action=list`
- recurring-job CRUD stays on the builtin `automation` family tool with `action=update/delete/pause/resume`
- manual execution goes through `POST /automations/{id}/trigger`, which creates one isolated automation turn and delivers the final digest to the configured target

Hard prerequisites:

- a configured GitHub MCP server must be discoverable by the runtime
- the GitHub MCP server must expose at least one repo-discovery tool suitable for ranking and summarization
- `search_repositories` is the preferred minimum capability

Semantic boundary:

- the current baseline persists recurring definitions and supports explicit manual trigger
- due-window auto-dispatch is not part of the current runtime baseline
- the slice does not promise exact parity with `github.com/trending` unless the configured MCP surface can actually provide that data

## Feishu

Feishu MVP uses the official long-connection websocket path. No public callback URL is required for that mode.

Example:

```toml
[feishu]
enabled = true
connection_mode = "websocket"
auto_start = true
allowed_chat_types = ["p2p"]
allowed_chat_ids = []

[feishu.websocket]
auto_reconnect = true
reconnect_count = -1
reconnect_interval_s = 5
ping_interval_s = 120

[feishu.retry]
progress_max_retries = 2
final_max_retries = 5
error_max_retries = 5
base_backoff_seconds = 0.25
max_backoff_seconds = 2.0
```

Secrets stay in `.env`:

```env
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_BASE_URL=https://open.feishu.cn
```

`config/platform.example.toml [server].public_base_url` is valid for the HTTP service itself, but it is not required to bring up Feishu websocket ingress.

## MCP

Use root `mcps.json` as the live user-edited MCP layer. Keep it empty until you actually need MCP access.

Use [../mcps.example.json](../mcps.example.json) as a public-safe reference template.

Example GitHub MCP:

```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "$GITHUB_PERSONAL_ACCESS_TOKEN"
      },
      "timeout_seconds": 30,
      "adapter": "github"
    },
    "github_trending": {
      "transport": "stdio",
      "command": "python",
      "args": [
        "-m",
        "marten_runtime.mcp_servers.github_trending"
      ],
      "timeout_seconds": 30,
      "tools": [
        {
          "name": "trending_repositories",
          "description": "Fetch GitHub trending repositories."
        }
      ]
    }
  }
}
```

Notes:

- If you put the literal token value directly in `mcps.json.env`, that value is authoritative.
- If you use `$GITHUB_PERSONAL_ACCESS_TOKEN`, the runtime resolves it from the current shell or repo `.env`.
- `tools` stays optional and only carries lightweight hints for diagnostics and capability disclosure.

## Local Start

Start the HTTP service with the resolved platform config:

```bash
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

Check the resolved values:

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Look for:

- `server.public_base_url`
- `channels.feishu.connection_mode`
- `channels.feishu.websocket.connected`
- `channels.feishu.websocket.endpoint_url`
  - this field is intended only as a connection diagnostic and is redacted for sensitive query params such as `access_key` and `ticket`
- `mcp_servers[*].source_layers`

Run-level operator diagnostics:

- `GET /diagnostics/run/{run_id}` returns `llm_request_count`
- `GET /diagnostics/run/{run_id}` returns `tool_calls`
- `GET /diagnostics/run/{run_id}` returns `attempted_profiles`, `attempted_providers`, and `final_provider_ref`
- use these fields to confirm whether a real turn invoked `automation`, `mcp`, `self_improve`, or other allowed tools

Feishu live diagnostics:

- `GET /diagnostics/runtime` returns `channels.feishu.websocket.last_session_id`
- `GET /diagnostics/runtime` returns `channels.feishu.websocket.last_run_id`
- use these fields to jump from a real Feishu inbound message to `GET /diagnostics/run/{run_id}`
