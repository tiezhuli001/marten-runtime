# Feishu Generic Renderer Iteration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the current Feishu generic-card protocol implementation so responsibilities are cleanly split across LLM output, one generic renderer, and a thin delivery layer, while materially improving Feishu visual hierarchy without introducing renderer taxonomies.

**Architecture:** Keep the current `feishu_card` protocol and LLM-first direction, but move protocol parsing and card skeleton generation out of `delivery.py` into a dedicated generic renderer module. `delivery.py` must become a transport-oriented adapter again, with retry/update/dedupe/dead-letter behavior unchanged. The renderer must remain generic: one schema, one visual skeleton, no business content classifiers.

**Tech Stack:** Python, unittest, Pydantic, Feishu interactive card payloads, existing Feishu delivery client

---

## Scope And Completion Contract

This plan is complete only when all of the following are true:

- `delivery.py` no longer owns protocol parsing or card skeleton assembly
- one dedicated Feishu generic renderer module exists and is the sole owner of:
  - `feishu_card` trailing-block detection
  - protocol schema validation
  - visible-body stripping
  - generic card visual skeleton generation
- the renderer supports both:
  - no-structure fallback rendering
  - valid structured rendering
- malformed protocol payloads safely fall back without breaking delivery
- the Feishu formatting skill still keeps natural language as default and `feishu_card` optional
- targeted tests pass
- full `unittest` suite passes
- one local smoke validates the live runtime still starts and responds
- one real Feishu validation is performed and the resulting card is reviewed for visual improvement

This plan is **not** complete if the code merely passes tests but still leaves:

- protocol parsing in `delivery.py`
- duplicated rendering logic in both renderer and delivery
- business-specific card branches
- undocumented visual-slot behavior

## Chunk 1: Freeze The Current Baseline And Responsibility Target

### Task 1: Freeze the current renderer baseline before refactor

**Files:**
- Read: `docs/2026-04-01-feishu-generic-card-protocol-design.md`
- Read: `src/marten_runtime/channels/feishu/delivery.py`
- Read: `skills/feishu_channel_formatting/SKILL.md`
- Test: `tests/test_feishu.py`
- Test: `tests/test_skills.py`

- [ ] **Step 1: Confirm current branch and worktree**

Run: `git -C /Users/litiezhu/workspace/github/marten-runtime branch --show-current && git -C /Users/litiezhu/workspace/github/marten-runtime status --short`
Expected:
- current branch is not `main`
- current branch remains `codex/runtime-timing-feishu-plan`

- [ ] **Step 2: Run the focused current baseline**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_skills tests.test_contract_compatibility tests.test_runtime_loop -v`
Expected: PASS

- [ ] **Step 3: Freeze the non-negotiable contracts**

Must preserve:
- `progress -> hidden`
- `final -> interactive card`
- retry/update/send behavior
- duplicate-window suppression
- dead-letter recording
- Feishu skill remains always-on and Feishu-only
- malformed `feishu_card` payloads do not break final delivery

**Testing plan for Task 1**
- Focused suite above must pass before refactor starts.

**Exit condition for Task 1**
- The current behavior and the desired responsibility boundary are frozen.

## Chunk 2: Extract The Generic Renderer Module

### Task 2: Introduce one dedicated Feishu renderer module with no business taxonomy

**Files:**
- Create: `src/marten_runtime/channels/feishu/rendering.py`
- Modify: `tests/test_feishu.py`

- [ ] **Step 1: Write the failing renderer tests**

Add tests for:
- trailing `feishu_card` detection
- valid protocol parse
- invalid JSON fallback
- unsupported key fallback
- invalid field-type fallback
- visible-body stripping
- generic visual slot ordering

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: FAIL only on newly added renderer expectations

- [ ] **Step 2: Define narrow renderer data structures**

Required responsibilities in `rendering.py`:
- protocol schema models
- parse result helpers
- one renderer entrypoint for final Feishu replies

Disallowed:
- retry logic
- send/update logic
- business renderer selection

- [ ] **Step 3: Implement minimal parser and fallback logic**

Required outcomes:
- only trailing `feishu_card` block is parsed
- only the documented schema is accepted
- malformed blocks produce fallback result, not exception-driven delivery failure

- [ ] **Step 4: Implement one generic visual skeleton**

Required slots:
- optional header
- optional summary
- zero or more section titles
- flat item lists
- plain fallback body when no valid structure exists

Do not add:
- task/rule/check renderer families
- item-level metadata objects
- per-type layout branches

- [ ] **Step 5: Re-run focused renderer tests**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: PASS for new renderer-related tests

**Testing plan for Task 2**
- Focus on renderer-only expectations through `tests.test_feishu`.

**Exit condition for Task 2**
- One dedicated renderer module exists and covers both structured and fallback rendering.

## Chunk 3: Reduce `delivery.py` Back To Transport Semantics

### Task 3: Remove parsing and card-assembly responsibilities from `delivery.py`

**Files:**
- Modify: `src/marten_runtime/channels/feishu/delivery.py`
- Test: `tests/test_feishu.py`
- Test: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Write the failing delegation test**

Add or update tests that prove:
- final reply rendering delegates to the renderer
- `delivery.py` still preserves send/update/retry behavior

Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_contract_compatibility -v`
Expected: FAIL on delegation expectations until code is updated

- [ ] **Step 2: Replace direct rendering logic with renderer delegation**

Required outcome:
- `delivery.py` asks the renderer for final interactive-card payloads
- `delivery.py` keeps only transport-oriented branching

- [ ] **Step 3: Delete superseded inline parsing / skeleton code**

Required cleanup:
- no duplicate protocol regex/schema/helpers in `delivery.py`
- no card skeleton construction left in `delivery.py`

- [ ] **Step 4: Verify transport behavior still holds**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_contract_compatibility -v`
Expected: PASS

**Testing plan for Task 3**
- Must prove that refactor preserved behavior, not just module placement.

**Exit condition for Task 3**
- `delivery.py` becomes transport-only again, with renderer delegation and no leftover duplicate rendering logic.

## Chunk 4: Improve The Generic Visual Skeleton Without Expanding Schema

### Task 4: Upgrade the single renderer’s visual hierarchy

**Files:**
- Modify: `src/marten_runtime/channels/feishu/rendering.py`
- Test: `tests/test_feishu.py`

- [ ] **Step 1: Write failing tests for better visual hierarchy**

Add expectations for:
- title appears in header slot
- summary is visually separated from body
- section titles render separately from item bodies
- item list rendering is stable and compact

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: FAIL on new hierarchy assertions

- [ ] **Step 2: Implement the minimal visual upgrade**

Allowed:
- better slot ordering
- consistent element grouping
- stable `lark_md` formatting for summary and items
- generic separators if needed

Disallowed:
- new schema fields
- business-specific layout variants
- custom renderer selection

- [ ] **Step 3: Re-run Feishu tests**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu -v`
Expected: PASS

**Testing plan for Task 4**
- Keep tests focused on slot hierarchy, not brittle JSON ordering beyond meaningful structure.

**Exit condition for Task 4**
- The single generic renderer produces visibly more intentional hierarchy than raw markdown-in-card.

## Chunk 5: Keep The Skill Thin And Aligned With The Renderer

### Task 5: Refine skill wording so it supports the renderer without overfitting

**Files:**
- Modify: `skills/feishu_channel_formatting/SKILL.md`
- Test: `tests/test_skills.py`
- Test: `tests/test_contract_compatibility.py`

- [ ] **Step 1: Write failing skill-contract assertions**

Required assertions:
- natural language remains default
- `feishu_card` remains optional
- structure is limited to the documented minimal schema
- the skill does not imply every reply should be card-structured

Run: `PYTHONPATH=src python -m unittest tests.test_skills tests.test_contract_compatibility -v`
Expected: FAIL on any missing contract language

- [ ] **Step 2: Update the skill conservatively**

Required outcome:
- support the renderer contract
- avoid becoming a system-prompt replacement
- avoid channel-specific business recipes

- [ ] **Step 3: Re-run skill and contract tests**

Run: `PYTHONPATH=src python -m unittest tests.test_skills tests.test_contract_compatibility -v`
Expected: PASS

**Testing plan for Task 5**
- Keep the skill narrow and optionality-first.

**Exit condition for Task 5**
- Skill wording supports the renderer protocol without pushing the model into overuse.

## Chunk 6: Full Verification And Real-Chain Validation

### Task 6: Run repository verification and live Feishu validation

**Files:**
- Read: `STATUS.md`
- Update: `STATUS.md`
- Update: `docs/ARCHITECTURE_CHANGELOG.md`

- [ ] **Step 1: Run focused Feishu/runtime regression**

Run: `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_skills tests.test_contract_compatibility tests.test_runtime_loop -v`
Expected: PASS

- [ ] **Step 2: Run full suite**

Run: `PYTHONPATH=src python -m unittest -v`
Expected: PASS

- [ ] **Step 3: Run local live smoke**

Run:
- `PYTHONPATH=src python -m marten_runtime.interfaces.http.serve`
- `curl -s http://127.0.0.1:8000/healthz`
- `curl -s -X POST http://127.0.0.1:8000/messages -H 'Content-Type: application/json' -d '{"channel_id":"feishu","conversation_id":"feishu-renderer-smoke","message_id":"msg-renderer-smoke","text":"当前都有哪些定时任务"}'`

Expected:
- health returns `{"status":"ok"}`
- message endpoint returns success
- diagnostics remain healthy

- [ ] **Step 4: Perform one real Feishu validation**

Operator flow:
- send a real Feishu message that should naturally produce grouped output
- inspect final visible card
- confirm hierarchy is better than plain markdown dump

Suggested prompts:
- `当前都有哪些定时任务`
- `列出候选规则并按类别分组`
- `总结一下今天的检查结果`

- [ ] **Step 5: Sync docs and continuity**

Update:
- `STATUS.md`
- `docs/ARCHITECTURE_CHANGELOG.md`

Required record:
- what changed
- what was verified
- what remains open, if anything

**Testing plan for Task 6**
- All automated verification must pass before claiming completion.
- Real Feishu validation is mandatory for closing the iteration.

**Exit condition for Task 6**
- Automated verification is green, real Feishu output is reviewed, and docs are synchronized.

## Definition Of A Complete Iteration

This iteration is complete only when all of these conditions are simultaneously true:

1. **Clean boundary**
   - protocol parsing and card skeleton generation live only in the generic renderer
   - `delivery.py` is transport-only

2. **No historical residue**
   - no duplicate protocol helpers remain in `delivery.py`
   - no dormant business renderer branches remain
   - no design doc still claims that `delivery.py` owns rendering

3. **Visual improvement**
   - real Feishu card output shows clearer hierarchy than plain markdown-in-card
   - the improvement comes from the generic skeleton, not business-specific branches

4. **Safety**
   - malformed protocol payloads still deliver safely
   - retry, update, dedupe, and dead-letter behavior remain unchanged

5. **Verification**
   - focused suite passes
   - full suite passes
   - local live smoke passes
   - real Feishu validation has been performed and documented

If any one of these conditions is missing, the iteration is not complete.
