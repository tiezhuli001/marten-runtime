# Self-Improve Review / Skill Candidate Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement real-time self-improve triggers, runtime-owned review-subagent execution, and skill-candidate notification/confirmation/promotion on top of `marten-runtime`'s shipped lightweight subagent lane.

**Architecture:** Keep the harness thin. Reuse the existing `self_improve` store/service/runtime surfaces, add one narrow trigger-and-review pipeline, and extend the existing `self_improve` management surface rather than creating a second memory or workflow subsystem. Background review must run only through the existing subagent lane, with runtime-owned dequeue/spawn, review-specific payload budgeting, and explicit child tool ceilings.

**Tech Stack:** Python 3.11+, unittest, existing `self_improve` SQLite store, `RuntimeLoop` post-run outcome flow, `SubagentService`, builtin family tools, `SkillService`, FastAPI diagnostics/runtime bootstrap

---

## Global implementation constraints

These rules apply to every chunk below.

- Review remains a **runtime-owned** contract; `self_improve_review` is only a narrow child reasoning asset.
- Do **not** add a second background execution substrate, automation compatibility shim, or planner/swarm layer.
- Real-time trigger capture is the primary path; any retained automation scan stays legacy backfill only.
- Review child permissions must be narrower than generic `standard` subagents and must never expose nested `spawn_subagent`.
- Review child must not directly send channel notifications or directly promote official skills.
- Skill-candidate lifecycle management must extend the existing `self_improve` family surface; do not add a parallel management tool family.
- `SYSTEM_LESSONS.md` remains active-runtime-lessons-only; skill-candidate content must never be mirrored into that file.
- Keep payloads summary-first and bounded; do not serialize raw full transcripts into review children.
- Every new schema/store/service surface must get targeted tests before implementation is considered done.
- No chunk is complete until its proof command passes.
- Update `STATUS.md` when the implementation-plan writing slice is complete, and again when execution milestones land later.

---

## File structure and responsibility map

### Existing files to extend

- `src/marten_runtime/self_improve/models.py`
  - Add `ReviewTrigger`, `SkillCandidate`, and any small result/notification metadata models.
- `src/marten_runtime/self_improve/sqlite_store.py`
  - Add SQLite tables and CRUD/query helpers for review triggers and skill candidates.
- `src/marten_runtime/self_improve/recorder.py`
  - Keep failure/recovery recording narrow; only add minimal helpers needed for trigger fingerprints/evidence linkage.
- `src/marten_runtime/self_improve/service.py`
  - Keep lesson judging/export here; add review result handling only if it truly belongs with existing self-improve gate logic.
- `src/marten_runtime/runtime/run_outcome_flow.py`
  - Add real-time trigger evaluation enqueue points close to runtime success/failure/recovery evidence.
- `src/marten_runtime/runtime/loop.py`
  - Only touch if a post-turn callback/hook is needed to flush queued review work after the user-facing turn commits.
- `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - Wire any new self-improve dispatcher/review service into runtime bootstrap.
- `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
  - Extend diagnostics with trigger/review/skill-candidate visibility.
- `src/marten_runtime/tools/builtins/self_improve_tool.py`
  - Extend the existing `self_improve` family actions for skill-candidate and review-management operations.
- `src/marten_runtime/data_access/adapter.py`
  - Extend domain access if the family tool continues to route through adapter-backed item listing/detail/delete.
- `src/marten_runtime/subagents/service.py`
  - Extend only if a runtime-owned internal spawn path needs an explicit non-user-facing helper or narrower child profile surface.

### New files likely needed

- `src/marten_runtime/self_improve/trigger_evaluator.py`
  - Runtime-owned trigger classification and dedupe/cooldown checks.
- `src/marten_runtime/self_improve/review_payloads.py`
  - Build bounded review payloads and trim evidence by budget.
- `src/marten_runtime/self_improve/review_dispatcher.py`
  - Dequeue pending triggers after turn commit, spawn review children, persist terminal review state.
- `src/marten_runtime/self_improve/review_child_contract.py`
  - Narrow result parsing/validation for `lesson_proposals[]`, `skill_proposals[]`, and review metadata.
- `src/marten_runtime/self_improve/promotion.py`
  - Runtime-owned skill-candidate promotion path that writes `skills/<slug>/SKILL.md` only after confirmation.
- `skills/self_improve_review/SKILL.md`
  - Narrow child reasoning asset for evidence classification only.

### New test files likely needed

- `tests/test_self_improve_trigger_evaluator.py`
- `tests/test_self_improve_review_dispatcher.py`
- `tests/test_self_improve_skill_candidates.py`
- `tests/test_self_improve_promotion.py`
- `tests/tools/test_self_improve_tool_skill_candidates.py`
- `tests/contracts/test_self_improve_review_contracts.py`

### Existing tests to extend

- `tests/test_self_improve_gate.py`
- `tests/test_self_improve_recorder.py`
- `tests/tools/test_self_improve_tool.py`
- `tests/contracts/test_runtime_contracts.py`
- `tests/contracts/test_gateway_contracts.py`
- `tests/test_subagent_service.py`
- `tests/test_subagent_runtime_loop.py`
- `tests/test_subagent_integration.py`
- `tests/test_skills.py`

---

## Chunk 1: Lock storage and runtime contract with failing tests

### Task 1: Add failing model/store tests for `ReviewTrigger` and `SkillCandidate`

**Files:**
- Modify: `src/marten_runtime/self_improve/models.py`
- Modify: `src/marten_runtime/self_improve/sqlite_store.py`
- Create: `tests/test_self_improve_skill_candidates.py`
- Extend: `tests/test_self_improve_gate.py`

- [ ] **Step 1: Add failing tests for `ReviewTrigger` persistence and lifecycle**

Cover:
- queued trigger record with `trigger_id`, `agent_id`, `trigger_kind`, `source_run_id`, `source_trace_id`, `status`, `semantic_fingerprint`, `payload_json`, `created_at`
- trigger status transitions: `pending -> queued -> running -> processed|failed|discarded`
- dedupe queries by semantic fingerprint and status
- list/get helpers return stable structured values

- [ ] **Step 2: Add failing tests for `SkillCandidate` persistence and lifecycle**

Cover:
- fields from the approved spec: `candidate_id`, `agent_id`, `status`, `title`, `slug`, `summary`, `trigger_conditions`, `body_markdown`, `rationale`, `source_run_ids`, `source_fingerprints`, `confidence`, `semantic_fingerprint`, `created_at`, `reviewed_at`, `promoted_skill_id`
- status transitions: `pending -> accepted|rejected -> promoted`
- listing/filtering by status
- semantic dedupe query path

- [ ] **Step 3: Extend SQLite schema with new tables and focused CRUD helpers**

Implement minimal helpers for:
- save/get/list/update review triggers
- save/get/list/update skill candidates
- mark promotion metadata after official skill write

- [ ] **Step 4: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_self_improve_skill_candidates tests.test_self_improve_gate`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/marten_runtime/self_improve/models.py \
        src/marten_runtime/self_improve/sqlite_store.py \
        tests/test_self_improve_skill_candidates.py \
        tests/test_self_improve_gate.py
git commit -m "test: add self-improve trigger and skill candidate storage contract"
```

---

## Chunk 2: Implement real-time trigger evaluation on the runtime path

### Task 2: Add `SelfImproveTriggerEvaluator` and enqueue logic from runtime evidence

**Files:**
- Create: `src/marten_runtime/self_improve/trigger_evaluator.py`
- Modify: `src/marten_runtime/runtime/run_outcome_flow.py`
- Modify: `src/marten_runtime/self_improve/recorder.py`
- Extend: `tests/test_self_improve_recorder.py`
- Create: `tests/test_self_improve_trigger_evaluator.py`

- [ ] **Step 1: Add failing tests for trigger classification**

Cover:
- `lesson_recovery_threshold` from repeated failures plus later recovery
- `lesson_failure_burst` from repeated failures without recovery
- `complex_successful_tool_episode` from multi-step successful tool episodes
- dedupe/cooldown skips near-duplicate triggers
- only relevant evidence is included in the trigger payload seed

- [ ] **Step 2: Implement `SelfImproveTriggerEvaluator` with runtime-owned heuristics**

Include:
- explicit input object for latest run outcome + recent self-improve evidence + optional tool episode summary
- deterministic trigger classification helpers
- semantic fingerprint computation and budget-aware payload seed generation

- [ ] **Step 3: Wire trigger enqueue into `run_outcome_flow.py`**

Requirements:
- success/failure/recovery recording stays near existing flow
- enqueue happens on the main runtime path, but only as persistence of a pending trigger
- no child spawn from inside the user-facing tool/LLM path

- [ ] **Step 4: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_self_improve_recorder tests.test_self_improve_trigger_evaluator`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/marten_runtime/self_improve/trigger_evaluator.py \
        src/marten_runtime/runtime/run_outcome_flow.py \
        src/marten_runtime/self_improve/recorder.py \
        tests/test_self_improve_recorder.py \
        tests/test_self_improve_trigger_evaluator.py
git commit -m "feat: add real-time self-improve trigger evaluation"
```

---

## Chunk 3: Add runtime-owned review dispatcher and bounded payload builder

### Task 3: Build dequeue/spawn flow that runs review only after turn commit

**Files:**
- Create: `src/marten_runtime/self_improve/review_payloads.py`
- Create: `src/marten_runtime/self_improve/review_child_contract.py`
- Create: `src/marten_runtime/self_improve/review_dispatcher.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/runtime/loop.py`
- Extend: `tests/test_subagent_runtime_loop.py`
- Create: `tests/test_self_improve_review_dispatcher.py`
- Create: `tests/contracts/test_self_improve_review_contracts.py`

- [ ] **Step 1: Add failing tests for payload budgeting and trimming**

Cover:
- payload includes only trigger-linked evidence
- per-collection caps are enforced
- over-budget trimming preserves source run summary and latest decisive evidence
- raw transcript replay is not included

- [ ] **Step 2: Add failing tests for dispatcher ownership and post-turn spawn timing**

Cover:
- enqueue occurs during main runtime path
- dequeue/spawn happens only after the user-facing turn commits
- dispatcher uses runtime-owned internal spawn path, not user-facing prompt logic
- review failure remains in diagnostics and does not silently fall back to another substrate

- [ ] **Step 3: Implement payload builder + child result parser**

Implement:
- bounded payload assembly from trigger + store summaries + skill summaries
- strict parse/validate helpers for `lesson_proposals[]`, `skill_proposals[]`, `nothing_to_save_reason`, and metadata

- [ ] **Step 4: Implement review dispatcher and bootstrap wiring**

Requirements:
- one runtime-owned dispatcher instance in bootstrap/runtime state
- hook from runtime loop post-turn commit or equivalent completion sink
- use existing subagent lane only
- keep the spawn surface deterministic and non-user-facing

- [ ] **Step 5: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_self_improve_review_dispatcher tests.contracts.test_self_improve_review_contracts tests.test_subagent_runtime_loop`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/marten_runtime/self_improve/review_payloads.py \
        src/marten_runtime/self_improve/review_child_contract.py \
        src/marten_runtime/self_improve/review_dispatcher.py \
        src/marten_runtime/interfaces/http/bootstrap_runtime.py \
        src/marten_runtime/runtime/loop.py \
        tests/test_self_improve_review_dispatcher.py \
        tests/contracts/test_self_improve_review_contracts.py \
        tests/test_subagent_runtime_loop.py
git commit -m "feat: add runtime-owned self-improve review dispatcher"
```

---

## Chunk 4: Add narrow review child contract and review-oriented skill asset

### Task 4: Create the review child reasoning surface without widening runtime ownership

**Files:**
- Create: `skills/self_improve_review/SKILL.md`
- Extend: `tests/test_skills.py`
- Extend: `tests/test_subagent_service.py`
- Extend: `tests/test_subagent_integration.py`

- [ ] **Step 1: Add failing tests for `self_improve_review` skill content boundaries**

Cover:
- skill content is classification-only
- skill content does not authorize AGENTS/bootstrap edits
- skill content does not authorize direct promotion or direct user notification
- skill content does not imply nested subagent behavior

- [ ] **Step 2: Add failing tests for review-child tool ceilings**

Cover:
- review child cannot inherit generic `standard` profile accidentally
- review child snapshot excludes MCP/network exploration if not explicitly allowed
- review child snapshot excludes `spawn_subagent` / `cancel_subagent`

- [ ] **Step 3: Implement the review skill asset and any required subagent service hook**

Keep it narrow:
- classification instructions only
- runtime remains source of truth for side effects and persistence

- [ ] **Step 4: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_skills tests.test_subagent_service tests.test_subagent_integration`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/self_improve_review/SKILL.md \
        tests/test_skills.py \
        tests/test_subagent_service.py \
        tests/test_subagent_integration.py
git commit -m "feat: add narrow self-improve review child skill"
```

---

## Chunk 5: Persist review results into lesson and skill-candidate stores

### Task 5: Route child outputs into existing lesson gate and new skill-candidate state

**Files:**
- Modify: `src/marten_runtime/self_improve/service.py`
- Modify: `src/marten_runtime/self_improve/sqlite_store.py`
- Modify: `src/marten_runtime/self_improve/review_dispatcher.py`
- Extend: `tests/test_self_improve_gate.py`
- Extend: `tests/test_self_improve_skill_candidates.py`
- Extend: `tests/contracts/test_self_improve_review_contracts.py`

- [ ] **Step 1: Add failing tests for lesson proposal persistence and gating**

Cover:
- review result writes pending `LessonCandidate`
- existing judge/export path still owns acceptance into `SYSTEM_LESSONS.md`
- duplicate or low-signal lesson proposals are rejected by existing gate behavior

- [ ] **Step 2: Add failing tests for skill proposal persistence**

Cover:
- review result writes pending `SkillCandidate`
- semantic dedupe suppresses near-duplicate candidates
- review metadata/evidence references persist with the candidate

- [ ] **Step 3: Implement result handling**

Requirements:
- lesson proposals feed existing gate path
- skill proposals persist as pending only
- review child terminal status and resulting ids are correlated in diagnostics-friendly state

- [ ] **Step 4: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_self_improve_gate tests.test_self_improve_skill_candidates tests.contracts.test_self_improve_review_contracts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/marten_runtime/self_improve/service.py \
        src/marten_runtime/self_improve/sqlite_store.py \
        src/marten_runtime/self_improve/review_dispatcher.py \
        tests/test_self_improve_gate.py \
        tests/test_self_improve_skill_candidates.py \
        tests/contracts/test_self_improve_review_contracts.py
git commit -m "feat: persist review proposals into lesson and skill candidate stores"
```

---

## Chunk 6: Extend `self_improve` family tool for skill-candidate management

### Task 6: Keep one management surface for inspect / accept / reject / promote

**Files:**
- Modify: `src/marten_runtime/tools/builtins/self_improve_tool.py`
- Modify: `src/marten_runtime/data_access/adapter.py`
- Extend: `tests/tools/test_self_improve_tool.py`
- Create: `tests/tools/test_self_improve_tool_skill_candidates.py`
- Extend: `tests/test_data_access_adapter.py`
- Extend: `tests/contracts/test_gateway_contracts.py`

- [ ] **Step 1: Add failing tests for new `self_improve` actions**

Cover actions such as:
- `list_skill_candidates`
- `skill_candidate_detail`
- `accept_skill_candidate`
- `reject_skill_candidate`
- `promote_skill_candidate`

- [ ] **Step 2: Extend domain adapter shape only as needed**

Requirements:
- keep item listing/detail/delete/update patterns consistent with current lesson-candidate access
- do not add a second parallel tool family

- [ ] **Step 3: Implement builtin tool dispatch for the new skill-candidate actions**

Requirements:
- accept/reject mutate candidate state only
- promotion delegates into a runtime-owned promotion path
- responses remain summary-first and safe for user-facing use

- [ ] **Step 4: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.tools.test_self_improve_tool tests.tools.test_self_improve_tool_skill_candidates tests.test_data_access_adapter tests.contracts.test_gateway_contracts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/marten_runtime/tools/builtins/self_improve_tool.py \
        src/marten_runtime/data_access/adapter.py \
        tests/tools/test_self_improve_tool.py \
        tests/tools/test_self_improve_tool_skill_candidates.py \
        tests/test_data_access_adapter.py \
        tests/contracts/test_gateway_contracts.py
git commit -m "feat: extend self_improve tool with skill candidate lifecycle actions"
```

---

## Chunk 7: Add runtime-owned notification and promotion path

### Task 7: Notify users through the normal runtime path and promote accepted candidates into official skills

**Files:**
- Create: `src/marten_runtime/self_improve/promotion.py`
- Modify: `src/marten_runtime/self_improve/review_dispatcher.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Create: `tests/test_self_improve_promotion.py`
- Extend: `tests/contracts/test_runtime_contracts.py`
- Extend: `tests/test_subagent_integration.py`
- Extend: `tests/test_skills.py`

- [ ] **Step 1: Add failing tests for notification ownership**

Cover:
- review child does not directly notify the user
- runtime/channel path emits one concise notification for a new pending skill candidate **only on channels with runtime-owned async follow-up delivery support** (current repo baseline: Feishu supported; plain HTTP request/response remains inspect-only via `self_improve`)
- cooldown/dedupe suppresses spam for the same semantic candidate

- [ ] **Step 2: Add failing tests for promotion behavior**

Cover:
- only accepted candidates may be promoted
- promotion writes exactly `skills/<slug>/SKILL.md` in the initial slice
- promotion stores `promoted_skill_id`/timestamp metadata
- promoted skill becomes discoverable through `SkillService`
- promotion does not mutate `AGENTS.md`, bootstrap assets, or `SYSTEM_LESSONS.md`

- [ ] **Step 3: Implement runtime-owned promotion path and diagnostics updates**

Requirements:
- file write is narrow and explicit
- diagnostics expose pending trigger/review/candidate counts and latest statuses
- runtime bootstrap wires any required promotion/notification helpers once

- [ ] **Step 4: Run focused tests**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_self_improve_promotion tests.contracts.test_runtime_contracts tests.test_subagent_integration tests.test_skills`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/marten_runtime/self_improve/promotion.py \
        src/marten_runtime/self_improve/review_dispatcher.py \
        src/marten_runtime/interfaces/http/runtime_diagnostics.py \
        src/marten_runtime/interfaces/http/bootstrap_runtime.py \
        tests/test_self_improve_promotion.py \
        tests/contracts/test_runtime_contracts.py \
        tests/test_subagent_integration.py \
        tests/test_skills.py
git commit -m "feat: add skill candidate notification and promotion path"
```

---

## Chunk 8: Full regression, docs sync, and completion proof

### Task 8: Verify the combined slice and sync runtime docs

**Files:**
- Modify: `STATUS.md`
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `docs/README.md`
- Modify: `docs/LIVE_VERIFICATION_CHECKLIST.md` (only if a new live proof step or checklist line is truly needed)
- Re-check: `docs/superpowers/specs/2026-04-15-self-improve-subagent-skill-learning-design.md`

- [ ] **Step 1: Add/refresh docs only after behavior is green**

Document:
- review triggers are now real-time and runtime-owned
- background self-improve review uses the shipped subagent lane
- skill candidates are user-visible and promotion requires explicit confirmation

- [ ] **Step 2: Run targeted regression for touched surfaces**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_self_improve_trigger_evaluator tests.test_self_improve_review_dispatcher tests.test_self_improve_skill_candidates tests.test_self_improve_promotion tests.tools.test_self_improve_tool tests.tools.test_self_improve_tool_skill_candidates tests.test_subagent_service tests.test_subagent_runtime_loop tests.test_subagent_integration tests.contracts.test_runtime_contracts tests.contracts.test_gateway_contracts tests.test_skills`

Expected: PASS

- [ ] **Step 3: Run broader runtime/gateway regression**

Run: `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_gateway tests.test_acceptance tests.contracts.test_runtime_contracts tests.contracts.test_gateway_contracts tests.test_event_loop_cleanup tests.test_subagent_service tests.tools.test_subagent_tools tests.test_subagent_integration tests.test_subagent_runtime_loop tests.tools.test_self_improve_tool tests.tools.test_self_improve_tool_skill_candidates tests.test_self_improve_gate tests.test_self_improve_trigger_evaluator tests.test_self_improve_review_dispatcher tests.test_self_improve_skill_candidates tests.test_self_improve_promotion tests.test_skills`

Expected: PASS

- [ ] **Step 4: Optional live/runtime smoke after local green**

If local runtime environment is available, validate one narrow path:
- trigger-producing turn completes normally
- runtime later spawns review child without polluting main transcript
- one pending skill candidate becomes visible through `self_improve`
- promotion after explicit confirmation writes discoverable `skills/<slug>/SKILL.md`

- [ ] **Step 5: Commit**

```bash
git add STATUS.md docs/ARCHITECTURE_CHANGELOG.md docs/README.md docs/LIVE_VERIFICATION_CHECKLIST.md
git commit -m "docs: record self-improve review and skill candidate runtime"
```

---

## Execution notes for agentic workers

- Execute chunks in order; later chunks assume earlier schema/runtime contracts already exist.
- Do not widen scope into generic memory, user profiling, or automatic prompt rewriting.
- Keep the review child deterministic and heavily constrained; if a capability is not explicitly listed in the spec, do not grant it by default.
- When uncertain whether logic belongs in `SelfImproveService` vs a new helper module, prefer a new focused helper module rather than bloating the existing lesson gate.
- If a test reveals the runtime loop lacks a clean “after user-facing turn commit” hook, add the narrowest possible callback seam and stop there.

## Plan completion criteria

This plan is complete when:

1. the file exists at the expected path and matches the approved spec boundaries
2. the chunk order follows the real dependency chain in the current repo
3. each chunk names exact files, tests, and proof commands
4. the plan keeps one management surface (`self_improve`) and one background execution substrate (subagent lane)
5. the plan does not introduce fallback/planner/memory-platform drift
