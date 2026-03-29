# Live Verification Checklist

This page is the operator-facing checklist for the real chain:

`Feishu -> LLM -> GitHub MCP -> LLM -> Feishu`

It separates three things clearly:

- what is already verified in code and tests
- what local configuration must exist before the last-hop test
- what is still a live-environment prerequisite instead of a repository blocker

## Current Verification Boundary

Already verified in this repository:

- [x] runtime boots with the websocket-first Feishu architecture
- [x] `mcps.json` servers auto-discover tools without static local `config/mcp.toml` tool lists
- [x] GitHub MCP tool execution works on the runtime path
- [x] runtime context assembly replays session context into the next LLM request
- [x] skills are visible to the LLM as startup heads and activated bodies
- [x] provider transport retries transient timeout and transport failures
- [x] Feishu receive-event dedupe keys on stable `message.message_id`
- [x] Feishu self/app-originated messages are ignored
- [x] Feishu final visible reply uses an interactive card while progress stays hidden
- [x] diagnostics redact sensitive websocket query parameters
- [x] duplicate websocket consumers are blocked by a single-instance lock

Not yet proven from a real external conversation:

- [ ] a real Feishu user sends an actual DM or `@` mention to the bot
- [ ] that websocket-native inbound event reaches the running process
- [ ] the live run calls the intended LLM profile
- [ ] the live run calls GitHub MCP from that Feishu-triggered turn
- [ ] the final answer is delivered back into the same Feishu chat
- [ ] only one final reply is delivered for that one human message

## Required Configuration

### 1. Provider

- [ ] `.env` contains a valid provider credential such as `MINIMAX_API_KEY` or `OPENAI_API_KEY`
- [ ] if `.env` overrides the base URL, it points at a reachable OpenAI-compatible endpoint
- [ ] local `config/models.toml` or the published `config/models.example.toml` uses the intended live profile

Blocking symptom if missing:

- `/messages` or Feishu-triggered runs fail before tool execution with auth or transport errors

Relevant files:

- `.env`
- `config/models.example.toml`

### 2. GitHub MCP

- [ ] root `mcps.json` contains a live `github` server entry
- [ ] GitHub PAT is available either literally in `mcps.json.env` or through `$GITHUB_PERSONAL_ACCESS_TOKEN`
- [ ] the target agent is still allowed to use `mcp:*`
- [ ] diagnostics show GitHub MCP discovered tools

Blocking symptom if missing:

- the model run completes without GitHub data, or MCP discovery/call fails

Relevant files:

- `mcps.json`
- `config/agents.toml`
- `config/mcp.example.toml`

### 3. Feishu Channel

- [ ] `.env` contains valid `FEISHU_APP_ID`
- [ ] `.env` contains valid `FEISHU_APP_SECRET`
- [ ] if locally overridden, `.env` contains the correct `FEISHU_BASE_URL`
- [ ] local `config/channels.toml` keeps `[feishu].enabled = true`
- [ ] local `config/channels.toml` keeps `connection_mode = "websocket"`
- [ ] local `config/channels.toml` keeps `auto_start = true`
- [ ] if you want a narrow verification lane, set either `allowed_chat_types = ["p2p"]` or a fixed `allowed_chat_ids = ["<chat_id>"]`
- [ ] the Feishu app is installed in a real chat where a human can message it

Blocking symptom if missing:

- diagnostics show websocket disconnected, or no real inbound conversation can be created

Relevant files:

- `.env`
- `config/channels.example.toml`

## Required Runtime Checks

Before running the real Feishu conversation:

- [ ] start the runtime locally
- [ ] call `GET /diagnostics/runtime`
- [ ] confirm the intended `llm_profile`
- [ ] confirm GitHub MCP shows `discovery.state = "discovered"`
- [ ] confirm Feishu websocket shows `connected = true`

Suggested commands:

```bash
PYTHONPATH=src python -m uvicorn marten_runtime.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8000
```

```bash
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

## Real Conversation Checklist

Use this sequence to prove the live Feishu chain:

1. [ ] start the runtime with the live `.env`
2. [ ] open `/diagnostics/runtime` and confirm the Feishu websocket is connected
3. [ ] prefer a DM or a fixed verification chat instead of a noisy shared group
4. [ ] from that real Feishu chat, send the bot one message that strongly forces GitHub MCP usage
5. [ ] verify the runtime produces a run for that inbound trace
6. [ ] verify the final answer appears in the same Feishu chat
7. [ ] verify the final answer contains GitHub-derived data rather than a generic answer
8. [ ] verify only one final reply appears for that one message
9. [ ] verify the reply text does not contain internal runtime metadata
10. [ ] verify the visible final reply is rendered as a Feishu card

Recommended Feishu prompt:

```text
Use GitHub MCP tool get_me and reply with my GitHub login and public repo count in one sentence.
```

Evidence to capture:

- [ ] Feishu-side screenshot or visible reply text
- [ ] `/diagnostics/runtime` output during the run
- [ ] `/diagnostics/trace/{trace_id}` for the inbound event
- [ ] `/diagnostics/run/{run_id}` for the final run

## Remaining Gaps

Repository-level blockers currently not identified:

- the main runtime spine is already covered by tests
- duplicate reply regression has a process-level websocket lock
- Feishu delivery remains hidden-progress plus single final-card behavior

The remaining work for a true live proof is environmental:

- valid local provider credentials
- valid local GitHub MCP credentials
- a real Feishu chat where the bot can receive a human message

## Exit Criteria

This checklist is complete when all of these are true:

- [ ] a real Feishu message reaches the runtime
- [ ] that run uses the real LLM
- [ ] that run uses GitHub MCP successfully
- [ ] the final answer is delivered back to Feishu
- [ ] the bot replies exactly once for that one human message
- [ ] the result is recorded in `STATUS.md`
