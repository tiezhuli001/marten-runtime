# 2026-04-09 Pre-Commit Closure And Evolution Design

## 1. Background

This document defines the **pre-commit closure design** for the current `marten-runtime` iteration.

This is **not** a new feature design cycle and **not** a greenfield architecture redesign. The runtime already completed the main implementation slice for:

- context usage accuracy
- thin cross-turn tool outcome continuity
- tool-episode summary with thin fallback
- Feishu history cleanliness
- live/runtime hardening around several real failure paths

The current stage is a **submission-preparation closure pass**:

- align docs with the actual implementation
- tighten confirmed architecture-boundary risks without changing the validated runtime baseline
- fix a small number of hygiene issues
- explicitly separate **current closure work** from **future evolution work**

This document is intended to keep the next execution plan inside a narrow, controlled boundary.

---

## 2. Decision Context

### 2.1 Authoritative inputs

This design is based on the current codebase plus the already-reviewed local continuity and review materials:

- `docs/architecture/adr/0001-thin-harness-boundary.md`
- `docs/architecture/adr/0002-progressive-disclosure-default-surface.md`
- `docs/2026-04-07-context-usage-accuracy-design.md`
- `docs/2026-04-07-llm-tool-episode-summary-design.md`
- local `STATUS.md`
- local review and handoff notes dated `2026-04-08` and `2026-04-09`

### 2.2 Current baseline facts

The current implementation baseline is already materially validated.

Confirmed facts:

1. No deterministic, submission-blocking bug has been confirmed in the current reviewed baseline.
2. The current runtime behavior is covered by focused regression tests and broader runtime/gateway/Feishu/MCP regression runs.
3. Several runtime fast paths and recovery paths were introduced to solve **real observed live-chain problems**, not hypothetical architecture concerns.
4. The current risk is **not** that the runtime is completely off-track; the current risk is that a valid thin harness may continue drifting toward heavier host-side routing if the next changes are not constrained.

### 2.3 Confirmed issues

The following issues are confirmed and should shape the closure work:

1. **Documentation drift exists**
   - `docs/ARCHITECTURE_CHANGELOG.md` currently contains at least one statement that does not match code and tests.
2. **Boundary tension exists in host-side fast paths**
   - `src/marten_runtime/runtime/loop.py` contains forced tool-routing logic and query matchers that create real tension with ADR 0001.
3. **Logic duplication exists**
   - several query-detection helpers are duplicated across `runtime/loop.py` and `runtime/llm_client.py`.
4. **Minor hygiene issues exist**
   - an absolute test path
   - empty directory shells
   - a small number of low-value/noise statements that can be cleaned up without changing runtime semantics

---

## 3. Problem Statement

The current codebase is close to submission, but the next execution slice can still go wrong in two ways:

1. **under-correction**
   - leave obvious doc drift and duplicated logic in place, increasing future confusion and accidental behavior drift
2. **over-correction**
   - treat the current validated runtime hardening as architectural failure and trigger a pre-commit redesign, removing or destabilizing live-proven behavior

The design goal is therefore:

> perform a narrow pre-commit closure pass that improves truthfulness, boundary clarity, and maintainability without widening the runtime or destabilizing the validated behavior.

---

## 4. Goals

This closure pass has exactly five goals.

### 4.1 Goal A — Align architecture-facing docs with runtime truth

Repository architecture docs must describe the current implemented behavior accurately, especially where recent live hardening changed behavior.

### 4.2 Goal B — Tighten boundary expression around fast paths

The code should make it clearer that the existing host-side shortcuts are **narrow hardening primitives**, not an invitation to grow a host-side intent-routing subsystem.

### 4.3 Goal C — Remove unnecessary duplication in query detection

Duplicated matcher logic should be reduced to a single source of truth where practical, without introducing a new heavy “intent detector” layer.

### 4.4 Goal D — Apply low-risk hygiene fixes

Small cleanup items that improve maintainability or portability should be completed if they do not widen scope.

### 4.5 Goal E — Separate current closure work from future evolution

The repository must clearly record which issues are intentionally deferred to a later branch.

---

## 5. Non-Goals

The following are explicitly **out of scope** for this branch.

### 5.1 No fast-path removal campaign

This branch will **not** remove the current runtime fast paths simply because they create architectural tension.

If a fast path is already backed by tests and live evidence, it should remain unless a concrete regression-safe replacement exists.

### 5.2 No major `loop.py` refactor

This branch will **not** split `runtime/loop.py` into multiple modules as a structural redesign.

Small helper extraction or local deduplication is acceptable. Large decomposition is deferred.

### 5.3 No new host-side intent subsystem

This branch will **not** add:

- a planner layer
- an intent router
- a policy center
- a generic query-classification subsystem
- an “intent_detector.py” style architecture expansion

### 5.4 No broad capability-surface redesign

This branch will **not** rework capability declarations, tool-family abstractions, or channel architecture beyond narrow closure fixes.

### 5.5 No unrelated cleanup wave

This branch will **not** use the review as justification for broad cleanup work such as:

- builtins reorganization
- generic base-store extraction
- package export reshaping
- aesthetic refactors unrelated to closure goals

---

## 6. Design Principles And Constraints

### 6.1 Thin harness boundary remains authoritative

ADR 0001 remains the primary architecture constraint.

The runtime host must not grow into:

- a turn-level message classifier
- a host-side intent router
- a framework center that keeps absorbing domain decisions

However, already-validated thin hardening primitives may remain in place for now if they solve real runtime correctness or live-stability problems.

### 6.2 Evidence beats aesthetics

The existing validated runtime chain, tests, and live evidence have higher priority than architecture-aesthetic cleanup.

Execution must not destabilize behavior merely to make the code look purer.

### 6.3 Smallest-change rule

When multiple fixes are possible, prefer the one that:

- changes the fewest semantics
- changes the fewest files
- preserves current tests and live assumptions
- best clarifies the boundary without opening a new subsystem

### 6.4 Truthful docs are part of runtime correctness

Architecture-facing docs that describe behavior incorrectly are not harmless. They create future implementation drift and must be corrected as part of closure.

### 6.5 Deferred evolution must be explicit

Any substantial improvement intentionally postponed must be recorded as deferred evolution, not left ambiguous.

---

## 7. Closure Design

## 7.1 Closure Workstream A — Documentation Alignment

### Scope

Update architecture-facing docs so they match the current tested implementation.

### Required changes

1. Correct the changelog description of explicit GitHub repo-query behavior.
2. Ensure the changelog distinguishes between:
   - direct MCP call + follow-up LLM
   - direct deterministic render
   - deterministic recovery from already-available tool results
3. Avoid wording that implies the repo metadata path already bypasses the follow-up LLM if current tests still show two LLM requests.

### Why this is first

This is the highest-confidence, lowest-risk correction and prevents future agents from “fixing” code to match an incorrect document.

---

## 7.2 Closure Workstream B — Boundary Tightening For Fast Paths

### Scope

Keep current fast paths, but tighten how the code expresses and limits them.

### Required changes

1. Clarify in code comments or adjacent structure that current forced routes are accepted **runtime hardening exceptions**, not a general routing model.
2. Make it harder for future changes to casually add more repo-specific or tool-family-specific matchers.
3. Avoid adding new route categories during this closure pass.

### Required framing

The current fast-path set should be treated as a narrow compatibility/hardening surface for already-observed cases such as:

- runtime context-status natural-language queries
- current-time natural-language queries
- narrow automation list/detail shortcuts
- narrow trending shortcut cases
- explicit GitHub latest-commit recovery/fallback cases already backed by tests

### Explicit limit

This branch must **not** expand that set.

---

## 7.3 Closure Workstream C — Matcher Deduplication Without New Subsystem Growth

### Scope

Reduce duplicated query-detection logic across:

- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/llm_client.py`

### Required changes

1. Consolidate duplicated helper logic where practical.
2. Preserve current behavior and test semantics.
3. Keep the solution local and thin.

### Constraint

Do **not** introduce a new high-ceremony intent-classification module or framework abstraction.

The purpose is to reduce duplicate truth, not to formalize a larger host-side routing system.

---

## 7.4 Closure Workstream D — Request-Specific Instruction Tightening

### Scope

Review `_request_specific_instruction(...)` in `src/marten_runtime/runtime/llm_client.py` and reduce avoidable over-specification while preserving the current thin hardening value.

### Desired result

The instruction layer should remain:

- thin
- bounded
- purpose-specific
- obviously subordinate to the runtime harness

It should not read like a host-side planner that fully scripts the model’s tool payload.

### Constraint

If removing or weakening any instruction changes tested or live-proven behavior, preserve behavior and defer the stronger redesign to the evolution track.

---

## 7.5 Closure Workstream E — Low-Risk Hygiene

### Scope

Apply only hygiene fixes that are clearly bounded and low-risk.

### In scope

1. Replace machine-specific absolute test paths with repository-relative path construction.
2. Remove empty directory shells that no longer represent active code.
3. Remove obviously no-op or misleading noise statements where the change is behavior-neutral.

### Out of scope

1. broad exception-handling style rewrites
2. package-level cleanup unrelated to current risk
3. cosmetic file reorganization

---

## 8. File-Level Intent

The expected closure work should stay concentrated in the following files or areas.

### Primary files

- `docs/ARCHITECTURE_CHANGELOG.md`
- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/llm_client.py`
- `tests/test_runtime_loop.py`
- `tests/test_skills.py`

### Secondary files

- `STATUS.md`
- empty directory cleanup under removed code areas

### Guardrail

If execution begins touching many additional subsystems, that is a scope warning and should be reconsidered.

---

## 9. Verification Requirements

No closure change should be considered complete without evidence.

### 9.1 Minimum regression baseline

At minimum, run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp
```

### 9.2 If matcher/instruction logic changes

If any query matcher, forced route, or request-specific instruction logic changes, the same baseline remains mandatory.

### 9.3 If only docs/hygiene change

If a change is strictly documentation-only or behavior-neutral hygiene, run the best relevant lightweight verification available and state what was or was not re-run.

### 9.4 Required success criteria

Closure verification should preserve at least these semantic properties:

- existing fast-path tests remain green
- GitHub explicit repo metadata path remains accurately documented
- cross-turn summary behavior remains unchanged
- runtime context-status shortcut behavior remains unchanged
- trending / automation / time shortcut behavior remains unchanged
- deterministic recovery behavior remains unchanged

---

## 10. Risk Controls

### 10.1 Primary risk

A well-intentioned cleanup may accidentally change runtime semantics in areas that are now backed by real live evidence.

### 10.2 Risk-control rule

If a “cleanup” changes any of the following without explicit design approval, it is too large for this branch:

- `llm_request_count` shape on covered flows
- fast-path routing presence/absence
- deterministic recovery usage after successful tool execution
- current direct-render surface

### 10.3 Fallback rule

If a proposed cleanup cannot be made behavior-preserving with confidence, fall back to:

- doc correction
- code comments/boundary clarification
- narrow deduplication only

---

## 11. Deferred Evolution

The following work is intentionally **not** part of this branch, but should be carried forward as the next evolution branch.

### 11.1 Fast-path exit strategy

A later branch should define, for each host-side fast path:

- why it still exists
- what live/runtime evidence justifies it
- what replacement or capability improvement would allow it to shrink or disappear
- what tests and live checks are required before removal

This should create an explicit exit strategy instead of leaving the current shortcuts as permanent informal behavior.

### 11.2 Controlled `loop.py` decomposition

A later branch may perform a controlled structural split of `runtime/loop.py`, but only with a narrow plan.

Likely decomposition candidates include:

- forced-route and matcher helpers
- deterministic direct-render helpers
- tool-outcome summary glue
- recovery-only logic

The decomposition must preserve thin harness behavior and must not become an excuse to build a new architecture layer.

### 11.3 Capability and instruction surface tightening

A later branch may revisit:

- whether capability descriptions are too imperative
- whether request-specific instruction text can be made more declarative
- whether channel-specific guards should move closer to channel-owned boundaries

This should be done only with explicit live-safety validation.

### 11.4 Further cleanup candidates intentionally deferred

The following ideas are explicitly postponed and should not leak into the closure branch:

- generic base SQLite store extraction
- builtins file consolidation
- package export cleanup such as `__init__.py` shaping
- broad style/exception-handling normalization

---

## 12. Execution Boundary For The Next Plan

The implementation plan generated from this design must obey the following execution boundary:

1. **Do the closure items first.**
2. **Do not mix in deferred evolution work.**
3. **Prefer doc correction before code restructuring.**
4. **Prefer behavior-preserving deduplication over architecture cleanup.**
5. **Stop if a change starts behaving like a redesign rather than a closure pass.**

A valid execution plan derived from this design should therefore remain a **small, submission-focused plan**, not a general runtime refactor plan.

---

## 13. STATUS Recording Requirement

`STATUS.md` should explicitly record:

1. this design document was written for the pre-commit closure pass
2. the current branch is limited to closure work
3. evolution items were intentionally deferred
4. the next branch should focus specifically on the deferred evolution track

This is required so later work does not accidentally reopen the current branch scope.
