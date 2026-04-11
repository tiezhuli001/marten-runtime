# 2026-04-09 Next-Branch Evolution Design

## 1. Background

The current branch completed the pre-commit closure pass and intentionally deferred broader runtime evolution.

The closure branch preserved the validated runtime baseline, including:

- thin hardening fast paths already backed by tests and live verification
- explicit GitHub MCP recovery and follow-up behavior
- current request-specific instruction shaping
- the current `runtime/loop.py` structure except for low-risk deduplication

The next branch should therefore focus on **controlled evolution**, not another cleanup pass and not a greenfield redesign.

This document defines that next-branch evolution boundary so later implementation does not drift into unbounded refactor work.

---

## 2. Baseline Facts Carried Forward

The following baseline is assumed true and is part of the design contract for the evolution branch:

1. The runtime already has a working end-to-end chain across plain sessions, builtin tools, GitHub MCP tools, and skill loading.
2. Several host-side fast paths exist because they solved real observed failures, not because of speculative architecture preferences.
3. The current branch must not be reopened to redo closure work.
4. The evolution branch may restructure internals, but only if it preserves externally validated behavior or replaces it with equally verified behavior.

### 2.1 Newly confirmed runtime diagnostics fact

`/diagnostics/runtime` now distinguishes:

- the **effective observed** server surface for the current request
- the **configured** server surface from `platform.toml` / env

This observability fix is now part of the baseline and should remain intact during future evolution.

---

## 3. Problem Statement

The runtime is currently effective but still carries three structural tensions:

1. **fast paths have no explicit exit strategy**
   - they exist, but the repo does not yet state which ones are permanent, temporary, or removable under what proof
2. **`runtime/loop.py` still concentrates too many responsibilities**
   - matcher checks, direct render helpers, recovery logic, tool routing exceptions, and control flow remain tightly co-located
3. **capability / instruction / channel boundaries are still looser than they should be**
   - some behavior is enforced in places that are harder to reason about or harder to validate in isolation

The next branch must reduce these tensions **without** replacing the thin harness with a heavier planner/router architecture.

---

## 4. Branch Goal

> Make the runtime easier to reason about, easier to verify, and easier to evolve by introducing an explicit fast-path exit strategy, a controlled `runtime/loop.py` decomposition, and tighter capability/instruction/channel ownership boundaries, while preserving the validated runtime behavior.

### 4.1 Execution phasing rule

This branch is intentionally split into **Stage 1** and **Stage 2** so implementation does not drift into premature restructuring.

#### Stage 1 — Boundary locking and baseline preparation

Stage 1 is limited to:

- writing the fast-path inventory and exit-strategy baseline
- locking current behavior with focused tests
- tightening the design and execution boundaries for later implementation
- preparing the exact inputs needed for later code-moving work

Stage 1 must **not**:

- remove any fast path
- finalize per-item fast-path keep/remove decisions
- perform function-level `runtime/loop.py` extraction
- change runtime semantics

#### Stage 2 — Controlled implementation after baseline lock

Stage 2 starts only after Stage 1 is completed and verified.

Stage 2 may:

- make per-item fast-path retain / shrink / remove decisions
- record any accepted architecture deviation explicitly if a fast path must remain
- execute function-level `runtime/loop.py` decomposition
- tighten capability / instruction / channel boundaries in code

---

## 5. Scope

This branch has exactly three in-scope workstreams.

### 5.1 Workstream A — Fast-path inventory and exit strategy

Create a single authoritative inventory of host-side fast paths and recovery-only shortcuts, and define for each one:

- current purpose
- current evidence
- owning boundary
- removal or shrink preconditions
- mandatory tests and live checks required before any change

#### Stage split for Workstream A

- **Stage 1:** produce the inventory and exit-strategy baseline only
- **Stage 2:** convert that inventory into a per-item decision matrix

### 5.2 Workstream B — Controlled `runtime/loop.py` decomposition

Split `runtime/loop.py` only along already-visible responsibility seams so that each moved slice remains thin and testable.

Allowed target seams include:

- matcher / forced-route helpers
- deterministic direct-render helpers
- recovery-only helpers
- tool-outcome-summary glue helpers

#### Stage split for Workstream B

- **Stage 1:** identify seams, lock tests, and define extraction preconditions
- **Stage 2:** perform function-level extraction in verified slices

#### Additional Stage 2 direction from review + discussion

- if `_is_*_query` logic remains necessary, prefer converging duplicated pure matchers into an existing shared helper boundary rather than introducing a new generic `intent_detector.py` subsystem
- the preferred landing zone is an extension of `query_hardening.py` or an equally thin shared helper module with the same non-goal guardrails
- the extraction target is **duplicate truth removal**, not a new routing center
- query helpers that still encode policy rather than pure matching must remain in `loop.py` until proven extractable

### 5.3 Workstream C — Capability / instruction / channel boundary tightening

Reduce ambiguous ownership by tightening where behavior is expressed:

- capability descriptions should stay descriptive, not script-like
- request-specific instructions should stay purpose-specific and minimal
- channel-specific rules should move closer to channel-owned boundaries when safe

#### Stage split for Workstream C

- **Stage 1:** identify concrete tightening targets and lock baseline behavior
- **Stage 2:** apply the tightening in isolated code slices

#### Additional Stage 2 direction from review + discussion

- the Feishu-specific card protocol guard currently in `runtime/llm_client.py` is now an explicit Stage 2 tightening target
- if safe, the guard must move closer to the Feishu channel-owned boundary so the core LLM client stops owning channel protocol knowledge
- this move is allowed only if the resulting boundary still preserves:
  - current HTTP vs Feishu behavior differences
  - current skill activation semantics
  - current live channel rendering expectations

---

## 6. Non-Goals

The next branch explicitly does **not** do the following.

### 6.1 No host-side planner or intent-router expansion

Do not add:

- a planner layer
- a generic intent router
- a policy center
- a broad message-classification subsystem
- an architecture whose main value is naming existing runtime branches

This explicitly includes:

- no `intent_detector.py` style subsystem that centralizes routing policy under a new abstraction layer
- no “shared helper” extraction whose real effect is to smuggle route policy out of `loop.py` while pretending it is only utility code

### 6.2 No feature expansion disguised as architecture work

Do not mix in unrelated new behavior such as:

- new tool families
- new channel products
- unrelated automation features
- new recovery categories not required by observed evidence

### 6.3 No cleanup wave unrelated to the three workstreams

Do not spend this branch on:

- base store extraction
- package export normalization
- broad style rewrites
- exception hierarchy redesign
- aesthetic re-organization outside touched seams

### 6.4 No silent semantics change

Any change that alters one of the following is out of bounds unless explicitly covered by tests and live verification:

- `llm_request_count` shape on covered flows
- fast-path routing presence/absence
- deterministic recovery usage
- plain/builtin/MCP/skill live-chain success paths
- diagnostics runtime observability fields

### 6.5 No premature Stage 2 work during Stage 1

During Stage 1, do **not** introduce:

- `route_hardening.py`
- `direct_rendering.py`
- `recovery_flow.py`
- `tool_outcome_flow.py`
- any function-level split blueprint that reads like approved implementation work

Stage 1 may reference these as future targets, but it must not act as though the split is already approved at function granularity.

---

## 7. Design Principles

### 7.1 Evidence-first evolution

Refactor only after the runtime truth is inventory-backed and test-locked.

### 7.2 Separate ownership, not behavior invention

The point of decomposition is to move existing behavior to clearer boundaries, not to invent new behavior.

### 7.3 One seam at a time

Each evolution slice should move one responsibility seam, verify it, then stop before the next seam.

### 7.4 Live-chain safety over purity

If a cleaner abstraction causes uncertainty on validated live paths, keep the thin explicit version until stronger evidence exists.

### 7.5 Diagnostics remain truthful

Runtime diagnostics must continue to expose the actual serving surface seen by the request, while keeping configured values visible for debugging.

---

## 8. Target Architecture Direction

The end state of this branch is **not** a new architecture. It is a clearer expression of the existing thin harness.

### 8.1 Expected ownership after the branch

- `runtime/loop.py`
  - keeps top-level orchestration and sequencing
  - stops owning every helper detail directly
- dedicated thin helper modules under `src/marten_runtime/runtime/`
  - own pure matching / forced-route eligibility logic
  - own deterministic direct-render helpers
  - own recovery-only decision helpers
  - own tool-outcome-summary composition helpers when those are pure or near-pure
- `runtime/llm_client.py`
  - owns request shaping only
  - does not duplicate host-side query semantics already defined elsewhere
  - does not permanently own Feishu channel protocol rules if they can be expressed at the channel boundary instead
- channel modules
  - own channel-specific rendering / guard behavior when the behavior is truly channel-local
  - are the preferred owner for Feishu card protocol enforcement if the extraction preserves current behavior

### 8.2 Guardrail

If the decomposition starts requiring cross-module policy negotiation or an orchestrating coordinator object, the split is too ambitious for this branch.

---

## 9. Workstream Details

## 9.1 Workstream A — Fast-path inventory and exit strategy

### Required outputs

1. one design-facing inventory document under `docs/`
2. inline code references or comments that point maintainers to the inventory
3. a test-backed classification of each fast path into one of:
   - retained with clear justification
   - shrink candidate
   - removable once replacement evidence exists

### Required explicit Stage 2 decisions from current discussion

The following items are no longer optional “maybe later” topics. Stage 2 must explicitly decide them:

1. whether the Feishu card protocol guard remains in `llm_client.py` temporarily or moves to the Feishu channel layer now
2. whether duplicated `_is_*_query` helpers are:
   - converged into a thin shared matcher helper boundary
   - partially converged while route policy stays in `loop.py`
   - intentionally left split for now with an explicit reason

These decisions must be written down before code movement that claims to resolve them.

## 9.2 Workstream B — Controlled `runtime/loop.py` decomposition

### Specific seam note: `_is_*_query` convergence

The review recommendation to merge duplicated `_is_*_query` logic is accepted only in the following constrained form:

- shared helper extraction is allowed for pure matchers such as:
  - runtime-context query detection
  - GitHub commit query detection
  - GitHub metadata query detection
- shared helper extraction is **not** approval to centralize:
  - forced-route policy
  - family-tool selection policy
  - pre-LLM tool-decision authority

#### Test boundary

Any `_is_*_query` convergence must preserve:

- current `tests/test_query_hardening.py`
- current GitHub request-shaping tests in `tests/test_llm_client.py`
- current runtime-loop forced-route regressions

If convergence changes meaning rather than just removing duplicate truth, it is not a safe Stage 2 move.

## 9.3 Workstream C — Capability / instruction / channel boundary tightening

### Specific seam note: Feishu guard migration

The review recommendation to move `_requires_feishu_card_protocol_guard` out of `llm_client.py` is accepted as a Stage 2 design target, with these boundaries:

- the move must reduce channel leakage into `llm_client.py`
- the move must not break the current always-on Feishu formatting skill behavior
- the move must not accidentally apply Feishu card protocol to HTTP traffic
- the move must not change current user-visible Feishu rendering without updated tests and live verification

#### Preferred end state

- channel-owned guard detection or guard materialization happens under the Feishu channel boundary
- `llm_client.py` receives already-resolved channel-specific instruction text or request metadata, rather than inferring Feishu protocol from skill ids directly

#### Test boundary

Any Feishu guard migration must preserve:

- `tests/test_llm_client.py`
- `tests/test_contract_compatibility.py`
- `tests/test_gateway.py` when channel injection behavior is involved
- `tests/test_feishu.py` for channel-owned live/render behavior

### Minimum inventory fields

For every fast path or recovery-only shortcut, record:

- path name
- current trigger shape
- current file/function owner
- why it exists
- what failure it protects against
- current automated tests
- required live verification if changed
- exit strategy

### Success criteria

No fast path remains undocumented or ownerless.

### Stage 2 required follow-up

After Stage 1 completes, Stage 2 must convert the inventory into a decision matrix that states for each fast path whether it is:

- retained for now
- a shrink candidate
- removable after replacement evidence
- an accepted deviation that must be recorded in ADR/changelog with exit conditions

---

## 9.2 Workstream B — Controlled `runtime/loop.py` decomposition

### Allowed extraction order

1. pure helper extraction first
2. deterministic direct-render helper extraction second
3. recovery-only helper extraction third
4. top-level loop simplification last

### Hard constraints

- no semantic widening during extraction
- no renaming for style alone if it obscures proof
- no module should depend on request-global mutable state unless it already did
- no extraction should require changing unrelated tool or channel code

### Success criteria

`runtime/loop.py` becomes easier to scan, with helper ownership clearer, while covered behavior remains unchanged.

### Stage 2 required follow-up

Stage 2 must produce a function-level split blueprint **before** moving code. That blueprint should map existing helpers to future module ownership and define the verification slice for each move.

---

## 9.3 Workstream C — Capability / instruction / channel boundary tightening

### Capability surface

Required direction:

- capability descriptions remain declarative
- capability descriptions stop sounding like a prescriptive script where avoidable
- description changes must not reduce tool-selection reliability on covered flows

### Request-specific instruction surface

Required direction:

- preserve hardening intent
- remove avoidable wording that over-specifies tool payloads or sequencing
- ensure instruction shaping remains obviously subordinate to the harness

### Channel boundary surface

Required direction:

- move channel-only behavior closer to channel modules when the move is behavior-preserving
- avoid storing channel protocol details in generic history or orchestration paths unless unavoidable

### Success criteria

Ownership becomes clearer without changing validated plain/builtin/MCP/skill live behavior.

---

## 10. Verification Requirements

No workstream is complete without both targeted and branch-level verification.

### 10.1 Per-slice verification

Every slice must include:

1. new or updated focused tests for the moved or tightened seam
2. the narrowest regression command covering that seam
3. if behavior is externally visible, one HTTP-level verification path

### 10.2 Required branch regression baseline

Run at minimum:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp tests.test_contract_compatibility
```

### 10.3 Required final live-chain verification

Run a source-backed HTTP runtime on an independent port and verify at least:

1. `GET /healthz`
2. `GET /diagnostics/runtime`
   - effective port/base URL correct
   - configured port/base URL still visible
3. plain `/messages`
4. builtin tool call
5. GitHub MCP tool call
6. skill load path

### 10.4 Failure rule

If any slice introduces uncertainty on live-chain behavior, stop the slice, revert to the last verified boundary, and reduce the change size.

---

## 11. Delivery Order

The next branch should execute in this order:

1. complete Stage 1 inventory and baseline locking
2. verify Stage 1 and record the approved implementation frontier
3. prepare Stage 2 decision matrix and function-level split blueprint
4. decompose the first `runtime/loop.py` seam
5. verify
6. decompose the next seam only if the previous one stayed green
7. tighten capability/instruction/channel boundaries in small slices
8. run full regression
9. run independent-port live verification

This order is mandatory because it prevents structural work from outpacing proof.

---

## 12. Risks And Controls

### 12.1 Main risk

A well-intentioned decomposition could silently change routing or recovery semantics.

### 12.2 Control

Before each slice, explicitly state:

- which seam is moving
- which user-visible behavior must remain identical
- which tests prove it
- which live check confirms it

### 12.3 Secondary risk

Capability/instruction tightening could make the model less reliable on edge cases that are currently protected by thin hardening.

### 12.4 Control

Do not combine wording reduction with structural moves in the same slice.

---

## 13. Done Criteria

This branch is done only when all of the following are true:

1. fast paths and recovery shortcuts have an explicit inventory and exit strategy
2. `runtime/loop.py` has been decomposed along at least the planned safe seams without goal drift
3. capability/instruction/channel ownership is tighter and documented
4. diagnostics runtime server fields remain truthful
5. targeted tests pass
6. required branch regression passes
7. independent-port live verification passes
8. `STATUS.md` records the evolution progress and any remaining deferred items

### 13.1 Stage 1 done criteria

Stage 1 is complete only when:

1. the inventory baseline document exists
2. Stage 1 tests lock the targeted seams without semantic drift
3. Stage 1 docs explicitly defer per-item fast-path decisions to Stage 2
4. Stage 1 docs explicitly defer function-level split blueprint to Stage 2
5. `STATUS.md` reflects that Stage 1 is complete and Stage 2 has not yet started
