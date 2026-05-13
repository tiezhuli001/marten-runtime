# Remove App Abstraction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `app` as a first-class runtime concept and make `agent` own prompt assets, tool policy, model profile, and runtime identity.

**Architecture:** Replace `apps/<app_id>/app.toml` with agent-owned asset roots declared in `config/agents.toml`. Keep `main` as the default routed agent through `AgentRouter(default_agent_id="main")`; future agents are selected by `requested_agent_id`, bindings, or active session state. Keep existing persisted `bootstrap_manifest_id` field as a compatibility field, but generate it from `agent_id + prompt_mode`. Keep Feishu `FEISHU_APP_ID` untouched because it is an external platform credential name.

**Tech Stack:** Python, Pydantic, FastAPI, SQLite stores, pytest.

---

## File Map

- Move: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/*` -> `/Users/litiezhu/workspace/github/marten-runtime/agents/main/*`
- Delete: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/app.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/defaults.py`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/assets.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/specs.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/ids.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/config/agents_loader.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime_support.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/app.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/case_state.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/subagents/models.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/subagents/service.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/spawn_subagent_tool.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/automation/models.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/automation/dispatch.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/automation/sqlite_store.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/automation_tool_support.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/self_improve/service.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/self_improve/review_dispatcher.py`
- Modify tests under `/Users/litiezhu/workspace/github/marten-runtime/tests/`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/http_app_support.py`
- Modify docs: `/Users/litiezhu/workspace/github/marten-runtime/README.md`, `/Users/litiezhu/workspace/github/marten-runtime/docs/CONFIG_SURFACES.md`, `/Users/litiezhu/workspace/github/marten-runtime/docs/README.md`, `/Users/litiezhu/workspace/github/marten-runtime/docs/DEPLOYMENT.md`

## Guardrails

- Preserve runtime path: channel -> binding -> agent router -> default `main` agent -> runtime loop -> tools/subagents -> delivery.
- Preserve default-agent routing semantics: `requested_agent_id` -> binding match -> active session agent -> `main`.
- Preserve session/history `bootstrap_manifest_id` DB column name for compatibility.
- Keep `bootstrap_manifest_id` values deterministic as `agent_{agent_id}_{prompt_mode}` for new runs.
- Remove `app_id` from public runtime diagnostics, agent specs, subagent tasks, automation jobs, and LLM request metadata.
- Keep external Feishu credential and payload names containing `app_id` because they refer to Feishu platform apps.
- Do not touch Feishu environment variable names: `FEISHU_APP_ID` and `FEISHU_APP_SECRET`.
- Commit after each task.

## Chunk 1: Agent Assets Replace App Manifest

### Task 1: Add failing tests for agent-owned assets

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_agent_specs.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/contracts/test_runtime_contracts.py`

- [ ] Add tests asserting `load_agent_specs()` reads `asset_root` and ignores legacy `app_id`.
- [ ] Add tests asserting missing `asset_root` defaults to `agents/main` and duplicate tools remain de-duplicated.
- [ ] Add runtime contract asserting `runtime.default_agent.agent_id == "main"`, `runtime.agent_router.default_agent_id == "main"`, `runtime.agent_runtimes["main"].prompt_manifest_id == "agent_main_full"`, and no `runtime.app_manifest` attribute.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/test_agent_specs.py tests/contracts/test_runtime_contracts.py -q
```

Expected: failing tests reference missing `asset_root`, `agent_runtimes`, or existing `app_manifest`.

### Task 2: Implement agent asset loader

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/defaults.py`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/assets.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/specs.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/ids.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/config/agents_loader.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime_support.py`

- [ ] Add `DEFAULT_AGENT_ID = "main"` and `DEFAULT_AGENT_ASSET_ROOT = "agents/main"`.
- [ ] Update `canonicalize_runtime_agent_id()` to import `DEFAULT_AGENT_ID` from `marten_runtime.agents.defaults`.
- [ ] Add `AgentSpec.asset_root`, `bootstrap_file`, `identity_file`, `agents_file`, `tools_file`.
- [ ] Add `AgentSpec.prompt_manifest_id` returning `agent_{agent_id}_{prompt_mode}`.
- [ ] Add `load_agent_runtime_assets(repo_root, spec)` returning `AgentRuntimeAssets(agent_id, asset_root, prompt_manifest_id, system_prompt)`.
- [ ] Replace `load_app_runtimes()` with `load_agent_runtimes()`.
- [ ] Run the same tests.
- [ ] Commit:

```bash
git add src/marten_runtime/agents src/marten_runtime/config/agents_loader.py src/marten_runtime/interfaces/http/bootstrap_runtime_support.py tests/test_agent_specs.py tests/contracts/test_runtime_contracts.py
git commit -m "Refactor runtime assets around agents"
```

## Chunk 2: Runtime Bootstrap Uses Agent Assets

### Task 3: Move prompt assets and config

**Files:**
- Move: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/AGENTS.md` -> `/Users/litiezhu/workspace/github/marten-runtime/agents/main/AGENTS.md`
- Move: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/BOOTSTRAP.md` -> `/Users/litiezhu/workspace/github/marten-runtime/agents/main/BOOTSTRAP.md`
- Move: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/SOUL.md` -> `/Users/litiezhu/workspace/github/marten-runtime/agents/main/SOUL.md`
- Move: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/TOOLS.md` -> `/Users/litiezhu/workspace/github/marten-runtime/agents/main/TOOLS.md`
- Move: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/SYSTEM_LESSONS.md` -> `/Users/litiezhu/workspace/github/marten-runtime/agents/main/SYSTEM_LESSONS.md`
- Delete: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/app.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/config/agents.toml`

- [ ] Move files with `git mv`.
- [ ] Add `asset_root = "agents/main"` to `agents.main`, `agents.coding`, and `agents.ops`.
- [ ] Keep `main` enabled and keep existing `allowed_tools`, `prompt_mode`, and `model_profile` values unchanged.
- [ ] Keep `coding` and `ops` as agents; only their asset source changes.
- [ ] Remove `app_id = "main_agent"` from `config/agents.toml`.
- [ ] Commit:

```bash
git add apps agents config/agents.toml
git commit -m "Move runtime prompt assets under agents"
```

### Task 4: Update HTTP runtime bootstrap

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/app.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/case_state.py`

- [ ] Replace `app_manifest` state field with direct `default_agent`, `default_prompt_manifest_id`, and `agent_runtimes`.
- [ ] Build the router with `default_agent_id="main"` from `DEFAULT_AGENT_ID`, independent of any asset file.
- [ ] Replace `state.app_runtimes[...]` with `state.agent_runtimes[agent.agent_id]`.
- [ ] Add a safe fallback to `state.agent_runtimes[state.default_agent.agent_id]` for unknown or disabled asset references.
- [ ] Replace session bootstrap manifest values with `agent_runtime.prompt_manifest_id`.
- [ ] Update `/sessions`, inbound messages, automation dispatch, and eval case seeding to use `state.default_prompt_manifest_id` or selected `agent_runtime.prompt_manifest_id`.
- [ ] Remove `app_id` from runtime diagnostics JSON.
- [ ] Keep `default_agent_id` in runtime diagnostics JSON and derive it from `runtime.default_agent.agent_id`.
- [ ] Keep response/session metadata `agent_id`, `model_profile_name`, and `bootstrap_manifest_id`.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/contracts/test_runtime_contracts.py tests/test_http_runtime_diagnostics.py tests/test_acceptance.py tests/evals/test_executor.py -q
```

- [ ] Commit:

```bash
git add src/marten_runtime/interfaces/http tests/contracts/test_runtime_contracts.py tests/test_http_runtime_diagnostics.py tests/test_acceptance.py
git commit -m "Use agent assets in HTTP runtime bootstrap"
```

## Chunk 3: Remove app_id From Runtime Data Flow

### Task 5: LLM request and runtime metadata

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/request_flow.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/session/title_summary.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/session/compaction_runner.py`
- Modify related tests containing `LLMRequest(... app_id=...)`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_session_catalog.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_usage_estimator.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_usage.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_models.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_compaction_trigger.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_llm_transport.py`

- [ ] Remove `LLMRequest.app_id`.
- [ ] Remove `app_id` from Langfuse/runtime metadata.
- [ ] Remove `app_id` argument from session title summary and self-improve judge request construction.
- [ ] Update `session/compaction_runner.py` so compaction LLM requests use `agent_id="compaction"` without app metadata.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/test_llm_client.py tests/test_llm_message_support.py tests/test_llm_transport.py tests/test_session_catalog.py tests/test_usage_estimator.py tests/test_runtime_usage.py tests/test_compaction_trigger.py tests/runtime_loop -q
```

- [ ] Commit:

```bash
git add src/marten_runtime/runtime src/marten_runtime/session tests/test_llm_client.py tests/test_llm_message_support.py tests/runtime_loop
git commit -m "Remove app id from LLM runtime requests"
```

### Task 6: Subagents use agent_id only

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/subagents/models.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/subagents/service.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/spawn_subagent_tool.py`
- Modify tests under `/Users/litiezhu/workspace/github/marten-runtime/tests/test_subagent_service.py`, `/Users/litiezhu/workspace/github/marten-runtime/tests/test_subagent_runtime_loop.py`, `/Users/litiezhu/workspace/github/marten-runtime/tests/tools/test_subagent_tools.py`, `/Users/litiezhu/workspace/github/marten-runtime/tests/contracts/test_subagent_contracts.py`

- [ ] Remove `SubagentTask.app_id`.
- [ ] Remove `app_id` from `SubagentService.spawn()`.
- [ ] Resolve child assets by `agent_id`.
- [ ] Preserve fallback behavior: unknown requested child agent falls back to parent agent through `AgentRegistry`, and `main` remains the final router default.
- [ ] Remove app checks in self-improve review terminal task matching.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/test_subagent_service.py tests/test_subagent_runtime_loop.py tests/tools/test_subagent_tools.py tests/contracts/test_subagent_contracts.py -q
```

- [ ] Commit:

```bash
git add src/marten_runtime/subagents src/marten_runtime/tools/builtins/spawn_subagent_tool.py tests/test_subagent_service.py tests/test_subagent_runtime_loop.py tests/tools/test_subagent_tools.py tests/contracts/test_subagent_contracts.py
git commit -m "Remove app id from subagent tasks"
```

### Task 7: Automation use agent_id only

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/automation/models.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/automation/dispatch.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/automation/sqlite_store.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/automation_tool_support.py`
- Modify automation tests.
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/config/automations.toml` if any job contains app fields.

- [ ] Remove `AutomationJob.app_id` and `AutomationDispatch.app_id`.
- [ ] Remove `app_id` from registration required fields and alias handling.
- [ ] Keep SQLite migration tolerant of existing `app_id` column by ignoring it when present.
- [ ] For existing SQLite DBs, support both schemas: read old rows with `app_id`, write new rows without depending on `app_id`.
- [ ] Remove `app_id` from semantic fingerprint.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/test_automation_store.py tests/tools/test_automation_tool.py tests/runtime_loop/test_automation_and_trending_routes.py tests/contracts/test_runtime_contracts.py -q
```

- [ ] Commit:

```bash
git add src/marten_runtime/automation src/marten_runtime/tools/builtins/automation_tool_support.py tests/test_automation_store.py tests/tools/test_automation_tool.py tests/runtime_loop/test_automation_and_trending_routes.py tests/contracts/test_runtime_contracts.py
git commit -m "Remove app id from automation jobs"
```

## Chunk 4: Remove App Package and Documentation

### Task 8: Delete app package and references

**Files:**
- Delete: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/apps/bootstrap_prompt.py`
- Delete: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/apps/manifest.py`
- Delete: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/apps/runtime_defaults.py`
- Modify imports throughout `/Users/litiezhu/workspace/github/marten-runtime/src/` and `/Users/litiezhu/workspace/github/marten-runtime/tests/`

- [ ] Run grep:

```bash
grep -R "marten_runtime.apps\|app_id\|AppManifest\|load_app\|apps/" -n src tests config README.md docs | grep -v "FEISHU_APP_ID" | grep -v "channels/feishu" | grep -v "docs/archive/" | grep -v "docs/superpowers/plans/"
```

- [ ] Remove or rename each surviving runtime-app reference.
- [ ] Rewrite `tests/test_bootstrap_prompt.py` around `marten_runtime.agents.assets.load_agent_system_prompt`.
- [ ] Update `tests/http_app_support.py` to copy `agents/` into temporary repos.
- [ ] Update `tests/test_acceptance.py` helper repos to create `agents/main` and `agents/coding` asset roots.
- [ ] Keep historical archive docs unchanged only under `docs/archive/`.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/test_agent_specs.py tests/contracts/test_runtime_contracts.py -q
```

- [ ] Commit:

```bash
git add src tests
git rm -r src/marten_runtime/apps
git commit -m "Delete app runtime package"
```

### Task 9: Update docs

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/README.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/CONFIG_SURFACES.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/README.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/ARCHITECTURE_EVOLUTION.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/DEPLOYMENT.md`

- [ ] Replace current active docs from `app` to `agent asset root`.
- [ ] Update `README.md` reading path and config descriptions.
- [ ] Update `docs/CONFIG_SURFACES.md` tables.
- [ ] Update `docs/DEPLOYMENT.md` deployment file list.
- [ ] In `docs/ARCHITECTURE_EVOLUTION.md`, mark older app references as historical and add the current agent-owned asset model.
- [ ] Add changelog entry: runtime app abstraction removed; agents own assets directly.
- [ ] Run grep again and verify only historical mentions remain.
- [ ] Commit:

```bash
git add README.md docs
git commit -m "Document agent-owned runtime assets"
```

## Chunk 5: Full Verification

### Task 10: Run focused and broad test suites

- [ ] Run focused tests:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/test_bootstrap_prompt.py tests/test_agent_specs.py tests/test_router.py tests/contracts/test_runtime_contracts.py -q
```

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest \
  tests/test_agent_specs.py \
  tests/contracts/test_runtime_contracts.py \
  tests/test_http_runtime_diagnostics.py \
  tests/test_acceptance.py \
  tests/evals/test_executor.py \
  tests/test_subagent_service.py \
  tests/tools/test_subagent_tools.py \
  tests/test_automation_store.py \
  tests/tools/test_automation_tool.py \
  tests/test_bootstrap_prompt.py \
  tests/test_router.py \
  -q
```

- [ ] Run full suite:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest -q
```

- [ ] Run static reference check:

```bash
grep -R "marten_runtime.apps\|AppManifest\|load_app_runtimes\|apps/<app_id>\|apps/main_agent\|app_id" -n src tests config README.md docs | grep -v "FEISHU_APP_ID" | grep -v "channels/feishu" | grep -v "docs/archive/" | grep -v "docs/superpowers/plans/"
```

Expected: no active runtime app references.



### Task 11: Run eval gates for main chain and delegation

- [ ] Verify eval CLI still loads suites after `apps/` removal:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python scripts/run_eval.py --list-suites
```

Expected: includes `main_chain_core`, `main_chain_subagent`, `subagent_task_progress`, and `memory_long_horizon`.

- [ ] Run scripted evals that exercise bootstrap prompt, main routing, session state, memory, and subagent surfaces:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python scripts/run_eval.py --suite main_chain_core --mode scripted --profile openai_gpt_5_4 --db-path /tmp/marten-app-removal-evals.sqlite3 --report-root /tmp/marten-app-removal-reports
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python scripts/run_eval.py --suite main_chain_subagent --mode scripted --profile openai_gpt_5_4 --db-path /tmp/marten-app-removal-evals.sqlite3 --report-root /tmp/marten-app-removal-reports
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python scripts/run_eval.py --suite memory_long_horizon --mode scripted --profile openai_gpt_5_4 --db-path /tmp/marten-app-removal-evals.sqlite3 --report-root /tmp/marten-app-removal-reports
```

Expected: each command exits `0` and prints `status=passed`.

- [ ] Run live evals when provider credentials are present:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python scripts/run_eval.py --suite main_chain_core --mode live --profile openai_gpt_5_4 --db-path /tmp/marten-app-removal-live-evals.sqlite3 --report-root /tmp/marten-app-removal-live-reports
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python scripts/run_eval.py --suite main_chain_subagent --mode live --profile openai_gpt_5_4 --db-path /tmp/marten-app-removal-live-evals.sqlite3 --report-root /tmp/marten-app-removal-live-reports
```

Expected: each command exits `0` and prints `status=passed`. A dependency block is acceptable only when the report says a provider or MCP credential is missing.

### Task 12: Run local HTTP smoke against the active runtime path

- [ ] Start the runtime:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m uvicorn marten_runtime.interfaces.http.app:create_app --factory --host 127.0.0.1 --port 8000
```

- [ ] Verify health and runtime diagnostics:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

Expected: `/healthz` returns `{"status":"ok"}`; diagnostics includes `default_agent_id = main`, provider info, tool registry info, and no runtime `app_id` field.

- [ ] Verify main-agent `/messages` path:

```bash
curl -sS -X POST http://127.0.0.1:8000/messages \
  -H 'content-type: application/json' \
  -d '{"channel_id":"http","user_id":"smoke-user","conversation_id":"smoke-main","message_id":"smoke-main-1","body":"用一句中文说明当前默认 agent 是谁。"}'
```

Expected: response has `status=accepted`, a non-empty `final_text`, and one final run id in `events`.

- [ ] Verify explicit agent routing still works:

```bash
curl -sS -X POST http://127.0.0.1:8000/messages \
  -H 'content-type: application/json' \
  -d '{"channel_id":"http","user_id":"smoke-user","conversation_id":"smoke-coding","message_id":"smoke-coding-1","requested_agent_id":"coding","body":"确认你正在按 coding agent 的工具权限运行。"}'
```

Expected: response has `status=accepted`; `/diagnostics/run/{run_id}` shows `agent_id = coding` and prompt manifest generated from the coding agent.

### Task 13: Run real Feishu verification

Use the existing operator checklist in `/Users/litiezhu/workspace/github/marten-runtime/docs/LIVE_VERIFICATION_CHECKLIST.md`.

- [ ] Start runtime with live `.env` and Feishu websocket enabled.
- [ ] Confirm `GET /diagnostics/runtime` reports Feishu websocket connected.
- [ ] Confirm diagnostics still reports `default_agent_id = main` and no runtime `app_id` field.
- [ ] From a real Feishu DM or fixed verification chat, send the main-chain prompt:

```text
请先告诉我现在的北京时间，再用 GitHub MCP 查询 tiezhuli001/codex-skills 最近一次提交时间，最后合并成一句中文回复。
```

Expected path: `Feishu -> main agent -> time -> mcp -> Feishu`.

- [ ] From the same real Feishu chat, send the subagent prompt:

```text
开启子代理查询 https://github.com/tiezhuli001/codex-skills 最近一次提交是什么时候
```

Expected path: `Feishu -> main agent -> spawn_subagent -> child agent -> GitHub MCP -> parent summary -> Feishu completion notice`.

- [ ] Capture evidence:
  - Feishu visible reply text or screenshot
  - `GET /diagnostics/runtime`
  - `GET /diagnostics/run/{run_id}` for parent runs
  - `GET /diagnostics/subagents`
  - `GET /diagnostics/subagent/{task_id}` for child task
  - `GET /diagnostics/trace/{trace_id}`

- [ ] Acceptance criteria:
  - `dead_letter.count = 0`
  - exactly one visible final reply for the main-chain prompt
  - subagent completion notice appears once
  - final replies contain no internal runtime metadata
  - Feishu card rendering still works
  - parent run uses `agent_id = main`
  - child run uses the requested child agent id or configured fallback agent id

- [ ] Final commit for missed test/doc fixes only:

```bash
git add .
git commit -m "Verify app abstraction removal"
```
