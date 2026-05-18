# Challenge Eval Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build challenge eval suites that measure iteration gains through component scoring, baseline delta, token/tool/retry delta, and live-chain stability.

**Architecture:** Keep existing gate eval suites as regression gates. Add `challenge_*` suites, a generic declarative challenge grader, targeted case fixtures, and report enhancements. Runtime behavior remains LLM-first: the eval harness observes final text, tool calls, diagnostics, memory, subagent records, skill loading, and token usage.

**Tech Stack:** Python 3.12, unittest, TOML eval manifests, SQLite eval store, existing `marten_runtime.evals` runner/report stack.

---

## Source Design

Primary design document:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-05-17-challenge-eval-design.md`

This plan implements the design in phased slices. Each phase has a concrete completion definition and tests.

## Global Boundaries

- Preserve current gate suites and their pass criteria.
- Keep model intent, tool selection, skill choice, MCP choice, and subagent choice inside the LLM path.
- Keep eval code focused on declarations, execution, observation, scoring, comparison, and reporting.
- Use structured checks first: anchor groups, required/forbidden text, tool call evidence, diagnostics, token/tool/round counts.
- First version uses absolute efficiency thresholds inside case grader. Compare/report displays token, tool-call, and LLM-round deltas; baseline-relative efficiency scoring stays out of the single-case grader.
- MCP quality evaluation uses live mode.
- Skill evaluation lives inside `challenge_integrated`.
- Avoid case-specific semantic branching in Python. Put case semantics in TOML `grader_case`.

## File Map

### New files

- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
  - Generic declarative challenge grader.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`
  - Unit tests for challenge components.
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_memory.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_mcp.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_subagent.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_integrated.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/*.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/*.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_subagent/*.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_integrated/*.toml`
- Optional fixtures under `/Users/litiezhu/workspace/github/marten-runtime/evals/fixtures/memory/`

### Modified files

- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/grader_registry.py`
  - Register `challenge` grader.
- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/compare.py`
  - Add token/tool/LLM round delta helpers for challenge compare.
- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/report_markdown.py`
  - Render Challenge Delta section for `challenge_*` suites.
- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/report_html.py`
  - Mirror Challenge Delta in HTML when present.
- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/scripted_runtime.py`
  - Add scripted replies only for `challenge_memory` and `challenge_subagent` deterministic cases.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_grader_registry.py`
  - Assert challenge grader is registered.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`
  - Assert challenge suites load and have expected cases.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_run_eval_script.py`
  - Assert live-only challenge suites reject scripted mode and missing deps are blocked.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_compare.py`
  - Assert challenge deltas include token/tool/round changes.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_report.py`
  - Assert Challenge Delta appears in reports.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`
  - Assert scripted challenge suites run and collect component summary.
- `/Users/litiezhu/workspace/github/marten-runtime/docs/README.md`
  - Add challenge eval operator entry.
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-05-17-challenge-eval-design.md`
  - Update status after implementation.

---

## Chunk 1: Challenge Grader Foundation

### Task 1.1: Register a generic challenge grader

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/grader_registry.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_grader_registry.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`

- [ ] Step 1: Add failing registry test.

```python
def test_registry_resolves_challenge_grader(self) -> None:
    case = EvalCaseSpec(
        case_id="challenge_sample",
        suite_id="challenge_memory",
        family="challenge",
        grader_id="challenge",
        description="sample",
        agent_id="main",
        profile_name="openai_gpt_5_4",
        turns=[EvalTurnSpec(role="user", content="test")],
        component_weights={"task_success": 100},
        gate_components=["task_success"],
    )
    grader = resolve_case_grader(case)
    self.assertEqual(grader.__name__, "grade_challenge_case_result")
```

Run:

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v tests.evals.test_grader_registry.EvalGraderRegistryTests.test_registry_resolves_challenge_grader
```

Expected: FAIL because `challenge` is unregistered.

- [ ] Step 2: Create minimal `grade_challenge_case_result` returning component scores from `component_weights`.

Initial behavior:

- A component with no rules passes with ratio `1.0` only for test scaffolding.
- Blocked observations use existing `build_blocked_result`.
- Result uses `finalize_component_case_result`.

- [ ] Step 3: Register `challenge` in `_REGISTRY`.

- [ ] Step 4: Run registry test.

Expected: PASS.

### Task 1.2: Implement declarative text component checks

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`

Supported component keys:

- `task_success`
- `reasoning_quality`

TOML shape:

```toml
[grader_case.task_success]
contains_all = ["SQLite"]
contains_any = ["memory", "记忆"]
forbid_all = ["无法确认"]
anchor_groups = [["scope", "隔离"]]
```

- [ ] Step 1: Add failing tests:
  - `test_challenge_grader_scores_text_anchor_components`
  - `test_challenge_grader_partial_score_when_one_component_fails`

Expected behavior:

- `contains_all` checks final text and evidence texts.
- `contains_any` passes when one token appears.
- `forbid_all` fails when forbidden token appears.
- `anchor_groups` uses existing `evaluate_text_evidence`.
- Each component gets its own `EvalComponentScore`.

- [ ] Step 2: Implement helper:

```python
def _grade_text_component(
    key: str,
    label: str,
    weight: int,
    rules: dict[str, object],
    final_text: str,
    evidence_texts: list[str],
) -> EvalComponentScore:
    ...
```

- [ ] Step 3: Run tests.

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v tests.evals.test_challenge_family_grader
```

Expected: PASS.

### Task 1.3: Implement tool path component checks

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`

Supported component key:

- `tool_path_quality`

TOML shape:

```toml
[grader_case.tool_path_quality]
required_tools = ["memory"]
forbidden_tools = ["spawn_subagent"]
min_tool_calls = 1
max_tool_calls = 3
required_skill_ids = ["long-run-execution"]
forbidden_skill_ids = ["code-review"]
```

- [ ] Step 1: Add failing tests:
  - required tool passes.
  - forbidden tool fails.
  - min/max tool call thresholds work.
  - required skill loading checks `tool_name == "skill"` and payload/result `skill_id`.
  - forbidden skill loading catches unnecessary skill load.

- [ ] Step 2: Implement helper:

```python
def _grade_tool_path_component(...):
    tool_names = [...]
    skill_ids = _extract_skill_ids(tool_calls)
    ...
```

- [ ] Step 3: Run tests.

Expected: PASS.

### Task 1.4: Implement state continuity checks

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`

Supported component key:

- `state_continuity`

TOML shape:

```toml
[grader_case.state_continuity]
required_memory_sections = ["preferences"]
forbidden_memory_tokens = ["old-style"]
required_subagent_labels = ["repo-investigation"]
require_subagent_completion = true
required_skill_ids = ["long-run-execution"]
```

Evidence sources:

- memory tool payload/result.
- diagnostics memory fields when available.
- subagent diagnostics tasks.
- skill tool payload/result.
- parent session history when available.

- [ ] Step 1: Add failing tests for memory, subagent, and skill continuity.

- [ ] Step 2: Implement helper functions:

```python
def _memory_evidence_texts(tool_calls, diagnostics): ...
def _subagent_tasks(diagnostics): ...
def _skill_ids(tool_calls): ...
```

- [ ] Step 3: Run tests.

Expected: PASS.

### Task 1.5: Implement efficiency checks

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`

Supported component key:

- `efficiency`

TOML shape:

```toml
[grader_case.efficiency]
max_llm_requests = 4
max_tool_calls = 5
max_total_tokens = 18000
max_repair_attempts = 1
allow_failover = false
```

- [ ] Step 1: Add failing tests for each threshold.

- [ ] Step 2: Implement helper:

```python
def _extract_total_tokens(diagnostics_json: dict[str, object]) -> float | None:
    ...
```

Use same extraction keys as compare where possible.

- [ ] Step 3: Implement retry/repair extraction from diagnostics using permissive count discovery:

Accepted fields to inspect:

- `contract_repair_count`
- `repair_attempts`
- turn run fields with repair markers

- [ ] Step 4: Run tests.

Expected: PASS.

### Completion Definition for Chunk 1

- `challenge` grader registered.
- Unit tests cover text, tool path, state continuity, efficiency.
- Grader reads case semantics from TOML `grader_case`.
- No runtime behavior changed.

Verification:

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v \
  tests.evals.test_grader_registry \
  tests.evals.test_challenge_family_grader
```

---

## Chunk 2: Suite Manifests and Loader Coverage

### Task 2.1: Add challenge suite manifests

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_memory.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_mcp.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_subagent.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_integrated.toml`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`

Suite contract:

```toml
suite_id = "challenge_memory"
grader_id = "challenge"
description = "Challenge eval for scoped memory quality and regression sensitivity"
default_mode = "scripted"
scripted_supported = true
required_dependencies = []
baseline_policy = "latest_passed_auto"
case_files = []
```

Mode rules:

- `challenge_memory`: `default_mode = "scripted"`, `scripted_supported = true`, deps `[]`.
- `challenge_subagent`: `default_mode = "scripted"`, `scripted_supported = true`, deps `subagent`. Current dependency check skips dependency validation for scripted mode, so this still supports scripted harness runs while live mode validates the subagent surface.
- `challenge_mcp`: `default_mode = "live"`, `scripted_supported = false`, deps `provider`, `mcp`.
- `challenge_integrated`: `default_mode = "live"`, `scripted_supported = false`, deps `provider`, `mcp`, `subagent`.

- [ ] Step 1: Add failing manifest test expecting all four suite IDs.

- [ ] Step 2: Create suite manifests with one placeholder disabled smoke case only if the loader rejects empty suites; otherwise keep `case_files = []` during this task. Prefer empty suites when current loader accepts them.

- [ ] Step 3: Run manifest test.

Expected: PASS.

### Task 2.2: Add live-only scripted rejection tests

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_run_eval_script.py`

- [ ] Step 1: Add failing tests:
  - `test_run_eval_rejects_scripted_mode_for_live_only_challenge_mcp_suite`
  - `test_run_eval_rejects_scripted_mode_for_live_only_challenge_integrated_suite`

- [ ] Step 2: Existing service logic should pass. If it fails, fix suite manifests.

- [ ] Step 3: Run tests.

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v tests.evals.test_run_eval_script.RunEvalScriptTests.test_run_eval_rejects_scripted_mode_for_live_only_challenge_mcp_suite tests.evals.test_run_eval_script.RunEvalScriptTests.test_run_eval_rejects_scripted_mode_for_live_only_challenge_integrated_suite
```

Expected: PASS.

### Completion Definition for Chunk 2

- `--list-suites` shows all `challenge_*` suites.
- All manifests load.
- Live-only challenge suites reject scripted mode quickly.
- No cases added yet.

Verification:

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v \
  tests.evals.test_suite_manifests \
  tests.evals.test_run_eval_script
```

---

## Chunk 3: Challenge Compare and Report Delta

### Task 3.1: Add token/tool/round delta to compare output

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/compare.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/models.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_compare.py`

Model addition:

```python
class EvalRunComparison(BaseModel):
    ...
    token_total_delta: float | None = None
    tool_calls_delta: float | None = None
    llm_requests_delta: float | None = None
```

Boundary: these fields are diagnostic deltas for reports. They must not change `total_score`, `pass_rate`, or case status in the first version.

- [ ] Step 1: Add failing test comparing two runs where current has lower tokens/tool calls.

Expected:

- `token_total_delta` is current minus baseline.
- `tool_calls_delta` is current suite total minus baseline suite total.
- `llm_requests_delta` follows the same suite-total convention.

- [ ] Step 2: Implement helpers:

```python
def _sum_case_tokens(cases: list[EvalCaseResult]) -> float | None: ...
def _sum_tool_calls(cases: list[EvalCaseResult]) -> float: ...
def _sum_llm_requests(cases: list[EvalCaseResult]) -> float: ...
```

- [ ] Step 3: Run compare tests.

Expected: PASS.

### Task 3.2: Render Challenge Delta in Markdown and HTML

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/report_markdown.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/report_html.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_report.py`

- [ ] Step 1: Add failing report test for a `challenge_memory` summary with compare result.

Expected Markdown section:

```markdown
## Challenge Delta

- Total score delta: ...
- Token delta: ...
- Tool call delta: ...
- LLM request delta: ...
```

Expected HTML contains `Challenge Delta`.

- [ ] Step 2: Implement conditional render when `suite_id.startswith("challenge_")` and compare result exists.

- [ ] Step 3: Run report tests.

Expected: PASS.

### Completion Definition for Chunk 3

- Baseline comparison exposes token/tool/round deltas.
- Challenge reports highlight deltas.
- Existing report structure remains stable for gate suites.

Verification:

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v \
  tests.evals.test_compare \
  tests.evals.test_report
```

---

## Chunk 4: Memory Challenge Cases

### Task 4.1: Add memory challenge case files

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_interference_recall_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_scope_isolation_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_overwrite_conflict_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_should_not_write_cn.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_memory.toml`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`

Shared case shape:

```toml
case_id = "memory_interference_recall_cn"
suite_id = "challenge_memory"
family = "challenge"
grader_id = "challenge"
enabled = true
required = true
description = "Recall durable preference after interference turns"
agent_id = "main"
profile_name = "openai_gpt_5_4"
tags = ["challenge", "memory"]

[[turns]]
role = "user"
content = "..."

[component_weights]
task_success = 35
reasoning_quality = 20
tool_path_quality = 20
state_continuity = 15
efficiency = 10

gate_components = ["task_success", "tool_path_quality"]
```

- [ ] Step 1: Add failing manifest test for 4 challenge memory cases.

- [ ] Step 2: Create four TOML cases with concrete `grader_case` sections.

- [ ] Step 3: Add case paths to `challenge_memory.toml`.

- [ ] Step 4: Run manifest tests.

Expected: PASS.

### Task 4.2: Add scripted runtime support for memory challenge

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/scripted_runtime.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`

Boundary:

- Scripted support creates deterministic model behavior for harness validation.
- Scripted support should not fake MCP quality.
- Keep case logic narrow and grouped by `challenge_memory` cases.

- [ ] Step 1: Add failing executor test:

```python
def test_execute_suite_scripted_challenge_memory_collects_component_summary(self) -> None:
    ...
```

Expected:

- suite runs in scripted mode.
- at least one case has component breakdown keys.
- score is recorded.

- [ ] Step 2: Add scripted replies for four memory challenge cases.

Implementation pattern:

- Use memory tool for write/replace cases.
- Use final text anchors from case TOML.
- For should-not-write case, answer without memory tool.

- [ ] Step 3: Run executor test.

Expected: PASS.

### Task 4.3: Run memory challenge eval twice for baseline delta

**Files:**
- No source changes unless failures reveal fixture defects.

Commands:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py \
  --suite challenge_memory \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --report-root reports/evals \
  --db-path data/evals.sqlite3

PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py \
  --suite challenge_memory \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --report-root reports/evals \
  --db-path data/evals.sqlite3
```

Expected:

- both runs finish.
- second run has compare result.
- stability sample size is at least 2.
- component summary appears.

### Completion Definition for Chunk 4

- `challenge_memory` has 4 cases.
- Scripted mode runs.
- Component summary and compare data are present.
- Grader can represent success, partial score, and failure through tests.

Verification:

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v \
  tests.evals.test_suite_manifests \
  tests.evals.test_executor \
  tests.evals.test_challenge_family_grader
```

---

## Chunk 5: MCP Challenge Cases

### Task 5.1: Add live-only MCP challenge cases

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/mcp_multi_turn_repo_investigation_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/mcp_result_synthesis_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/mcp_recovery_after_empty_result_cn.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_mcp.toml`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_run_eval_script.py`

Boundary:

- `challenge_mcp` is live-only.
- Case prompts must target stable repository facts in this repo or a durable public GitHub target.
- Avoid time-sensitive wording such as “latest” unless the case explicitly validates current live data.

- [ ] Step 1: Add manifest test expecting 3 MCP challenge cases.

- [ ] Step 2: Create TOML cases. Keep `required_dependencies = ["provider", "mcp"]` in `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_mcp.toml`, not in case files.

- [ ] Step 3: Add blocked dependency test for missing MCP config.

- [ ] Step 4: Run manifest and run_eval script tests.

Expected: PASS.

### Task 5.2: Live run MCP challenge

Command:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py \
  --suite challenge_mcp \
  --mode live \
  --profile openai_gpt_5_4 \
  --report-root reports/evals \
  --db-path data/evals.sqlite3 \
  --case-timeout-seconds 180
```

Run at least twice after first successful pass.

Expected:

- Real GitHub MCP server starts.
- Cases finish or produce precise blocked reason.
- token_total is greater than 0.
- stability sample grows.

### Completion Definition for Chunk 5

- `challenge_mcp` is live-only.
- Scripted mode blocks quickly.
- Missing MCP dependency blocks quickly.
- Live run produces token usage and component summary.
- Live MCP case prompts use stable repository facts or explicit live-data wording.

---

## Chunk 6: Subagent Challenge Cases

### Task 6.1: Add subagent challenge cases

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_subagent/subagent_should_delegate_complex_task_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_subagent/subagent_should_stay_main_thread_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_subagent/subagent_multi_child_synthesis_cn.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_subagent.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/scripted_runtime.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`

Boundary:

- `challenge_subagent` scripted mode validates harness and scoring.
- Live mode validates real child behavior.
- Simple task case must forbid `spawn_subagent`.
- Subagent diagnostics collection currently keys off `grader_id == "subagent_task_progress"`; implementation must extend that condition to include challenge cases that declare subagent checks, without changing runtime behavior.

- [ ] Step 1: Add manifest test expecting 3 cases.

- [ ] Step 2: Add scripted runtime responses:
  - complex task uses `spawn_subagent`.
  - simple task returns direct final text.
  - multi child case spawns two distinct labels.

- [ ] Step 3: Add executor test for scripted challenge subagent component summary.

- [ ] Step 4: Run tests.

Expected: PASS.

### Completion Definition for Chunk 6

- `challenge_subagent` has direct, single-child, and multi-child coverage.
- Duplicate dispatch risk is scored through `tool_path_quality` or `state_continuity`.
- Parent integration appears in component details.

---

## Chunk 7: Integrated + Skill Challenge Cases

### Task 7.1: Add integrated live-only cases

**Files:**
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_integrated/integrated_memory_mcp_recall_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_integrated/integrated_subagent_mcp_memory_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_integrated/skill_required_load_and_apply_cn.toml`
- Create: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_integrated/skill_not_needed_stays_unloaded_cn.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_integrated.toml`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_run_eval_script.py`

Boundary:

- `challenge_integrated` is live-only.
- Skill case uses a deterministic local skill with clear constraints.
- Skill required case checks `skill` tool loading and final text constraints.
- Skill not-needed case forbids `skill` tool.
- Integrated subagent cases need subagent diagnostics; extend eval diagnostics collection declaratively by suite/case grader metadata, not by user-message intent.

- [ ] Step 1: Add manifest test expecting 4 integrated cases.

- [ ] Step 2: Add suite dependencies: `provider`, `mcp`, `subagent`.

- [ ] Step 3: Create TOML cases.

- [ ] Step 4: Add blocked tests for scripted mode and missing dependencies. For `challenge_integrated`, test missing MCP and missing subagent surface separately because both are declared suite dependencies.

Expected: PASS.

### Task 7.2: Live run integrated challenge

Command:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py \
  --suite challenge_integrated \
  --mode live \
  --profile openai_gpt_5_4 \
  --report-root reports/evals \
  --db-path data/evals.sqlite3 \
  --case-timeout-seconds 240
```

Expected:

- token_total is greater than 0.
- skill required case includes `skill` tool call.
- skill not-needed case has no `skill` tool call.
- integrated MCP cases include real MCP evidence.

### Completion Definition for Chunk 7

- Integrated suite covers memory + MCP + subagent + skill.
- Skill behavior has both positive and negative examples.
- Live-only behavior is enforced.

---

## Chunk 8: Documentation and Operator Entry

### Task 8.1: Update eval docs

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/README.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-05-17-challenge-eval-design.md`

Add:

- Challenge suite list.
- Recommended command sequence.
- Gate vs challenge interpretation.
- Meaning of `token_total = 0` for scripted mode.
- How to interpret 100-point gate suite vs challenge deltas.

- [ ] Step 1: Add docs update.

- [ ] Step 2: Run docs grep check:

```bash
grep -R "challenge_memory\|challenge_mcp\|Challenge Delta" -n docs/README.md docs/2026-05-17-challenge-eval-design.md
```

Expected: entries exist.

### Completion Definition for Chunk 8

- Operator can discover challenge eval from docs.
- Commands are copy-pasteable.
- Interpretation rules are explicit.

---

## Full Verification Matrix

### Unit and contract tests

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v \
  tests.evals.test_challenge_family_grader \
  tests.evals.test_grader_registry \
  tests.evals.test_suite_manifests \
  tests.evals.test_run_eval_script \
  tests.evals.test_compare \
  tests.evals.test_report \
  tests.evals.test_executor
```

### Existing eval regression tests

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v tests.evals
```

### Compile and diff hygiene

```bash
PYTHONPATH=src:. .venv/bin/python -m compileall -q src tests scripts/run_eval.py scripts/migrate_memory_md_to_sqlite.py
git diff --check
```

### Scripted eval runs

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_memory --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_subagent --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
```

### Live eval runs

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_mcp --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 180
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_integrated --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 240
```

### Gate eval safety check

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite main_chain_core --mode scripted --profile openai_gpt_5_4 --baseline latest_passed --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite memory_long_horizon --mode scripted --profile openai_gpt_5_4 --baseline latest_passed --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite subagent_task_progress --mode scripted --profile openai_gpt_5_4 --baseline latest_passed --report-root reports/evals --db-path data/evals.sqlite3
```

---

## Overall Completion Definition

The implementation is complete when all items are true:

1. Four `challenge_*` suites exist and load.
2. `challenge_memory` and `challenge_subagent` run in scripted mode.
3. `challenge_mcp` and `challenge_integrated` are live-only and block scripted mode quickly.
4. Challenge grader supports text, tool path, state continuity, skill trigger, and efficiency components.
5. Reports show component delta plus token/tool/LLM round delta.
6. Skill has one required-load case and one no-load case.
7. At least one scripted challenge suite has two runs with compare and stability data.
8. At least one live challenge suite has two runs with token usage and stability data.
9. Existing gate eval tests remain green.
10. Docs explain how to interpret gate score, challenge score, and token delta.

## Risk Controls

- Keep challenge cases small enough to debug by reading one case file and one report.
- Prefer stable repository facts for live MCP cases.
- Keep live case timeout explicit.
- Put semantic requirements in TOML.
- Keep Python grader generic.
- Treat token improvements as report-level delta in first version.
- Treat LLM judge as future enhancement.
