# Challenge Hard Cases v1 Execution Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert current `challenge_*` suites from enhanced smoke checks into hard, partially-scored evals that expose marten-runtime quality gaps and show improvement after future runtime upgrades.

**Architecture:** Keep gate eval suites as the health/regression layer. Keep runtime LLM-first: intent, tool choice, skill use, MCP planning, and subagent decisions remain in the model path. The eval harness remains declarative: TOML cases describe hard scenarios; the generic challenge grader scores rubric items, tool evidence, diagnostics, continuity, and efficiency.

**Tech Stack:** Python 3.12, `unittest`, TOML eval manifests, existing `marten_runtime.evals` runner/store/report stack, real GitHub MCP for live MCP quality.

---

## Source Inputs

Primary docs:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-05-17-challenge-eval-design.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-05-17-challenge-eval-execution-plan.md`

Current branch:

- `/Users/litiezhu/workspace/github/marten-runtime`
- Branch: `codex/eval-challenge-assessment-20260517`

Reference direction from user:

- Gate eval is enough for health, tool path, reports, and live dependency smoke.
- Challenge eval should represent real quality assessment and expose known gaps.
- Current challenge suites returning 100 makes them weak.
- Build hard cases inspired by mature assistant patterns: local memory, editability, real tool evidence, subagent isolation/completion, skill loading discipline, multi-step MCP recovery.

## Hard Boundaries

- Do not modify gate suites or their pass criteria.
- Do not add runtime semantic routing, intent hardcode, or host-side tool decision logic.
- Do not use Python case-id branches to decide semantic success. Case semantics belong in TOML `grader_case`.
- Do not fake MCP quality in scripted mode. MCP hard quality remains live-only.
- Keep scripted hard cases for harness/grader validation only.
- Keep all scoring explainable through report JSON component details.
- Expected challenge scores should be below 100 on the current implementation unless runtime genuinely satisfies the hard rubrics. A below-100 score is success when failures map to real unsupported/weak behavior.
- Replace existing simple challenge cases with hard cases. Do not preserve weak challenge cases as separate challenge smoke tests; gate eval already owns smoke/regression coverage.
- Avoid time-sensitive facts such as “latest” unless the case explicitly validates live recency.
- Avoid huge case suites. First version should be hard enough to expose gaps and small enough to debug.

## Target Score Profile

After this plan:

- `challenge_memory` scripted should no longer be designed for 100. Target initial range: `50-85`.
- `challenge_subagent` scripted should no longer be designed for 100. Target initial range: `50-85`.
- `challenge_mcp` live should contain hard cases that may score below 100. Target initial range: `50-85`.
- `challenge_integrated` live should contain hard cases that may score below 100. Target initial range: `40-80`.

A suite scoring 100 is allowed only when runtime genuinely satisfies all hard rubrics and diagnostics. During implementation, any 100-point challenge suite must trigger plan review: either make the case harder, add missing rubric detail, or document concrete evidence that the runtime already satisfies that hard scenario.

## File Map

### Modify

- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
  - Add generic partial scoring with rubric items.
  - Add structured evidence checks needed by hard cases.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`
  - Unit tests for partial rubric scoring and diagnostics-based checks.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`
  - Expected hard case ids and suite invariants.
- `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`
  - Scripted hard challenge score shape and invariant checks.
- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/scripted_runtime.py`
  - Update only scripted memory/subagent challenge behavior to exercise partial scoring. Keep MCP quality out of scripted mode.
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_memory.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_mcp.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_subagent.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_integrated.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/*.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/*.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_subagent/*.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_integrated/*.toml`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-05-17-challenge-eval-design.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/README.md`
- `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

### Optional create

- `/Users/litiezhu/workspace/github/marten-runtime/evals/fixtures/memory/challenge_hard_scope_conflict_cn.md`
- Additional TOML case files only when replacing weak files would make history hard to read.

## Hard Case Matrix

### Memory hard cases

Replace the current 4 simple cases with hard cases. Keep file names only when useful for compatibility; the content must become hard-case content.

1. `memory_interference_recall_cn`
   - Multi-turn with durable preference plus temporary contradictory instruction.
   - Expected: final answer uses durable preference after temporary turn expires.
   - Bad current behavior to catch: temporary instruction persists or overrides durable preference.

2. `memory_scope_isolation_cn`
   - Global, current agent, other agent, current workspace, other workspace memory fixture.
   - Expected: current visible scope only.
   - Bad behavior: leakage from other agent/workspace or missing current scoped memory.

3. `memory_overwrite_conflict_cn`
   - Old preference, replace with new preference, then ask with wording close to old value.
   - Expected: new value only and evidence of replace semantics.
   - Bad behavior: stale value leakage.

4. `memory_should_not_write_cn`
   - Explicit ephemeral instruction plus later recall attempt.
   - Expected: no memory write, later recall says it was temporary.
   - Bad behavior: memory append/replace on ephemeral content.

### MCP hard cases

Keep live-only. Replace current easy checks with hard cases:

1. `mcp_multi_source_repo_evidence_cn`
   - Read README and query commits or repository metadata.
   - Expected: final answer includes evidence from both source types.
   - Bad behavior: one MCP call only, answer based on README only, or invented commit evidence.

2. `mcp_empty_result_recovery_cn`
   - First prompt asks for a likely sparse search target and tells model to recover by reading README if sparse.
   - Expected: model makes follow-up MCP call after sparse/empty result and states recovery basis.
   - Bad behavior: stops after sparse result or invents.

3. `mcp_tool_result_attribution_cn`
   - Ask for a repo assessment with explicit path/commit/source attribution.
   - Expected: output ties claims to `README.md`, commit metadata, or MCP result fields.
   - Bad behavior: generic assessment with no source anchors.

### Subagent hard cases

Scripted + live capable. Replace current easy checks with hard cases:

1. `subagent_delegation_boundary_cn`
   - Complex investigation should delegate once with a precise label/task.
   - Expected: one spawn, bounded child task, parent integrates child result.
   - Bad behavior: main-thread-only or vague child task.

2. `subagent_no_duplicate_dispatch_cn`
   - Follow-up asks for same child result.
   - Expected: no second child for same task; parent reuses existing/known state.
   - Bad behavior: duplicate spawn.

3. `subagent_incomplete_child_handling_cn`
   - Child accepted/background without completed result.
   - Expected: parent clearly states accepted/in-progress and avoids fabricating child output.
   - Bad behavior: fabricates child completion or gives unsupported repo facts.

### Integrated hard cases

Live-only. Keep skill positive/negative, add pressure:

1. `integrated_memory_mcp_conflict_resolution_cn`
   - Memory says output order/style. MCP evidence supplies repo facts. User introduces conflicting temporary style.
   - Expected: durable memory style + MCP evidence; temporary conflict does not persist.

2. `integrated_subagent_mcp_evidence_boundary_cn`
   - Parent delegates MCP child. Parent must avoid claiming child result unless diagnostics show completion.
   - Expected: real spawn and honest parent status or evidence-based synthesis when result exists.

3. `skill_required_multistep_apply_cn`
   - User explicitly requests `long-run-execution` and asks for chunk verification behavior.
   - Expected: skill load and answer includes verifiable chunk/test/doc drift checks.

4. `skill_unneeded_complex_direct_cn`
   - Moderately complex but direct conceptual task, no skill requested.
   - Expected: no skill load, no subagent, direct answer.

## Chunk 1: Add Partial Rubric Scoring to Challenge Grader

### Task 1.1: Add generic `rubric_items` text scoring

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`

TOML shape:

```toml
[grader_case.task_success]
contains_all = ["风险"]
forbid_all = ["工具执行失败"]

[[grader_case.task_success.rubric_items]]
id = "has_risk"
points = 4
contains_all = ["风险"]

[[grader_case.task_success.rubric_items]]
id = "has_conclusion"
points = 4
contains_all = ["结论"]

[[grader_case.task_success.rubric_items]]
id = "no_fabrication"
points = 2
forbid_all = ["我猜", "可能是"]
```

Rules:

- Existing component-level rules remain gate-style prerequisites for that component.
- When `rubric_items` exists, component ratio = earned item points / total item points.
- If a component-level prerequisite fails, component ratio = `0.0`.
- `contains_all`, `contains_any`, `forbid_all`, `anchor_groups` work inside each item.
- Item details must include `id`, `points`, `earned`, `passed`, and matched/missing evidence.
- Missing or zero `points` defaults to `1`.
- Empty `rubric_items` keeps existing 0/1 behavior.

Steps:

- [ ] Add unit test `test_challenge_grader_scores_text_rubric_items_partially`.
- [ ] Run only that test and confirm it fails because rubric scoring is absent.
- [ ] Implement `_grade_rubric_items(...)` and integrate it into `_grade_text_component`.
- [ ] Run `tests.evals.test_challenge_family_grader`.

Expected:

- A component with 6 of 10 item points returns ratio `0.6` and score `weight * 0.6`.
- Gate components fail when ratio `< 1.0`, so hard cases can fail while still showing useful score.

### Task 1.2: Add rubric support to tool path and state continuity components

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/family_graders/challenge.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_challenge_family_grader.py`

TOML shape:

```toml
[[grader_case.tool_path_quality.rubric_items]]
id = "called_memory"
points = 2
required_tools = ["memory"]

[[grader_case.tool_path_quality.rubric_items]]
id = "called_mcp"
points = 4
required_tools = ["mcp"]
min_tool_calls = 2
max_tool_calls = 5

[[grader_case.state_continuity.rubric_items]]
id = "used_preferences"
points = 3
required_memory_sections = ["preferences"]

[[grader_case.state_continuity.rubric_items]]
id = "child_completed"
points = 4
require_subagent_completion = true
required_child_tools = ["mcp"]
```

Rules:

- Tool rubric item supports: `required_tools`, `forbidden_tools`, `required_skill_ids`, `forbidden_skill_ids`, `min_tool_calls`, `max_tool_calls`.
- State rubric item supports: `required_memory_sections`, `forbidden_memory_tokens`, `required_subagent_labels`, `min_subagent_tasks`, `max_subagent_tasks`, `require_subagent_completion`, `required_child_tools`, `required_skill_ids`.
- Component-level rules stay prerequisites.

Steps:

- [ ] Add unit test `test_challenge_grader_scores_tool_and_state_rubric_items_partially`.
- [ ] Run the test and confirm it fails.
- [ ] Refactor tool/state checks into reusable boolean detail helpers.
- [ ] Add rubric item scoring for tool/state components.
- [ ] Run challenge grader tests.

Expected:

- Missing `mcp` earns 0 for that item but other tool/state items can still score.
- Requiring child MCP completion fails only when the case declares it.

### Task 1.3: Preserve existing challenge tests and reports

**Files:**
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_compare.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_report.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`

Steps:

- [ ] Run targeted tests:

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest -v \
  tests.evals.test_challenge_family_grader \
  tests.evals.test_compare \
  tests.evals.test_report \
  tests.evals.test_executor
```

Expected: PASS.

Completion for Chunk 1:

- Generic challenge grader supports partial scoring.
- Component details explain which rubric items passed/failed.
- Existing 0/1 TOML cases still work.

## Chunk 2: Replace Memory Challenge with Hard Cases

### Task 2.1: Harden memory TOML cases

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_interference_recall_cn.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_scope_isolation_cn.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_overwrite_conflict_cn.toml`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_memory/memory_should_not_write_cn.toml`
- Optional modify/create: `/Users/litiezhu/workspace/github/marten-runtime/evals/fixtures/memory/challenge_hard_scope_conflict_cn.md`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`

Required case qualities:

- Each case has 5-10 rubric items across components.
- `gate_components` should include at least `task_success` and one structural component.
- At least one case is expected to produce partial score in scripted mode.
- Memory semantics use explicit `scope`, `type`, `section` in tool-path expectations where relevant.

Steps:

- [ ] Update each memory case with hard multi-step turns and `rubric_items`.
- [ ] Add fixture entries for current and invisible scope conflict.
- [ ] Add manifest invariant test that each challenge memory case has at least one `rubric_items` block.
- [ ] Run manifest tests.

Expected: PASS.

### Task 2.2: Adjust scripted runtime only for hard memory harness validation

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/scripted_runtime.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`

Rules:

- Scripted responses can intentionally miss some rubric items to prove score granularity.
- Do not hardcode runtime behavior outside scripted eval client.
- Keep case-id branching limited to scripted eval harness.

Steps:

- [ ] Update scripted memory replies for hard case turns.
- [ ] Add/modify executor test to assert `challenge_memory` scripted total score is below 100 and above 0.
- [ ] Assert at least one memory case has a failed rubric item in `score_breakdown_json`.
- [ ] Run executor test.

Expected:

- `challenge_memory` scripted passes or fails according to gate config, but total score is meaningfully below 100.

### Task 2.3: Run memory hard challenge

Command:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py \
  --suite challenge_memory \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --report-root reports/evals \
  --db-path data/evals.sqlite3
```

Expected:

- Run completes.
- Report includes rubric item details.
- Total score is below 100 and above 0.
- A 100 score blocks the chunk until cases or rubric items are strengthened.

Completion for Chunk 2:

- Memory challenge has real hard scenarios.
- It can show improvement through rubric deltas.

## Chunk 3: Replace MCP Challenge with Live Hard Cases

### Task 3.1: Harden MCP live cases

**Files:**
- Rename or modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/mcp_multi_turn_repo_investigation_cn.toml`
- Rename or modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/mcp_result_synthesis_cn.toml`
- Rename or modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_mcp/mcp_recovery_after_empty_result_cn.toml`
- Modify when renaming: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_mcp.toml`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`

Required case qualities:

- `challenge_mcp` remains `scripted_supported = false`.
- Each case requires real `mcp` and has at least 2 MCP-related rubric items.
- Cases should target stable repository facts: README, repo metadata, commit metadata.
- Each case should include a source attribution rubric: path, commit, README, or tool result field.

Steps:

- [ ] Convert current cases to:
  - `mcp_multi_source_repo_evidence_cn`
  - `mcp_empty_result_recovery_cn`
  - `mcp_tool_result_attribution_cn`
- [ ] Update suite manifest if filenames change.
- [ ] Add manifest invariant: `challenge_mcp` cases are live-only, require `mcp`, and have rubric items.
- [ ] Run manifest tests.

Expected: PASS.

### Task 3.2: Validate live MCP hard behavior

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

Expected:

- Run completes or blocks only for real external dependency failure.
- Token total > 0.
- Total score should be below 100 on the current implementation unless evidence proves all hard requirements are met.
- Case details reveal missing source attribution, missing recovery, or single-source synthesis when present.
- A 100 score requires immediate hardening or documented evidence that the runtime satisfies every hard rubric.

Completion for Chunk 3:

- MCP challenge measures real multi-step tool quality.
- It can fail meaningfully without breaking gate eval.

## Chunk 4: Replace Subagent Challenge with Hard Cases

### Task 4.1: Harden subagent cases

**Files:**
- Modify or rename files under `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_subagent/`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_subagent.toml`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`

Required case qualities:

- Scripted mode remains supported.
- Cases cover delegation boundary, duplicate dispatch, incomplete child handling.
- At least one case requires subagent diagnostics through declarative metadata.
- At least one case forbids unsupported/fabricated child completion claims.

Steps:

- [ ] Convert current cases to:
  - `subagent_delegation_boundary_cn`
  - `subagent_no_duplicate_dispatch_cn`
  - `subagent_incomplete_child_handling_cn`
- [ ] Add `rubric_items` for spawn count, labels, child completion, parent honesty, synthesis.
- [ ] Update manifest expected case ids.
- [ ] Run manifest tests.

Expected: PASS.

### Task 4.2: Adjust scripted subagent behavior for partial scoring

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/evals/scripted_runtime.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`

Steps:

- [ ] Update scripted client for renamed/hardened cases.
- [ ] Ensure one scripted case intentionally misses a non-gate rubric item.
- [ ] Add/modify executor test: `challenge_subagent` scripted score is below 100 and above 0.
- [ ] Assert duplicate dispatch case catches more than one spawn when scripted to do so in a local unit or fixture scenario.

Expected: PASS.

### Task 4.3: Run subagent hard challenge

Command:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py \
  --suite challenge_subagent \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --report-root reports/evals \
  --db-path data/evals.sqlite3
```

Expected:

- Run completes.
- Total score is below 100 and above 0.
- Component details identify subagent-specific misses.
- A 100 score blocks the chunk until cases or rubric items are strengthened.

Completion for Chunk 4:

- Subagent challenge evaluates delegation quality, duplication, and parent honesty.

## Chunk 5: Replace Integrated Challenge with Hard Cases

### Task 5.1: Harden integrated cases

**Files:**
- Modify or rename files under `/Users/litiezhu/workspace/github/marten-runtime/evals/cases/challenge_integrated/`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/evals/suites/challenge_integrated.toml`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_suite_manifests.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/evals/test_executor.py`

Required case qualities:

- `challenge_integrated` remains live-only.
- Suite dependencies remain `provider`, `mcp`, `subagent`.
- Covers memory + MCP conflict, subagent + MCP boundary, skill required, skill forbidden.
- At least one integrated case is allowed/expected to fail or partially score today.
- No integrated case should pass on `工具执行失败`.

Steps:

- [ ] Convert current cases to:
  - `integrated_memory_mcp_conflict_resolution_cn`
  - `integrated_subagent_mcp_evidence_boundary_cn`
  - `skill_required_multistep_apply_cn`
  - `skill_unneeded_complex_direct_cn`
- [ ] Update suite manifest paths.
- [ ] Add/modify tests ensuring integrated hard cases:
  - reject tool failure text,
  - require `mcp` for memory+MCP case,
  - require `spawn_subagent` for subagent boundary case,
  - require `skill` only for skill-required case,
  - forbid `skill` for skill-unneeded case.
- [ ] Run manifest and executor invariant tests.

Expected: PASS.

### Task 5.2: Run integrated live hard challenge

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

- Run completes or blocks only for real provider/MCP/subagent dependency failure.
- Token total > 0 when live completes.
- Total score should be below 100 on the current implementation unless evidence proves all hard requirements are met.
- Report identifies which integrated behaviors are weak.
- A 100 score requires immediate hardening or documented evidence that the runtime satisfies every hard rubric.

Completion for Chunk 5:

- Integrated challenge exposes combined-chain quality gaps.
- Skill evaluation remains meaningful and bounded.

## Chunk 6: Documentation and Operator Interpretation

### Task 6.1: Update design and README

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-05-17-challenge-eval-design.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/README.md`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

Docs must state:

- Gate eval is the health/regression layer.
- Challenge eval is expected to include hard failing or partially passing cases.
- 100 on challenge means either runtime satisfies hard cases or the suite is too weak.
- Operators should inspect `rubric_items`, `component_summary`, `Challenge Delta`, token/tool/LLM deltas, and stability.
- Initial hard-case scores create the baseline for future improvement.

Steps:

- [ ] Update docs with hard-case philosophy and commands.
- [ ] Add current score interpretation after first hard eval runs.
- [ ] Update `STATUS.md` with completed chunks and latest verification.
- [ ] Run docs grep:

```bash
grep -R "hard case\|rubric_items\|Challenge Delta\|100" -n \
  docs/README.md \
  docs/2026-05-17-challenge-eval-design.md \
  docs/2026-05-17-challenge-hard-cases-execution-plan.md
```

Expected: entries exist.

Completion for Chunk 6:

- Docs prevent future agents from weakening challenge cases back into smoke tests.

## Final Verification Matrix

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

Expected: PASS.

### Full eval test suite

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest discover -v tests/evals
```

Expected: PASS.

### Compile and diff hygiene

```bash
PYTHONPATH=src:. .venv/bin/python -m compileall -q src tests scripts/run_eval.py scripts/migrate_memory_md_to_sqlite.py
git diff --check
```

Expected: PASS.

### Gate eval safety check

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite main_chain_core --mode scripted --profile openai_gpt_5_4 --baseline latest_passed --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite memory_long_horizon --mode scripted --profile openai_gpt_5_4 --baseline latest_passed --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite subagent_task_progress --mode scripted --profile openai_gpt_5_4 --baseline latest_passed --report-root reports/evals --db-path data/evals.sqlite3
```

Expected: PASS, matching prior gate health.

### Challenge eval runs

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_memory --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_subagent --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_mcp --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 180
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_integrated --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 240
```

Expected:

- Scripted challenge suites complete.
- Live challenge suites complete or show precise dependency blockers.
- Each challenge suite should produce a score below 100 on the current implementation, unless a specific suite has documented evidence that all hard rubrics are genuinely satisfied.
- Reports expose concrete failed rubric items.

## Overall Completion Definition

This plan is complete when all items are true:

1. Gate eval suites remain unchanged and passing.
2. `challenge_*` suites contain hard cases with `rubric_items`.
3. Challenge grader supports partial scoring for text, tool path, and state continuity.
4. Challenge reports show why a score is below 100 through item-level details.
5. `challenge_memory` and `challenge_subagent` scripted runs show non-100 meaningful scores.
6. `challenge_mcp` and `challenge_integrated` live runs use real MCP/provider behavior and are designed to reveal non-100 hard-case gaps.
7. Each challenge live or scripted suite produces a score below 100 for real, inspectable reasons, or the implementation records concrete evidence that a 100 score reflects actual hard-case success.
8. No runtime semantic routing or host-side intent decision was added.
9. Unit tests, full eval tests, compile, and diff hygiene pass.
10. Docs clearly position challenge eval as the quality-improvement layer.
