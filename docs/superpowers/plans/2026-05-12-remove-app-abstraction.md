# Remove App Abstraction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `app` as a first-class runtime concept and make `agent` own prompt assets, tool policy, model profile, and runtime identity.

**Architecture:** Replace `apps/<app_id>/app.toml` with agent-owned asset roots declared in `config/agents.toml`. Keep existing persisted `bootstrap_manifest_id` field as a compatibility field, but generate it from `agent_id + prompt_mode`. Keep Feishu `FEISHU_APP_ID` untouched because it is an external platform credential name.

**Tech Stack:** Python, Pydantic, FastAPI, SQLite stores, pytest.

---

## File Map

- Move: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/*` -> `/Users/litiezhu/workspace/github/marten-runtime/agents/main/*`
- Delete: `/Users/litiezhu/workspace/github/marten-runtime/apps/main_agent/app.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/defaults.py`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/assets.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/agents/specs.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/config/agents_loader.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime_support.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_handlers.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/app.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/runtime_diagnostics.py`
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
- Modify docs: `/Users/litiezhu/workspace/github/marten-runtime/README.md`, `/Users/litiezhu/workspace/github/marten-runtime/docs/CONFIG_SURFACES.md`, `/Users/litiezhu/workspace/github/marten-runtime/docs/README.md`

## Guardrails

- Preserve runtime path: channel -> binding -> agent -> runtime loop -> tools -> delivery.
- Preserve session/history `bootstrap_manifest_id` DB column name for compatibility.
- Remove `app_id` from public runtime diagnostics, agent specs, subagent tasks, automation jobs, and LLM request metadata.
- Do not touch Feishu environment variable names: `FEISHU_APP_ID` and `FEISHU_APP_SECRET`.
- Commit after each task.

## Chunk 1: Agent Assets Replace App Manifest

### Task 1: Add failing tests for agent-owned assets

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_agent_specs.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/contracts/test_runtime_contracts.py`

- [ ] Add tests asserting `load_agent_specs()` reads `asset_root` and ignores legacy `app_id`.
- [ ] Add runtime contract asserting `runtime.default_agent.agent_id == "main"`, `runtime.agent_runtimes["main"].prompt_manifest_id == "agent_main_full"`, and no `runtime.app_manifest` attribute.
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
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/config/agents_loader.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap_runtime_support.py`

- [ ] Add `DEFAULT_AGENT_ID = "main"` and `DEFAULT_AGENT_ASSET_ROOT = "agents/main"`.
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

- [ ] Replace `app_manifest` state field with direct `default_agent` and `agent_runtimes`.
- [ ] Replace `state.app_runtimes[...]` with `state.agent_runtimes[agent.agent_id]`.
- [ ] Replace session bootstrap manifest values with `agent_runtime.prompt_manifest_id`.
- [ ] Remove `app_id` from runtime diagnostics JSON.
- [ ] Keep response/session metadata `agent_id`, `model_profile_name`, and `bootstrap_manifest_id`.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/contracts/test_runtime_contracts.py tests/test_http_runtime_diagnostics.py tests/test_acceptance.py -q
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
- Modify related tests containing `LLMRequest(... app_id=...)`

- [ ] Remove `LLMRequest.app_id`.
- [ ] Remove `app_id` from Langfuse/runtime metadata.
- [ ] Remove `app_id` argument from session title summary and self-improve judge request construction.
- [ ] Run:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest tests/test_llm_client.py tests/test_llm_message_support.py tests/runtime_loop -q
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

- [ ] Remove `AutomationJob.app_id` and `AutomationDispatch.app_id`.
- [ ] Remove `app_id` from registration required fields and alias handling.
- [ ] Keep SQLite migration tolerant of existing `app_id` column by ignoring it when present.
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
grep -R "marten_runtime.apps\|app_id\|AppManifest\|load_app\|apps/" -n src tests config README.md docs | grep -v "FEISHU_APP_ID"
```

- [ ] Remove or rename each surviving runtime-app reference.
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

- [ ] Replace current active docs from `app` to `agent asset root`.
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
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest \
  tests/test_agent_specs.py \
  tests/contracts/test_runtime_contracts.py \
  tests/test_http_runtime_diagnostics.py \
  tests/test_acceptance.py \
  tests/test_subagent_service.py \
  tests/tools/test_subagent_tools.py \
  tests/test_automation_store.py \
  tests/tools/test_automation_tool.py \
  -q
```

- [ ] Run full suite:

```bash
PYTHONPATH=src /tmp/marten-runtime-py313-verify/bin/python -m pytest -q
```

- [ ] Run static reference check:

```bash
grep -R "marten_runtime.apps\|AppManifest\|load_app_runtimes\|apps/<app_id>\|apps/main_agent\|app_id" -n src tests config README.md docs | grep -v "FEISHU_APP_ID" | grep -v "docs/archive/"
```

Expected: no active runtime app references.

- [ ] Final commit for missed test/doc fixes only:

```bash
git add .
git commit -m "Verify app abstraction removal"
```
