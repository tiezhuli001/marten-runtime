# Self-Improve / Subagent Review / Skill Candidate Design

## Goal

Design a Hermes-informed but `marten-runtime`-native evolution path for runtime learning that improves automation, user visibility, and procedural knowledge capture without turning the runtime into a generic memory platform or silently mutating bootstrap truth.

This design covers three requested capability upgrades:

1. real-time enhancement of the existing lesson mechanism
2. background isolated self-improve review
3. `skill_candidate + channel notification + user confirmation`

It also records one prerequisite architecture decision driven by current repository reality and the user's preference:

- `marten-runtime` should add a thin subagent substrate first, then build background review on top of that substrate instead of permanently coupling review to automation-only dispatch

## Summary Decision

The recommended target state is:

- **lesson** remains the narrow runtime-learning surface for short, stable execution rules
- **skill candidates** become the narrow procedural-learning surface for reusable workflows
- **background review** should eventually run through a thin subagent runtime, not a heavy planner/swarm system
- **system prompt assets stay stable**: do not auto-edit `AGENTS.md`, bootstrap prompt files, identity files, or other source-of-truth prompt assets
- **skills stay self-contained**: if a promoted skill is good enough, its summary/body plus the existing selector/loading flow should be sufficient for future model use; system prompt only needs to keep the stable “how to find/use skills” protocol

## Why This Design Exists

Current `marten-runtime` already implements a narrow lesson loop:

- runtime failures and recoveries are recorded
- `self_improve_internal` automation can synthesize lesson candidates
- accepted lessons are exported into runtime-managed `SYSTEM_LESSONS.md`
- the main agent can inspect and delete lesson candidates through the `self_improve` family tool

That baseline is useful, but it is still batch-oriented and relatively invisible:

- lesson generation is primarily driven by the internal daily automation
- there is no real-time trigger model for “this turn just taught us something”
- there is no separate procedural-learning surface for longer reusable workflows
- there is no user-visible review/acceptance path for newly discovered reusable procedures

Hermes Agent shows a stronger learning loop by combining:

- event/interval nudges
- background review
- memory persistence before context loss
- procedural memory captured as skills

However, Hermes is a broader agent shell than `marten-runtime`. The right move is not a direct port; it is a narrow adaptation that respects the current repository's thin-harness goals.

## Current Repository Reality

### What already exists

`marten-runtime` already has these ingredients:

- `SelfImproveRecorder` records failures and later recoveries from the runtime path
- `SelfImproveService` judges pending lesson candidates and exports active runtime lessons into `SYSTEM_LESSONS.md`
- `self_improve_internal` is an internal automation job created at bootstrap time
- the HTTP/runtime path already supports isolated automation turns through `AutomationJob.session_target = "isolated"`
- skill discovery already works through `SkillService`, visible skill summaries, and on-demand skill loading
- runtime diagnostics already expose a self-improve status surface

### What does *not* already exist

The repository does **not** currently expose a mature parent/child subagent runtime. There is no current source-of-truth implementation for:

- spawning a child agent with an isolated run/session and explicit parent linkage
- returning structured child results back into a parent conversation contract
- child-agent scheduling, lifecycle, or result correlation as a stable runtime subsystem
- planner/swarm-style orchestration (explicitly deferred by repo docs)

### Consequence for this design

Background review should be designed as a **subagent-backed target architecture**, but this document explicitly treats that as dependent on a prior thin subagent substrate slice.

Until that substrate exists, review can still run through the existing isolated-internal-turn path for compatibility and incremental delivery. But the long-term design in this document assumes:

> background review is eventually a thin, internal, isolated **review subagent** capability — not a general planner, not a swarm, and not a workflow platform.

## Non-Goals

This design must not turn `marten-runtime` into:

- a generic long-term memory platform
- a user-profile modeling system like Honcho
- an architecture source-of-truth store
- a planner/swarm orchestration framework
- an automatic bootstrap prompt rewrite engine
- an automatic `AGENTS.md` editor
- an automatic promotion path that writes directly into official skills without user confirmation

Explicitly out of scope:

- generic USER memory, broad cross-session autobiographical memory, or personality modeling
- auto-editing `apps/<app_id>/AGENTS.md`, `BOOTSTRAP.md`, `IDENTITY.md`, `SOUL.md`, or any equivalent prompt asset
- auto-patching repository docs or ADRs from runtime learning
- auto-promoting low-confidence skill candidates into `skills/`

## Design Invariants

These invariants anchor all three proposals.

### Invariant 1: keep the harness thin

Learning must stay close to the active runtime chain:

`channel -> binding -> agent -> runtime -> LLM -> tool/skill -> LLM -> channel`

No new subsystem should become a control center that rewrites unrelated behavior.

### Invariant 2: learning outputs are split by type

There are two distinct learning outputs:

- **lesson**: short, stable, execution-level guidance that can safely influence runtime prompt material
- **skill candidate**: reusable procedural workflow that requires user-visible review and explicit promotion

### Invariant 3: prompt truth stays layered

- system prompt assets define stable behavioral protocol and skill-loading rules
- runtime-managed `SYSTEM_LESSONS.md` carries active runtime lessons only
- promoted skills carry reusable methods and workflows

No runtime learning mechanism should collapse these layers into a single mutable prompt blob.

### Invariant 4: evidence before learning

New learning artifacts must be grounded in observed runtime evidence, not free-form reflection.

### Invariant 5: user-visible skill promotion

Skill promotion must be user-visible and confirmable through channel/runtime interactions. Silent skill promotion is not allowed.

## Reference Comparison: Hermes vs. marten-runtime

### Hermes patterns worth borrowing

1. **event/interval-based learning triggers**
   - Hermes tracks memory and skill nudges during the conversation loop
2. **background review after task completion**
   - Hermes uses a separate review flow so learning does not compete with the user's primary task
3. **pre-context-loss persistence**
   - Hermes flushes memory before compression/reset so important learning is not lost
4. **procedural memory as skills**
   - Hermes distinguishes between broad memory and reusable how-to knowledge

### Hermes patterns not appropriate to copy directly

1. **broad memory platform semantics**
   - `marten-runtime` should remain a narrow runtime-learning system, not a general memory layer
2. **direct official skill mutation by the learning loop**
   - `marten-runtime` should use `skill_candidate` + explicit promotion instead
3. **broader identity/profile modeling**
   - out of scope for the current repository target
4. **heavy parent/child orchestration runtime as a prerequisite for all learning**
   - the repo should only add the minimum thin subagent substrate needed for isolated review

## High-Level Architecture

The target architecture adds one prerequisite and three learning slices.

### Stage 0: thin subagent substrate (prerequisite)

Add a minimal internal subagent capability sufficient for background review.

This stage is not a planner system. It only needs to support:

- spawning a child review agent with isolated session state
- passing a structured review payload
- capturing child result status and payload
- correlating child review output back to the originating parent run/session
- enforcing restricted tool/skill access for review-specific work

### Stage 1: real-time lesson trigger evaluation

Augment the current lesson system with trigger evaluation so review opportunities are detected near the moment of evidence creation.

### Stage 2: background review execution

Run self-improve review in an isolated review agent (or compatibility shim using isolated internal turns until subagent support exists).

### Stage 3: skill candidate lifecycle

When background review detects reusable procedural knowledge, create a `skill_candidate`, notify the user through channel delivery, and require explicit user confirmation before promotion into official `skills/`.

## Proposal 1 — Real-Time Enhancement of the Existing Lesson Mechanism

## Objective

Keep the current lesson model, data store, and `SYSTEM_LESSONS.md` export, but make review opportunities more immediate and more selective.

## Current baseline

Current lesson flow is approximately:

1. runtime loop records `FailureEvent`
2. later successful run may record `RecoveryEvent`
3. internal `self_improve_internal` automation runs
4. dedicated `self_improve` skill/tool synthesize pending lesson candidates
5. `SelfImproveService.process_pending_candidates()` judges and exports active lessons

This baseline is useful but delayed.

## New design: `SelfImproveTriggerEvaluator`

Introduce a narrow evaluator component that watches runtime outcomes and decides whether a review opportunity should be enqueued.

### Responsibilities

Input:

- latest run outcome
- latest failure/recovery evidence
- optional tool-episode summaries
- optional compaction pressure signal

Output:

- zero or more **review triggers**

### Proposed trigger types

#### 1. `lesson_recovery_threshold`

Trigger when:

- one fingerprint has repeated failures within a recent window
- and at least one later recovery exists for the same fingerprint

Purpose:
- produce a high-confidence lesson candidate from evidence that already demonstrates recovery

#### 2. `lesson_failure_burst`

Trigger when:

- one fingerprint fails repeatedly inside a short window
- but recovery has not yet happened

Purpose:
- allow early review of a recurring failure pattern
- generate low-confidence pending lesson candidates or structured evidence summaries
- do **not** auto-accept based only on repeated failure without later successful evidence

#### 3. `pre_compaction_learning_flush`

Trigger when:

- compaction is about to occur
- and there is recent unreviewed evidence likely to be useful for runtime learning

Purpose:
- preserve narrow runtime-learning evidence before context is compressed away

#### 4. `complex_successful_tool_episode`

Trigger when:

- a turn used multiple tools / multiple iterations / multiple follow-up repairs
- and ended successfully
- and tool outcome summaries indicate a reusable multi-step method

Purpose:
- hand the case to background review so it can decide between lesson output and `skill_candidate` output

## Trigger safeguards

To avoid noisy review storms:

- per-fingerprint cooldown
- per-session review budget
- per-agent review budget per time window
- dedupe by semantic fingerprint of the trigger payload
- skip if a closely matching pending lesson/skill candidate already exists

## Data additions for proposal 1

### `ReviewTrigger`

Suggested model:

- `trigger_id`
- `agent_id`
- `trigger_kind`
- `source_run_id`
- `source_trace_id`
- `source_fingerprints`
- `status` (`pending`, `queued`, `processed`, `expired`)
- `payload_json`
- `semantic_fingerprint`
- `created_at`

This becomes the queueable review intent record.

## Why this fits current code

This proposal is mostly additive to existing seams:

- `runtime/run_outcome_flow.py`
- `runtime/loop.py`
- `self_improve/recorder.py`
- `self_improve/sqlite_store.py`
- existing tool outcome summary flow

It does not require broad new orchestration.

## Proposal 2 — Background Isolated Self-Improve Review

## Objective

Borrow Hermes' “background review” idea, but fit it into `marten-runtime`'s narrower architecture.

## Key decision

The target architecture is **review subagent**, not general automation-only review. But because subagent support is not yet a stable repository capability, this proposal is intentionally split into:

- target architecture
- compatibility execution path

## 2A. Target architecture: internal review subagent

### What the review subagent is

A review subagent is a narrowly scoped internal child agent whose only job is to inspect a structured review payload and emit learning proposals.

It is **not**:

- a general worker scheduler
- a planner
- a multi-step branch executor
- a source-code modification agent

### Required capabilities

The thin review subagent substrate only needs to support:

- spawn child with isolated session/run identity
- pass a structured parent-linked review payload
- restrict tools/skills visible to the child
- return one structured result payload
- record parent-child correlation in diagnostics

### Review subagent inputs

The child should not receive an unbounded raw conversation transcript by default. It should receive a compact structured review package:

- trigger kind and trigger reason
- source run summary
- recent failures/recoveries for the relevant fingerprint(s)
- recent tool-episode summaries if present
- currently active runtime lessons summary
- current pending lesson candidates summary
- current pending skill candidates summary
- currently visible skill summaries (summary-only, not all bodies)

### Review subagent outputs

Structured output should allow both lesson and skill proposals in one pass:

- `lesson_proposals[]`
- `skill_proposals[]`
- optional `nothing_to_save_reason`

The review agent is a proposal producer, not the final gate.

## 2B. Compatibility path before subagent support exists

Until thin subagent support lands, the repository can emulate review execution with the existing isolated internal-turn machinery:

- internal automation-like dispatch
- isolated session target
- dedicated review skill id
- final result written into the same review-output store

Important: this is a compatibility path only. The design record should still preserve the subagent-backed target architecture so the repository does not accidentally hard-code learning forever into automation dispatch.

## Review execution contract

### Review skills

Introduce one dedicated review skill, for example:

- `self_improve_review`

This skill should be allowed to:

- inspect self-improve evidence
- inspect lesson candidates and active lessons
- inspect skill candidate summaries
- save lesson candidates
- save skill candidates

It must not:

- edit prompt assets
- edit AGENTS/bootstrap files
- directly promote skills into the official skill directory

## Review result handling

After review execution:

- lesson proposals are written as pending `LessonCandidate`s and processed by the existing gate/judge path
- skill proposals are written as pending `SkillCandidate`s and routed into the user-notification flow

## Correlation and diagnostics

Each review execution should be traceable from:

- parent run id / trace id
- trigger id
- review run id / child run id
- resulting lesson candidate ids
- resulting skill candidate ids

This makes review observable without exposing raw internals to end users.

## Proposal 3 — Skill Candidate + Channel Notification + User Confirmation

## Objective

Introduce a procedural-learning surface that is richer than lessons but safer than automatic skill mutation.

## Why skills are a separate output class

Lessons are appropriate for:

- short rules
- execution heuristics
- stable recovery reminders
- compact runtime-learning guidance

Skills are appropriate for:

- multi-step workflows
- reusable procedural methods
- task-type-specific strategies
- pitfalls and verification guidance

Trying to encode rich procedural knowledge into `SYSTEM_LESSONS.md` would over-expand the lesson surface and duplicate skill-system responsibilities.

## Core decision

`marten-runtime` should add **skill candidates**, not automatic direct skill creation.

### Confirmation strategy

Per user confirmation, use strategy **B**:

- auto-create pending skill candidates
- store them outside the official `skills/` surface
- notify the user through the relevant channel/runtime path
- only promote into official `skills/` after explicit user confirmation

## `SkillCandidate` model

Suggested fields:

- `candidate_id`
- `agent_id`
- `status` (`pending`, `accepted`, `rejected`, `promoted`)
- `title`
- `slug`
- `summary`
- `trigger_conditions`
- `body_markdown`
- `rationale`
- `source_run_ids`
- `source_fingerprints`
- `confidence`
- `semantic_fingerprint`
- `created_at`
- `reviewed_at`
- `promoted_skill_id`

The generated `body_markdown` should already resemble a minimal valid `SKILL.md` candidate body so user review and later promotion remain cheap.

## Storage boundary

The candidate should **not** live in official `skills/` before confirmation.

Recommended storage options:

- same self-improve SQLite domain (preferred for unified learning storage)
- or a parallel skill-candidate table within the same DB file

Do **not** use a git-tracked repo directory as the pending candidate store.

## Channel notification flow

When a new pending skill candidate is created:

1. mark candidate as `pending`
2. create a lightweight notification event
3. deliver one user-visible notification through the originating channel if safe
4. allow later inspection through the normal runtime path

### Notification style

The notification should be short and user-facing, for example:

- “我总结了一个新的 skill 候选：`provider-timeout-recovery`。要不要我展示详情？”
- “这次复杂问题形成了一个可复用 workflow，我已生成 skill 候选，可随时查看或采纳。”

### Notification constraints

- no raw SQL / table names / internal store details
- no spam: one notification per semantic candidate per cooldown window
- no silent promotion

## User-facing management flow

Add a narrow management surface similar to current `self_improve_management`, but for skill candidates.

### User operations

- list candidates
- candidate detail
- accept candidate
- reject candidate
- optionally edit candidate before acceptance
- promote accepted candidate into official `skills/`

### Promotion behavior

Promotion writes a new official skill only after explicit confirmation.

Suggested path:

- `skills/<slug>/SKILL.md`

Optional supporting files can be deferred until later phases. Initial promotion should remain narrow:

- one `SKILL.md`
- no prompt-asset updates
- no automatic category reorganization

## Skill visibility after promotion

Once promoted:

- the normal `SkillService` snapshot/selector path should make the skill discoverable
- the system prompt does not need to absorb the skill content
- the existing summary-first selector remains the discovery mechanism

This preserves the layered prompt model:

- system prompt defines skill-usage protocol
- skill summaries trigger selection
- skill bodies are loaded on demand

## Prompt Boundary Decision

## Stable system prompt behavior

The default main agent prompt should continue to say, in effect:

- skills are visible in the skill directory
- read summaries first
- load a skill body only when relevant
- do not expand every skill in advance

## Explicitly rejected prompt behavior

Do not automatically:

- inject promoted skill bodies into system prompt
- rewrite bootstrap prompt assets because a skill was promoted
- mirror skill candidate contents into `SYSTEM_LESSONS.md`

## Why this is the right boundary

If a promoted skill is genuinely good enough, it should be usable through:

- its summary
- the existing selector
- on-demand body loading

Duplicating that content into system prompt assets would create drift and merge two truth layers that should stay separate.

## Recommended Phasing

Although the user asked for a single combined design, the implementation order should be staged.

### Phase 0 — thin subagent substrate (prerequisite)

Add the narrow internal review-subagent substrate.

Done when:

- internal child review execution exists
- child review is isolated and correlated to the parent run
- child review can return structured proposals
- no planner/swarm/general worker semantics are introduced

### Phase 1 — real-time lesson triggers

Add `SelfImproveTriggerEvaluator` and review-trigger persistence.

Done when:

- repeated failure/recovery patterns can enqueue immediate review opportunities
- daily automation remains as a fallback scanner, not the only trigger

### Phase 2 — review execution path

Run isolated background review for pending triggers.

Done when:

- review turn can emit lesson proposals and skill proposals
- review output is stored in narrow candidate stores

### Phase 3 — skill candidate lifecycle

Add candidate notification, inspection, confirmation, and promotion.

Done when:

- user can inspect pending skill candidates from channel/runtime path
- user can accept/reject/promote
- promotion writes official `skills/<slug>/SKILL.md`
- no prompt assets are auto-mutated

## Repository Fit Check

This design aligns with current repository goals because:

- it preserves the thin-harness role
- it reuses the current lesson mechanism instead of replacing it
- it treats subagent review as a narrow internal capability, not planner expansion
- it keeps `SYSTEM_LESSONS.md` scoped to active runtime lessons only
- it keeps prompt truth layered and stable
- it keeps official skill surface user-governed

## Risks and Mitigations

### Risk 1: accidental planner/swarm drift

Mitigation:
- constrain subagent substrate to internal review only in the first slice
- forbid general task planning or multi-agent branch execution in this feature line

### Risk 2: noisy or low-quality skill candidates

Mitigation:
- require evidence thresholds and semantic dedupe
- keep candidates pending until user confirmation
- provide reject/edit management tools

### Risk 3: user-visible notification spam

Mitigation:
- per-candidate cooldown
- dedupe by semantic fingerprint
- one concise notification per candidate lifecycle stage

### Risk 4: prompt drift

Mitigation:
- explicitly block prompt asset edits from the review capability
- treat skills as independent runtime capability artifacts

### Risk 5: lesson/skill overlap

Mitigation:
- use proposal classification rules:
  - short stable rule -> lesson
  - reusable workflow / multi-step method -> skill candidate

## Acceptance Criteria for the Design

This design is acceptable when the repository can eventually support all of the following without violating current architecture boundaries:

1. the existing lesson system can trigger review in near real time, not only through daily batch automation
2. background review runs in isolated execution without polluting the parent user session
3. the long-term design supports a thin review subagent substrate rather than a heavy planner runtime
4. reusable workflows can be captured as `skill_candidate`s
5. new skill candidates are user-visible through channel/runtime notifications
6. official skill promotion requires explicit user confirmation
7. promoted skills remain discoverable through the normal skill summary/selector/body-loading flow
8. no automatic mutation of `AGENTS.md`, bootstrap prompt files, or identity assets occurs
9. `SYSTEM_LESSONS.md` remains active-runtime-lessons-only, not a procedural memory dump

## Recommended Document Follow-Up

If this design is approved, the next planning document should explicitly separate:

- **Phase 0 plan**: thin review-subagent substrate
- **Phase 1 plan**: real-time lesson triggers + compatibility review execution
- **Phase 2 plan**: full skill-candidate notification/confirmation/promotion flow

That keeps the implementation path aligned with the current codebase and with the user's stated priority of considering subagent support before full self-improve expansion.
