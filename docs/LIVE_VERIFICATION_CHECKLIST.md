# Live Verification Checklist

This page is the operator-facing checklist for the real chain:

`Feishu -> LLM -> GitHub MCP -> LLM -> Feishu`

It also applies to live self-improve inspection turns on the same runtime path:

`Feishu -> LLM -> builtin self-improve tool -> LLM -> Feishu`

It now also covers the verified lightweight subagent live path:

`Feishu -> main agent -> spawn_subagent -> child agent -> GitHub MCP -> parent summary -> Feishu completion notice`

It separates three things clearly:

- what is already verified in code and tests
- what local configuration must exist before the last-hop test
- what is still a live-environment prerequisite instead of a repository blocker

## Current Verification Boundary

Already verified in this repository:

- [x] runtime boots with the websocket-first Feishu architecture
- [x] `mcps.json` servers auto-discover tools without any secondary MCP config file
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

- [x] a real Feishu user sends an actual DM or `@` mention to the bot
- [x] that websocket-native inbound event reaches the running process
- [x] the live run calls the intended LLM profile
- [x] the live run calls GitHub MCP from that Feishu-triggered turn
- [x] the final answer is delivered back into the same Feishu chat
- [x] only one final reply is delivered for that one human message

Already proven from a real external conversation on the lightweight subagent slice:

- [x] a real Feishu user can force the main agent to call `spawn_subagent`
- [x] the accepted child task keeps explicit `parent_run_id` / `child_run_id` lineage
- [x] the child task can retain `tool_profile = standard` and `effective_tool_profile = standard`
- [x] the child run can call the real GitHub MCP `get_me` tool from that Feishu-triggered path
- [x] the child result is written back to the parent as one concise `SessionMessage.system(...)` summary
- [x] Feishu completion notification can be delivered without dead-letter fallback on the live path

Already proven from a real external conversation on the self-improve slice:

- [x] a real Feishu user can query current lesson candidates through the live runtime
- [x] a real Feishu user can delete rejected lesson candidates through the live runtime
- [x] a follow-up Feishu query reflects the updated candidate state
- [x] the resulting live session can be correlated through `last_run_id -> /diagnostics/run/{run_id} -> trace_id -> /diagnostics/trace/{trace_id}`

## Required Configuration

### 1. Provider

- [ ] `.env` contains a valid provider credential such as `MINIMAX_API_KEY` or `OPENAI_API_KEY`
- [ ] if `.env` overrides the base URL, it points at a reachable OpenAI-compatible endpoint
- [ ] local `config/providers.toml` or the published `config/providers.example.toml` uses the intended provider endpoints and capability flags
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

Recommended Feishu prompt for the subagent-specific live proof:

```text
请严格按以下方式处理：
1. 主线程必须先调用 spawn_subagent，不要在主线程直接调用 mcp。
2. spawn_subagent 的参数请使用：
   - label: github-mcp-child-live-check
   - tool_profile: standard
   - notify_on_finish: true
3. 子 agent 的任务是：调用 GitHub MCP 工具 get_me，读取当前 GitHub login；如果可用，再读取我的 public repo count；最后只返回一句简短摘要。
4. 主线程先只回复：已受理，子 agent 正在后台执行。
5. 子 agent 完成后，再通过 Feishu 单独通知我最终结果。
```

Product-level smoke now also works with a short natural-language prompt; it no longer requires the full explicit parameter block above just to trigger a usable subagent path.

Recommended short prompt for product smoke:

```text
开启子代理查询 https://github.com/tiezhuli001/codex-skills 最近一次提交是什么时候
```

Latest proven live evidence for that path:

- parent session: `sess_7d135c6e`
- parent run: `run_5b7cf193`
- parent trace: `trace_b9ca817f`
- child task: `task_1aaaba73`
- child session: `sess_e5fc1628`
- child run: `run_1f387407`
- child MCP call: `server_id = github`, `tool_name = get_me`
- returned GitHub identity facts:
  - `login = tiezhuli001`
  - `public_repos = 9`
- parent-visible completion summary:
  - `你的 GitHub 账号是 **tiezhuli001**，拥有 **9 个公开仓库**。`
- Feishu delivery health during this proof:
  - `dead_letter.count = 0`
  - `delivery_sessions.closed_count = 2`

Latest product-usability smoke after the spawn-policy hardening:

- parent session: `sess_ed0f9ed1`
- parent run: `run_8d8294d0`
- child task: `task_5848ff84`
- child run: `run_fae21f28`
- user prompt was only:
  - `开启子代理查询 https://github.com/tiezhuli001/codex-skills 最近一次提交是什么时候`
- runtime still chose:
  - `spawn_subagent`
  - `tool_profile = standard`
  - `effective_tool_profile = standard`
- child completion summary:
  - `tiezhuli001/codex-skills 最近一次提交是 **2026-04-14 20:01:21**（北京时间）...`

Latest direct Feishu main-chain proof on the current runtime:

- conversation/chat: `oc_5091efbdd295f49cad9bdeed9d92b7ae`
- session: `sess_3072ef1d`
- run: `run_3624374a`
- trace: `trace_a579ef70`
- latest websocket correlation fields:
  - `last_run_id = run_3624374a`
  - `last_runtime_trace_id = trace_a579ef70`
  - `last_session_id = sess_3072ef1d`
  - `dead_letter.count = 0`
  - `delivery_sessions.closed_count = 1`
- user prompt:
  - `请先告诉我现在的北京时间，再用 GitHub MCP 查询 tiezhuli001/codex-skills 最近一次提交时间，最后合并成一句中文回复。`
- verified runtime path:
  - `Feishu -> main agent -> time -> mcp:list -> mcp:list_commits -> Feishu`
- verified final reply:
  - `tiezhuli001/codex-skills 最近一次提交是 **2026-04-14 20:01:21**（北京时间）...`

Evidence to capture:

- [x] Feishu-side screenshot or visible reply text
- [x] `/diagnostics/runtime` output during the run
- [x] `/diagnostics/trace/{trace_id}` for the inbound event
- [x] `/diagnostics/run/{run_id}` for the final run

Trace correlation note:

- `channels.feishu.websocket.last_trace_id` is the raw Feishu websocket trace header, not the runtime trace
- for runtime correlation, prefer `channels.feishu.websocket.last_run_id`
- then open `/diagnostics/run/{run_id}` and use the returned runtime `trace_id`
- `channels.feishu.websocket.last_runtime_trace_id` mirrors that runtime trace for convenience

Recommended live self-improve prompts:

```text
现在都有哪些候选规则
```

```text
删除2条已拒绝的候选规则
```

```text
现在有哪些候选规则
```

## Remaining Gaps

Repository-level blockers currently not identified:

- the main runtime spine is already covered by tests
- duplicate reply regression has a process-level websocket lock
- Feishu delivery remains hidden-progress plus single final-card behavior

The remaining work for a true live proof is environmental:

- valid local provider credentials
- valid local GitHub MCP credentials
- a real Feishu chat where the bot can receive a human message

The remaining work for the subagent slice is not the live GitHub MCP proof itself anymore; it is runtime hardening around delivery timing, especially ensuring the parent acknowledgement is emitted before a fast child task can finish.

## Exit Criteria

This checklist is complete when all of these are true:

- [x] a real Feishu message reaches the runtime
- [x] that run uses the real LLM
- [x] that run uses GitHub MCP successfully
- [x] the final answer is delivered back to Feishu
- [x] the bot replies exactly once for that one human message
- [x] the result is recorded in `docs/ARCHITECTURE_CHANGELOG.md`

For self-improve live inspection, completion additionally means:

- [x] the live Feishu query path can read candidate rules through builtin self-improve tools
- [x] the live Feishu delete path can remove rejected candidates without touching active lessons
- [x] diagnostics clearly separate Feishu raw trace headers from runtime trace correlation
