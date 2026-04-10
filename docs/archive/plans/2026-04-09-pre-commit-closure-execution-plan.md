# Pre-Commit Closure Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the narrow pre-commit closure pass for `marten-runtime` by fixing architecture-doc drift, tightening fast-path boundary expression, deduplicating shared matcher logic without growing a new host-side routing subsystem, applying low-risk hygiene fixes, and proving no behavior drift with focused and full regression.

**Architecture:** This plan follows `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-pre-commit-closure-and-evolution-design.md` exactly. It keeps the runtime’s current validated hardening behavior, prefers doc correction and behavior-preserving deduplication over structural cleanup, and explicitly defers fast-path exit strategy and major `loop.py` decomposition to the next branch.

**Tech Stack:** Python 3.12, `unittest`, repository docs under `docs/`, runtime implementation under `src/marten_runtime/`, local continuity in `STATUS.md`.

---
> **Execution status:** Completed on 2026-04-09. All required closure tasks were executed and verified. Conditional fallback steps (for unexpected regressions) were not needed because the targeted and final regression suites stayed green.


## Scope Guardrails

Before making any change, re-read:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-pre-commit-closure-and-evolution-design.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/architecture/adr/0001-thin-harness-boundary.md`
- `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

Hard constraints for this plan:

- Do **not** remove validated fast paths.
- Do **not** expand the host-side routing surface.
- Do **not** introduce a planner, intent router, policy center, or heavy classifier subsystem.
- Do **not** perform a major `runtime/loop.py` refactor.
- Do **not** mix deferred evolution work into this branch.
- Every task must end with verification evidence.
- Final completion requires both targeted verification and the full required regression suite.

If any step starts changing `llm_request_count` semantics, route shape, or deterministic recovery behavior on covered paths, stop and reduce the change back to the smallest behavior-preserving version.

---

## File Structure And Responsibilities

### Existing files to modify

- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/ARCHITECTURE_CHANGELOG.md`
  - correct behavior drift in architecture-facing documentation
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
  - keep route selection, recovery, direct rendering, and runtime loop behavior intact while adopting shared thin helper logic and explicit boundary comments
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
  - keep request-specific hardening behavior intact while consuming shared thin helper logic and tightening instruction phrasing where safe
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
  - preserve or extend regression coverage for the exact paths touched by closure changes
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_skills.py`
  - remove the machine-specific absolute path assumption
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`
  - keep continuity aligned with actual progress

### Small new file allowed if needed

- Create: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/query_hardening.py`
  - optional thin shared helper module for duplicated pure query-detection logic only
  - allowed contents: pure matcher functions and repo-slug extraction helpers already duplicated in `loop.py` and `llm_client.py`
  - forbidden contents: routing policy, planner behavior, rendering, runtime state mutation, broad intent framework language

### Files/directories allowed to delete

- Delete if still empty/unused:
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/operator/`
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/cli/`

### Files that should remain untouched unless a real blocker appears

- MCP tool implementation beyond regression-safe test support
- Feishu channel architecture beyond low-risk hygiene
- automation/self-improve/sqlite store internals
- broad capability-catalog redesign

---

## Verification Baseline Used Throughout

### Targeted runtime regression command

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop
```

### Focused mixed-surface regression command

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp tests.test_skills
```

### Required final regression command

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp
```

### Optional full confidence sweep if any unexpected drift appears

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v
```

---

## Chunk 1: Lock The Baseline And Fix Architecture-Doc Drift

### Task 1: Reconfirm behavior truth before editing docs

**Files:**
- Read: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-pre-commit-closure-and-evolution-design.md`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/docs/ARCHITECTURE_CHANGELOG.md`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Re-read the closure design and note the allowed change surface**

Run:

```bash
sed -n '1,260p' /Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-pre-commit-closure-and-evolution-design.md
```

Expected: the design explicitly says this branch is closure-only, no fast-path removal, no major `loop.py` refactor, no new intent subsystem.

- [ ] **Step 2: Reconfirm the changelog drift with direct evidence from the codebase**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "Explicit GitHub MCP Repo Queries Now Use Thin Direct Rendering|llm_request_count=0|test_runtime_shortcuts_explicit_github_repo_query_to_direct_mcp_call|len\(llm.requests\), 2|run.llm_request_count, 2" docs/ARCHITECTURE_CHANGELOG.md tests/test_runtime_loop.py
```

Expected: the changelog claims direct rendering for explicit GitHub repo queries, while the test for explicit repo metadata still proves `len(llm.requests) == 2` and `run.llm_request_count == 2`.

- [ ] **Step 3: Run the single authoritative regression proving current repo-metadata behavior**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_query_to_direct_mcp_call
```

Expected: PASS, confirming the current implementation is direct MCP call + follow-up LLM rather than direct final render.

### Task 2: Correct `ARCHITECTURE_CHANGELOG.md` without changing runtime behavior

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/docs/ARCHITECTURE_CHANGELOG.md`
- Verify against: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Edit the incorrect changelog entry**

Required edit content:

- remove or rewrite wording that implies explicit GitHub repo metadata queries already end in direct final rendering
- distinguish the following three surfaces clearly:
  1. direct MCP call + follow-up LLM
  2. direct deterministic render for narrow paths already implemented
  3. deterministic recovery using already-available tool results after late follow-up failure

- [ ] **Step 2: Run a docs consistency grep after the edit**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "Explicit GitHub MCP Repo Queries Now Use Thin Direct Rendering|repo-metadata query now returns with `llm_request_count=0`|explicit latest-commit query now returns with `llm_request_count=0`" docs/ARCHITECTURE_CHANGELOG.md
```

Expected:
- no stale wording remains for repo-metadata direct final render
- any retained `llm_request_count=0` wording only refers to paths still proven by the current code/tests

- [ ] **Step 3: Re-run the authoritative targeted regression after the doc fix**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_query_to_direct_mcp_call
```

Expected: PASS again, proving the documentation now matches unchanged runtime truth.

- [ ] **Step 4: Sync continuity**

Update `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md` with:

- the doc-drift fix completed
- the evidence used
- confirmation that no runtime semantics changed in this chunk

---

## Chunk 2: Deduplicate Shared Matcher Logic Without Growing A New Subsystem

### Task 3: Add or identify one thin shared source of truth for duplicated pure helpers

**Files:**
- Create if needed: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/query_hardening.py`
- Modify if reusing instead: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Modify if reusing instead: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Identify the exact duplicated pure helpers before changing code**

Expected candidates:

- `_extract_github_repo(...)` / `_extract_github_repo_query(...)`
- `_is_runtime_context_query(...)`
- `_is_github_repo_commit_query(...)`
- `_is_github_repo_metadata_query(...)`

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "def _extract_github_repo|def _extract_github_repo_query|def _is_runtime_context_query|def _is_github_repo_commit_query|def _is_github_repo_metadata_query" src/marten_runtime/runtime/loop.py src/marten_runtime/runtime/llm_client.py
```

Expected: duplication appears in both files.

- [ ] **Step 2: Write or extend focused regression coverage before moving the logic**

Add tests that lock the intended shared semantics. Acceptable options:

- extend `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py` with focused tests for representative messages, or
- add a small new focused test file if and only if it stays thin and local

Minimum message cases to lock:

1. runtime context natural-language query
2. explicit GitHub latest-commit query with repo URL
3. explicit GitHub repo metadata query with repo URL
4. negative case where commit query must not be treated as metadata query

Suggested test shape:

```python
def test_runtime_query_hardening_detects_commit_query_but_not_metadata_query(self) -> None:
    message = "请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？"
    self.assertTrue(is_github_repo_commit_query(message))
    self.assertFalse(is_github_repo_metadata_query(message))
```

- [ ] **Step 3: Run the new or updated focused tests and confirm they fail only if the shared helper is not yet wired correctly**

Run the narrowest new test command first.

Expected: if new tests are added before implementation, they should fail for the right reason or expose the duplication gap; if the test only codifies existing accessible behavior, document that it already passes against duplicated logic and continue.

- [ ] **Step 4: Implement the smallest shared-helper extraction**

Implementation rules:

- keep only pure helper logic in the shared location
- no runtime state access
- no route selection
- no rendering
- no planner-like naming
- preserve existing tokens and matching semantics unless a test-backed bug is found

- [ ] **Step 5: Switch both `loop.py` and `llm_client.py` to consume the shared helpers**

Expected result:

- duplicated logic is removed or reduced to thin forwarding wrappers
- behavior remains unchanged

- [ ] **Step 6: Run targeted runtime regression for all flows affected by the shared helpers**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_natural_language_context_query_to_runtime_tool_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_query_to_direct_mcp_call \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_commit_query_to_list_commits
```

Expected: PASS, with existing `llm_request_count` behavior unchanged.

### Task 4: Keep route ownership in `loop.py` and instruction ownership in `llm_client.py`

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`

- [ ] **Step 1: Add a short module-level or local boundary comment near the shared-helper import/use site**

Required meaning:

- shared helpers exist only to remove duplicate truth
- route policy still belongs locally to `loop.py`
- instruction shaping still belongs locally to `llm_client.py`
- this is not a general intent-routing subsystem

- [ ] **Step 2: Run a grep-based boundary check**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "intent router|hardening exception|duplicate truth|not a general routing model|not an intent subsystem" src/marten_runtime/runtime/loop.py src/marten_runtime/runtime/llm_client.py src/marten_runtime/runtime/query_hardening.py
```

Expected: the edited code now documents the boundary in plain text close to the relevant logic.

- [ ] **Step 3: Re-run the focused mixed-surface regression**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp
```

Expected: PASS.

- [ ] **Step 4: Sync continuity**

Update `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md` with:

- which helpers were deduplicated
- whether a thin shared helper file was created
- confirmation that no new routing subsystem was introduced
- the verification commands and results

---

## Chunk 3: Tighten Boundary Expression Around Forced Routes And Request-Specific Instructions

### Task 5: Add explicit fast-path boundary comments and no-growth framing in `loop.py`

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Write or extend a regression note in tests if needed to protect current fast-path behavior**

If existing tests already fully cover the fast-path set, add no new test. If coverage is unclear, add one focused regression for the exact path being clarified.

Minimum covered paths to reconfirm:

- runtime context query shortcut
- time query shortcut
- automation list/detail shortcut
- trending shortcut including typo case

- [ ] **Step 2: Add boundary comments immediately above or near `_select_forced_tool_route(...)`**

The comment must say the equivalent of:

- these routes are narrow hardening exceptions for already-observed live/runtime failures
- they are not a general host-side intent router
- new route categories should not be added casually

- [ ] **Step 3: Run the fast-path regression set**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_natural_language_context_query_to_runtime_tool_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_natural_language_time_query_to_time_tool_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_natural_language_automation_list_query_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_natural_language_automation_detail_query_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_trending_query_to_github_trending_mcp_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_treding_typo_query_to_github_trending_mcp_without_first_llm
```

Expected: PASS, confirming the closure work clarified boundaries without changing fast-path runtime behavior.

### Task 6: Tighten `_request_specific_instruction(...)` without changing behavior

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`

- [ ] **Step 1: Inspect the current request-specific instruction branches before editing**

Run:

```bash
sed -n '600,760p' /Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/llm_client.py
```

Expected: runtime/time/GitHub/Feishu instruction branches are visible.

- [ ] **Step 2: Reduce over-specification only where it is clearly safe**

Allowed changes:

- tighten wording so the instruction reads as hardening guidance rather than full payload scripting
- preserve the semantic requirement to use live tools instead of stale memory where current behavior depends on it

Forbidden changes:

- removing a branch solely for aesthetic reasons
- weakening a branch if it changes covered behavior
- expanding instruction handling into a broader policy system

- [ ] **Step 3: Re-run explicit GitHub and runtime/time behavior tests**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_query_to_direct_mcp_call \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_commit_query_to_list_commits \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_natural_language_context_query_to_runtime_tool_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_natural_language_time_query_to_time_tool_without_first_llm \
  tests.test_runtime_loop.RuntimeLoopTests.test_runtime_recovers_explicit_github_commit_query_after_first_llm_provider_failure
```

Expected: PASS, showing instruction tightening did not change visible behavior or recovery semantics.

- [ ] **Step 4: If any test drifts, revert the risky instruction wording and keep only boundary comments**

Expected fallback behavior: preserve runtime behavior first, leave stronger tightening to the next branch.

- [ ] **Step 5: Sync continuity**

Update `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md` with:

- what instruction tightening was safely retained
- what was intentionally deferred to the evolution branch
- the verification results

---

## Chunk 4: Low-Risk Hygiene Only

### Task 7: Remove the machine-specific absolute path from `tests/test_skills.py`

**Files:**
- Modify: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_skills.py`
- Test: `/Users/litiezhu/workspace/github/marten-runtime/tests/test_skills.py`

- [ ] **Step 1: Write the path fix using `Path(__file__)`-based repository-relative construction**

Expected implementation shape:

```python
repo_root = Path(__file__).resolve().parent.parent
skill_body = (repo_root / "skills" / "feishu_channel_formatting" / "SKILL.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the focused skill test**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_skills.SkillTests.test_repo_feishu_formatting_skill_constrains_trending_order_and_rank_markers
```

Expected: PASS on the local machine without relying on a hard-coded absolute repository path.

### Task 8: Remove empty directory shells and obvious no-op noise only if behavior-neutral

**Files:**
- Delete if empty: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/operator/`
- Delete if empty: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/cli/`
- Modify if truly behavior-neutral: `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/rendering.py`

- [ ] **Step 1: Reconfirm directories are empty and not referenced by live code**

Run:

```bash
python - <<'PY'
import os
for path in [
    '/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/operator',
    '/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/cli',
]:
    print(path, os.path.exists(path), list(os.walk(path)) if os.path.exists(path) else 'missing')
PY
```

Expected: only empty shells or `__pycache__` remain.

- [ ] **Step 2: Delete the empty shells and any stale `__pycache__` inside them**

Run repository-safe delete commands only for these exact empty paths.

- [ ] **Step 3: Remove only obviously no-op noise in `rendering.py` if the diff is truly behavior-neutral**

Candidate example already observed in review:

- an `if ...: pass` branch that has no effect and can be safely collapsed

Do **not** turn this into a broad cleanup of exception handling or style.

- [ ] **Step 4: Run focused hygiene regression**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_skills tests.test_feishu
```

Expected: PASS.

- [ ] **Step 5: Verify the empty directories are actually gone**

Run:

```bash
test ! -d /Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/operator && \
test ! -d /Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/interfaces/cli
```

Expected: command exits successfully.

- [ ] **Step 6: Sync continuity**

Update `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md` with:

- the hygiene fixes completed
- confirmation that no broader cleanup wave was started
- the focused test results

---

## Chunk 5: Final Alignment, Regression, And Plan/Status Sync

### Task 9: Re-check the whole branch against the closure design

**Files:**
- Read: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-pre-commit-closure-and-evolution-design.md`
- Read: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-pre-commit-closure-execution-plan.md`
- Update: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`

- [ ] **Step 1: Compare completed changes against the design non-goals**

Required check list:

- no fast paths removed
- no host-side routing expansion
- no major `loop.py` refactor
- no new general intent subsystem
- no unrelated cleanup wave
- deferred evolution still deferred

- [ ] **Step 2: Record any drift immediately if found**

If drift exists, fix the drift before claiming the plan chunk is complete.

### Task 10: Run final required regression and optional full sweep if needed

**Files:**
- Verify runtime and docs alignment only; no new product scope

- [ ] **Step 1: Run the required final regression suite**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp
```

Expected: PASS.

- [ ] **Step 2: If any failure appears, fix only closure-scope regressions and re-run the same suite**

Expected: the suite returns to green without introducing new scope.

- [ ] **Step 3: If the closure changes touched more than expected or any uncertainty remains, run the optional full sweep**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v
```

Expected: PASS, used only when extra confidence is needed.

### Task 11: Final continuity and execution sync

**Files:**
- Update: `/Users/litiezhu/workspace/github/marten-runtime/STATUS.md`
- Update if needed: `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-pre-commit-closure-execution-plan.md`

- [ ] **Step 1: Update `STATUS.md` with the final closure state**

Required status content:

- goal achieved or not achieved
- exact files changed
- verification commands run and results
- current branch remains closure-only
- deferred evolution remains for the next branch

- [ ] **Step 2: Mark completed plan items so future agents do not misread them as open**

Expected: the plan/checklist reflects reality.

- [ ] **Step 3: Final manual alignment check**

Confirm the repository now has:

- one formal design doc for the closure pass
- one detailed execution plan for the closure pass
- `STATUS.md` explicitly noting that evolution work is deferred to the next branch

---

## Completion Criteria

This plan is complete only when all of the following are true:

1. `docs/ARCHITECTURE_CHANGELOG.md` matches the current tested runtime behavior.
2. Shared duplicated matcher logic has been reduced without creating a new routing subsystem.
3. `loop.py` and `llm_client.py` now express the fast-path/instruction boundary more clearly.
4. The absolute skill-test path is removed.
5. Empty directory shells are removed if still empty.
6. Closure-only scope was preserved throughout.
7. `STATUS.md` is synchronized.
8. The required final regression suite passes.

---

## Deferred To Next Branch (Do Not Pull Forward)

These are intentionally excluded from execution here:

- fast-path exit/removal strategy
- controlled structural decomposition of `runtime/loop.py`
- broader capability-surface redesign
- deeper channel-boundary refactoring
- generic storage abstractions
- builtins consolidation
- broad style cleanup

If execution starts sliding into any of these, stop and return to the closure design boundary.
