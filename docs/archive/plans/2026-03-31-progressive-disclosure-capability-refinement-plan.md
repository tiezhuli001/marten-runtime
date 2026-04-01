# Progressive Disclosure Capability Refinement Implementation Plan

> **For agentic workers:** REQUIRED: Use `superpowers:subagent-driven-development` (if subagents are available) or `superpowers:executing-plans` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the existing progressive-disclosure runtime so MCP normalization, skill loading, skill prompt budgeting, capability declaration, and prompt rules all converge on a thinner, more reusable harness shape without reintroducing host-side intent routing.

**Architecture:** Keep the current runtime-visible surface stable at `automation`, `mcp`, `self_improve`, `skill`, and `time`, but refactor the internals into thinner primitives. Move MCP compatibility handling into a dedicated normalization layer, split skill head loading from body loading, add prompt-budgeted skill summary rendering, and centralize capability-family declarations so prompt text, tool descriptions, and diagnostics do not drift.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, unittest, existing `marten-runtime` runtime/tool/skill architecture, real MiniMax OpenAI-compatible model path, MCP stdio client.

---

## Source Of Truth

- Design doc:
  - [2026-03-31-progressive-disclosure-llm-first-capability-design.md](/Users/litiezhu/workspace/github/marten-runtime/docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md)
- External reference research:
  - `/Users/litiezhu/docs/ytsd/工作学习/AI学习/mcp和skill/Skill_MCP渐进披露架构研究报告.md`
- Continuity file:
  - [STATUS.md](/Users/litiezhu/workspace/github/marten-runtime/STATUS.md)

## Hard Constraints

- Do not reintroduce turn-level message classification or host-side intent routing.
- Keep `skills/` as a single-level plugin directory: `skills/<skill_id>/SKILL.md`.
- `mcps.json` remains restart-only. No config hot reload.
- Do not widen automation lifecycle boundaries.
- Do not widen adapter boundaries.
- Do not add a new “framework” layer. Add only thin primitives with clear ownership.
- Keep the runtime-visible tool surface stable unless a specific compatibility fix requires a documented adjustment.
- Every milestone must end with targeted tests before moving to the next milestone.
- Final completion requires fresh full-suite verification plus real local chain validation.

### Additional Constraint For Capability Declaration

The `capability declaration` slice is allowed to solve only static metadata reuse.

Allowed scope:
- tool description reuse
- capability catalog rendering
- optional diagnostics text reuse

Explicitly forbidden:
- runtime routing logic
- permissions engine
- policy branching
- plugin lifecycle management
- dynamic capability registration protocols
- any object graph that turns `capabilities.py` into a new central framework

## Planned Outcome

After this plan is implemented:

1. MCP family payload compatibility lives in one normalization layer instead of `if/else` spread inside the builtin tool.
2. Skill runtime startup reads heads separately from full bodies, so “summary-only” is true at both prompt exposure and file-loading levels.
3. Skill summaries have a bounded prompt budget with a compact fallback format that keeps the harness stable as the number of skills grows.
4. Capability-family metadata is declared once and reused for prompt catalog generation, tool descriptions, and runtime wiring.
5. Bootstrap/app prompt text gives the model explicit progressive-disclosure operating rules similar to OpenClaw/OTTClaw, but adapted to this runtime’s family tools.

## File Map

### Existing files to modify

- [src/marten_runtime/tools/builtins/mcp_tool.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/mcp_tool.py)
  - Remove normalization logic that belongs in a reusable MCP-layer module.
- [src/marten_runtime/interfaces/http/bootstrap.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap.py)
  - Wire capability declarations into tool descriptions and capability catalog assembly.
- [src/marten_runtime/skills/models.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/models.py)
  - Add explicit head/body structures or metadata needed for true lazy loading and prompt budgeting.
- [src/marten_runtime/skills/loader.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/loader.py)
  - Split head loading from full-body loading.
- [src/marten_runtime/skills/render.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/render.py)
  - Add full and compact summary rendering with budget-aware truncation.
- [src/marten_runtime/skills/service.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/service.py)
  - Build runtime view from head-only load path plus explicit always-on body loading.
- [src/marten_runtime/apps/bootstrap_prompt.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/apps/bootstrap_prompt.py)
  - Add stable progressive-disclosure operating rules for skill/mcp usage.
- [tests/test_runtime_mcp.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py)
  - Add focused regression tests around the new normalizer layer.
- [tests/test_skills.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_skills.py)
  - Add coverage for head-only loading and budget fallback behavior.
- [tests/test_bootstrap_prompt.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_bootstrap_prompt.py)
  - Add prompt-rule assertions so the usage contract cannot drift.
- [tests/test_contract_compatibility.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py)
  - Freeze the runtime-visible surface and capability catalog expectations.

### New files to create

- [src/marten_runtime/mcp/normalize.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/mcp/normalize.py)
  - MCP payload normalization entrypoint and normalization helpers.
- [src/marten_runtime/mcp/request_models.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/mcp/request_models.py)
  - Pydantic request models or dataclasses for normalized MCP requests.
- [src/marten_runtime/runtime/capabilities.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/capabilities.py)
  - Thin capability-family declaration model plus render helpers.
- [tests/test_runtime_capabilities.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_capabilities.py)
  - Unit tests for capability declaration rendering and description stability.

### Files to inspect during implementation

- [src/marten_runtime/runtime/context.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/context.py)
- [src/marten_runtime/runtime/llm_client.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py)
- [apps/example_assistant/BOOTSTRAP.md](/Users/litiezhu/workspace/github/marten-runtime/apps/example_assistant/BOOTSTRAP.md)
- [tests/test_runtime_loop.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py)

## Chunk 1: MCP Normalize Layer

### Task 1: Introduce a dedicated normalized MCP request model

**Files:**
- Create: [src/marten_runtime/mcp/request_models.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/mcp/request_models.py)
- Test: [tests/test_runtime_mcp.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py)

- [ ] **Step 1: Add a failing unit test that defines the normalized shape**

Add tests that assert a normalized request has exactly these fields:

```python
action: str
server_id: str | None
tool_name: str | None
arguments: dict
```

Cover at least:
- missing `action`
- alias fields `tool`, `name`
- alias fields `params`, `payload`
- empty or missing arguments

- [ ] **Step 2: Run the focused MCP test target and confirm the new tests fail**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_mcp.RuntimeMCPTests -v
```

Expected:
- FAIL because the normalized request model and parser do not exist yet.

- [ ] **Step 3: Create the normalized request model with the smallest stable API**

Implementation requirements:
- prefer a small `BaseModel` or frozen dataclass
- do not embed runtime client logic in this file
- keep it serialization-safe for diagnostics and tests
- use explicit field names, not dynamic dict access

- [ ] **Step 4: Re-run the focused MCP tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_mcp.RuntimeMCPTests -v
```

Expected:
- the new model tests still fail on parser behavior
- the import and model shape tests pass

### Task 2: Move MCP payload compatibility into one normalization entrypoint

**Files:**
- Create: [src/marten_runtime/mcp/normalize.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/mcp/normalize.py)
- Modify: [src/marten_runtime/tools/builtins/mcp_tool.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/mcp_tool.py)
- Test: [tests/test_runtime_mcp.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_mcp.py)

- [ ] **Step 1: Add failing tests for the normalizer**

Add targeted tests for:
- `{"query": "release notes"}` on a single-tool server normalizes to `action="call"`
- `arguments` as JSON string normalizes to dict
- `{"tool": "...", "params": {...}}` maps to canonical fields
- missing `server_id` with a unique tool name infers the correct server
- missing `tool_name` on a single-tool server infers the tool
- unsupported/ambiguous requests still fail with stable `ValueError` messages

- [ ] **Step 2: Run only the new failing tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_mcp.RuntimeMCPTests.test_mcp_family_tool_can_infer_single_tool_server_from_query_payload tests.test_runtime_mcp.RuntimeMCPTests.test_mcp_family_tool_accepts_json_string_arguments -v
```

Expected:
- FAIL if the tests are pointed at the new normalizer entrypoint before implementation.

- [ ] **Step 3: Implement the normalizer**

Implementation rules:
- `normalize_mcp_request(server_map, payload)` returns one normalized request object
- normalization is the only place where provider-shape compatibility is handled
- resolution helpers may use server metadata, but execution must remain outside this file
- if inference is ambiguous, fail fast instead of guessing

Required internal helpers:
- action inference
- control-key alias normalization
- argument normalization
- server inference
- single-tool fallback resolution

- [ ] **Step 4: Refactor `run_mcp_tool` to use the normalizer**

Refactor shape:
- `run_mcp_tool(...)`
  - build `server_map`
  - call `normalize_mcp_request(...)`
  - switch on normalized `action`
  - execute list/detail/call

Rules:
- remove duplicated normalization helpers from `mcp_tool.py` if they are now owned by `normalize.py`
- keep `mcp_tool.py` thin and execution-focused

- [ ] **Step 5: Re-run focused MCP tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_mcp -v
```

Expected:
- PASS for all MCP-family normalization tests
- no regression in real stdio MCP tests

### Task 3: Freeze the new MCP layer contract in compatibility tests

**Files:**
- Modify: [tests/test_contract_compatibility.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py)
- Inspect: [src/marten_runtime/interfaces/http/bootstrap.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap.py)

- [ ] **Step 1: Add a failing compatibility test**

Assert:
- assistant default tools still equal `["automation", "mcp", "self_improve", "skill", "time"]`
- MCP family tool remains the only model-visible MCP entrypoint

- [ ] **Step 2: Run the narrow compatibility target**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_contract_compatibility -v
```

Expected:
- PASS if no compatibility drift occurred
- otherwise fix drift before proceeding

## Chunk 2: True Lazy Skill Loading

### Task 4: Split skill head loading from skill body loading

**Files:**
- Modify: [src/marten_runtime/skills/models.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/models.py)
- Modify: [src/marten_runtime/skills/loader.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/loader.py)
- Modify: [tests/test_skills.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_skills.py)

- [ ] **Step 1: Add failing tests that distinguish head loading from body loading**

Add tests for:
- `load_all()` returns heads with `body is None`
- `load_skill()` returns full body
- head loading does not require a full-body parse path
- always-on bodies are still loaded only through an explicit body load step

If needed, instrument with a small temporary parser seam in tests so the implementation must actually separate the paths.

- [ ] **Step 2: Run the skills test target and confirm failure**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_skills -v
```

Expected:
- FAIL on the newly added assertions if the loader still reads through one path.

- [ ] **Step 3: Add explicit head/body parse helpers**

Implementation requirements:
- keep front matter parsing compatible with current `SKILL.md` format
- avoid widening metadata semantics
- expose one clear helper for “head-only parse” and one for “full parse”
- do not change the single-level `skills/` directory contract

- [ ] **Step 4: Refactor `SkillLoader` to use the split parse path**

Target shape:
- `load_all()` calls head-only read/parse
- `load_skill(skill_id)` calls full-body read/parse
- duplicate parsing logic lives in one place, not two copies

- [ ] **Step 5: Re-run skills tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_skills -v
```

Expected:
- PASS

### Task 5: Keep runtime assembly summary-only while preserving explicit always-on loading

**Files:**
- Modify: [src/marten_runtime/skills/service.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/service.py)
- Modify: [tests/test_skills.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_skills.py)
- Inspect: [src/marten_runtime/tools/builtins/skill_tool.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/skill_tool.py)

- [ ] **Step 1: Add a failing runtime-view test**

Assert:
- visible runtime skills remain head-only
- always-on skills are body-loaded explicitly and only for always-on render/export
- `skill(action=load)` still returns the same payload contract

- [ ] **Step 2: Run the focused skill-service tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_skills.SkillTests.test_skill_service_builds_startup_snapshot_and_loads_always_on_body_explicitly tests.test_runtime_loop.RuntimeLoopTests.test_runtime_can_load_skill_body_via_skill_tool -v
```

Expected:
- FAIL until runtime assembly is adjusted to the new loader split if needed

- [ ] **Step 3: Refactor `SkillService.build_runtime()` minimally**

Rules:
- no selector heuristics
- no extra caching layer unless a benchmark proves it is needed
- do not pre-load non-`always_on` bodies

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_skills tests.test_runtime_loop -v
```

Expected:
- PASS for skill runtime and explicit load behavior

## Chunk 3: Skill Budget Tiers

### Task 6: Add budget-aware skill summary rendering with compact fallback

**Files:**
- Modify: [src/marten_runtime/skills/render.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/render.py)
- Modify: [src/marten_runtime/skills/service.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/skills/service.py)
- Modify: [tests/test_skills.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_skills.py)

- [ ] **Step 1: Add failing tests for tiered summary rendering**

Cover:
- full format when under budget
- compact format when full format exceeds budget
- truncated compact prefix when compact still exceeds budget
- stable ordering and deterministic truncation

- [ ] **Step 2: Run the new render tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_skills -v
```

Expected:
- FAIL until tiered rendering exists

- [ ] **Step 3: Implement the renderer**

Minimum API:
- `render_skill_heads(items, *, max_chars: int, max_items: int) -> RenderedSkillHeads`

Required output data:
- rendered text
- `compact: bool`
- `truncated: bool`
- optional `truncated_reason`

Rules:
- use simple character budgets, not token estimators
- do not add ranking heuristics
- preserve current visible-skill ordering

- [ ] **Step 4: Wire the renderer into `SkillService.build_runtime()`**

Rules:
- keep defaults conservative and documented
- do not make budgets user-message dependent
- keep this a prompt-budget concern only, not an intent-routing mechanism

- [ ] **Step 5: Re-run skill tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_skills -v
```

Expected:
- PASS

## Chunk 4: Capability Declaration

### Task 7: Centralize capability-family declarations

**Files:**
- Create: [src/marten_runtime/runtime/capabilities.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/capabilities.py)
- Modify: [src/marten_runtime/interfaces/http/bootstrap.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/bootstrap.py)
- Create: [tests/test_runtime_capabilities.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_capabilities.py)
- Modify: [tests/test_contract_compatibility.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_contract_compatibility.py)

- [ ] **Step 1: Add failing tests for capability declarations**

Assert:
- capability declarations exist for `automation`, `mcp`, `self_improve`, `skill`, `time`
- the same source can render capability catalog text
- the same source can provide tool descriptions for registration

- [ ] **Step 2: Run the new capability tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_capabilities -v
```

Expected:
- FAIL because the declaration layer does not exist yet

- [ ] **Step 3: Implement the declaration layer**

Data model should include only:
- `name`
- `summary`
- optional `actions`
- optional `usage_rules`

Do not add:
- permissions engine
- routing rules
- plugin marketplace semantics
- registries with runtime mutation
- policy evaluators
- dependency graphs

- [ ] **Step 3.5: Add a structure guard test before wiring bootstrap**

Add a test that freezes the declaration layer to a static, data-only shape.

Assert:
- declarations can be instantiated without a runtime state object
- declarations do not import tool registry, router, session, or channel modules
- the helper module only renders text/metadata and does not execute tools

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_capabilities -v
```

Expected:
- FAIL until the declaration layer stays data-only

- [ ] **Step 4: Refactor bootstrap wiring to use the declaration layer**

Refactor targets:
- tool descriptions passed to `ToolRegistry.register(...)`
- capability catalog text injected into runtime context

Rules:
- runtime-visible tool names must not change
- diagnostics shape should not regress

- [ ] **Step 5: Re-run focused capability and compatibility tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_capabilities tests.test_contract_compatibility -v
```

Expected:
- PASS

## Chunk 5: Prompt Operating Rules

### Task 8: Make the progressive-disclosure usage contract explicit in bootstrap/app prompt

**Files:**
- Modify: [src/marten_runtime/apps/bootstrap_prompt.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/apps/bootstrap_prompt.py)
- Inspect: [apps/example_assistant/BOOTSTRAP.md](/Users/litiezhu/workspace/github/marten-runtime/apps/example_assistant/BOOTSTRAP.md)
- Modify: [tests/test_bootstrap_prompt.py](/Users/litiezhu/workspace/github/marten-runtime/tests/test_bootstrap_prompt.py)

- [ ] **Step 1: Add failing prompt tests**

Assert the prompt explicitly tells the model:
- read visible skill summaries first
- load skill body only when one clearly applies
- avoid loading multiple skills up front
- use `mcp` family progressively instead of assuming all tool detail is already present

- [ ] **Step 2: Run prompt tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_bootstrap_prompt -v
```

Expected:
- FAIL until the prompt rules are added

- [ ] **Step 3: Add a compact, stable prompt section**

Rules:
- keep it behavioral, not verbose
- do not leak internal run ids or operator diagnostics
- do not reference nonexistent tools or legacy per-tool MCP schemas

- [ ] **Step 4: Re-run prompt tests**

Run:

```bash
PYTHONPATH=src python -m unittest tests.test_bootstrap_prompt -v
```

Expected:
- PASS

## Chunk 6: Verification And Real-Chain Validation

### Task 9: Run targeted verification after each implementation chunk

**Files:**
- No code changes required
- Update continuity in [STATUS.md](/Users/litiezhu/workspace/github/marten-runtime/STATUS.md)

- [ ] **Step 1: Run MCP-focused tests**

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_mcp tests.test_contract_compatibility -v
```

Expected:
- PASS

- [ ] **Step 2: Run skill-focused tests**

```bash
PYTHONPATH=src python -m unittest tests.test_skills tests.test_bootstrap_prompt tests.test_runtime_loop -v
```

Expected:
- PASS

- [ ] **Step 3: Run capability-declaration tests**

```bash
PYTHONPATH=src python -m unittest tests.test_runtime_capabilities tests.test_contract_compatibility -v
```

Expected:
- PASS

### Task 10: Run the full regression suite

**Files:**
- No code changes required

- [ ] **Step 1: Run the full suite**

```bash
PYTHONPATH=src python -m unittest -v
```

Expected:
- PASS with no newly introduced failures

- [ ] **Step 2: If the full suite fails, stop and fix before live validation**

Rules:
- do not proceed to real-chain testing on a red suite
- fix only regressions caused by this plan

### Task 11: Re-run live local chain validation on the real service

**Files:**
- No code changes required unless validation reveals a real regression
- Diagnostics endpoints:
  - [src/marten_runtime/interfaces/http/app.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/http/app.py)

- [ ] **Step 1: Restart the local real service**

Use the repo’s existing local run method that produced the verified `127.0.0.1:8061` environment.

Expected:
- service starts cleanly
- Feishu websocket reconnects if credentials are present

- [ ] **Step 2: Verify health and runtime diagnostics**

Run:

```bash
curl -sS http://127.0.0.1:8061/healthz
curl -sS http://127.0.0.1:8061/diagnostics/runtime
```

Expected:
- `{"status":"ok"}`
- tool count remains `5`
- MCP family remains visible as one tool
- Feishu websocket connected if local credentials are present

- [ ] **Step 3: Verify live HTTP probes**

Run probes for:
- plain chat
- `time`
- explicit `mcp` call
- automation summary
- self-improve summary

Expected:
- each returns progress + final
- MCP path succeeds without intermittent normalization regressions

- [ ] **Step 4: Stress-check explicit MCP again**

Run repeated explicit MCP calls, at least `10` times.

Expected:
- no intermittent `TOOL_EXECUTION_FAILED`

- [ ] **Step 5: Re-verify queue serialization**

Send two overlapping requests on the same conversation.

Expected:
- mid-flight diagnostics show a queued item
- second request finishes after the first

- [ ] **Step 6: Re-verify real Feishu path**

At minimum:
- confirm a real inbound Feishu message reaches the latest runtime instance
- confirm the visible reply is coherent
- confirm diagnostics map `last_run_id -> diagnostics/run`

If feasible, also re-run:

```bash
curl -sS -X POST http://127.0.0.1:8061/automations/codex_live_validation_temp/trigger
```

Expected:
- final Feishu delivery succeeds

## Drift Guardrails

During implementation, reject any change that introduces one of these drifts:

- a new message-type router
- a new skill directory hierarchy
- a new dynamic MCP config reload path
- a new generic capability framework with deep abstraction
- a mutable global capability registry
- capability objects that depend on runtime stateful services
- a fallback path that bypasses the `mcp` or `skill` family entrypoints
- multiple incompatible prompt-generation sources for capability descriptions

## Completion Checklist

- [ ] MCP normalization is centralized in one reusable module.
- [ ] `mcp_tool.py` contains execution logic, not compatibility sprawl.
- [ ] Skill loading is truly head-first and body-on-demand.
- [ ] Skill summary rendering has deterministic budget tiers.
- [ ] Capability family metadata is declared once and reused.
- [ ] Prompt rules explicitly teach the model progressive-disclosure behavior.
- [ ] All targeted tests pass.
- [ ] Full suite passes.
- [ ] Real local HTTP chain passes.
- [ ] Real Feishu chain passes.
- [ ] [STATUS.md](/Users/litiezhu/workspace/github/marten-runtime/STATUS.md) is updated with the completed slice and fresh verification evidence.

## Notes For The Implementing Agent

- Keep changes small and sequential. Do not mix multiple chunks into one unverified patch.
- Prefer modifying existing files over introducing new layers unless the new file has one clear responsibility.
- If a live-model payload shape appears that the new MCP normalizer still cannot handle, add one normalization rule and one regression test. Do not spread the fix across runtime/bootstrap/prompt layers.
- If a proposed optimization requires host-side semantic routing, stop. That would violate the source-of-truth constraints.
- If a test needs to prove “head-only” loading, use an observable seam in the parser/loader rather than hand-waving from output shape alone.

Plan complete and saved to `docs/plans/2026-03-31-progressive-disclosure-capability-refinement-plan.md`. Ready to execute.
