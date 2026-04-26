# Current-Turn Evidence Ledger Finalization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** implement the current-turn evidence ledger finalization contract so multi-tool turns finalize against explicit execution-derived evidence, while single-tool direct renders, zero-tool chat, and LLM-first routing behavior remain stable.

**Architecture:** keep canonical assistant/tool transcript replay unchanged, add one runtime-built current-turn evidence ledger for tool followup and finalization retry, keep `recovery_flow.py` as the bounded last-line contract validator, and add finalization diagnostics so live acceptance / retry / fallback decisions are inspectable from one run record. The runtime may summarize executed evidence and loop metadata; it must not add new host-side natural-language routing.

**Tech Stack:** Python 3.12, Pydantic, FastAPI runtime harness, unittest, OpenAI-compatible chat/responses transports

---

## Source Documents

- Design source of truth:
  - `docs/2026-04-24-current-turn-evidence-ledger-finalization-design.md`
- Architecture constraints:
  - `docs/architecture/adr/0001-thin-harness-boundary.md`
  - `docs/architecture/adr/0004-llm-first-tool-routing-boundary.md`
- Continuity file:
  - `STATUS.md`
- Nearby implementation-plan references:
  - `docs/2026-04-22-generic-loop-finalization-contract-implementation-plan.md`
  - `docs/2026-04-21-session-switch-compaction-and-replay-policy-implementation-plan.md`

## Locked Invariants

- keep free-form natural-language tool selection with the model
- keep the runtime center at:
  - `channel -> binding -> runtime loop -> builtin/MCP/skill -> finalization -> delivery`
- keep canonical assistant tool-call + tool-result transcript replay unchanged
- keep the evidence ledger additive:
  - never a replacement for transcript replay
  - never a new request router
- keep evidence-ledger inputs limited to:
  - `ToolExchange.tool_name`
  - `ToolExchange.tool_payload`
  - `ToolExchange.tool_result`
  - `ToolExchange.recovery_fragment`
  - runtime-owned loop metadata such as model/tool counts
  - existing generic finalization-contract state
- do not add keyword / regex / phrase routing for ordinary user text
- do not assign tool-family intent in the ledger builder
- keep single-tool `finalize_response=true` direct-render paths intact for:
  - `session.list`
  - `time`
  - `runtime.context_status`
  - existing direct-render-safe session / subagent cases already covered by the branch baseline
- keep zero-tool plain chat behavior unchanged
- keep finalization retry bounded:
  - at most one extra provider call after tools have already succeeded
  - no new callable tools on `request_kind="finalization_retry"`
- keep degraded fallback truthful:
  - only executed current-turn evidence
  - no fabricated success claims for failed tool steps
- keep the slice channel-agnostic:
  - no Feishu-specific finalization logic
- do not commit as part of this plan unless the user later asks explicitly

## File / Module Map

- `src/marten_runtime/runtime/llm_client.py`
  - add evidence-ledger data models to the runtime request surface
- `src/marten_runtime/runtime/tool_followup_support.py`
  - build execution-derived evidence ledger items from `tool_history`
  - keep normalization and direct-render support stable
- `src/marten_runtime/runtime/llm_message_support.py`
  - inject ledger blocks into tool-followup and finalization-retry prompts
  - keep ordinary conversation and zero-tool paths unchanged
- `src/marten_runtime/runtime/llm_request_instructions.py`
  - add generic ledger-aware followup / retry instruction wording
  - keep LLM-first routing boundary intact
- `src/marten_runtime/runtime/recovery_flow.py`
  - derive required coverage from the same evidence source seen by the model
  - keep fallback bounded and execution-truthful
- `src/marten_runtime/runtime/loop.py`
  - assemble the ledger for followup / retry requests
  - record finalization diagnostics
  - keep contract-repair and zero-tool behavior stable
- `src/marten_runtime/runtime/history.py`
  - extend run history with finalization-assessment / retry / recovery diagnostics if needed
- `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
  - expose the new finalization diagnostics fields when appropriate
- `tests/test_tool_followup_support.py`
  - unit coverage for evidence-ledger assembly and direct-render stability
- `tests/test_llm_message_support.py`
  - new focused prompt-assembly tests for ledger injection and bounded prompt shape
- `tests/test_llm_client.py`
  - request-specific instruction and contract-repair wording coverage
- `tests/test_recovery_flow.py`
  - evidence-ledger-driven acceptance / degraded / fallback rules
- `tests/runtime_loop/test_tool_followup_and_recovery.py`
  - loop integration, retry, contract-repair continuity, partial-success, zero-tool stability
- `tests/runtime_loop/test_direct_rendering_paths.py`
  - protect existing direct-render fast paths
- `tests/test_acceptance.py`
  - end-to-end regression for thin-summary omission, partial success, zero-tool plain chat, direct render, prompt-size-sensitive paths
- `tests/test_gateway.py`
  - request/response stability where runtime loop finalization state is surfaced across the HTTP boundary
- `docs/ARCHITECTURE_CHANGELOG.md`
  - record the durable finalization-contract change after implementation lands
- `STATUS.md`
  - keep progress and verification synchronized with reality

## Anti-Drift Checkpoints

Re-check these design sections after each chunk:

- design section `2`:
  - ledger inputs must stay execution-derived
  - required flags must stay inside existing finalization-contract state
- design section `3`:
  - transcript remains canonical and ledger remains additive
- design section `4`:
  - `recovery_flow.py` remains the last-line validator, not a second success-path answer engine
- design section `5`:
  - observability fields must explain acceptance / retry / fallback decisions
- design section `7`:
  - no host-side natural-language routing growth
- design section `9`:
  - contract-repair, partial-success, zero-tool, and prompt-size regressions must all be covered

If a chunk drifts from one of these checkpoints, fix the code or fix the plan before continuing.

## Delivery Order

Implement in five strict chunks:

1. evidence-ledger data contract and assembly helpers
2. prompt assembly and request-instruction wiring
3. recovery-flow alignment and bounded fallback rules
4. loop integration, diagnostics, and contract-repair / zero-tool stability
5. broader regressions, docs sync, and final anti-drift verification

Do not start a later chunk until the current chunk:

- passes its focused verification
- still matches the design doc
- leaves `git diff --check` clean

## Chunk 1: Evidence-Ledger Data Contract And Assembly

### Task 1: Add evidence-ledger models to the runtime request surface

**Files:**
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Create: `tests/test_llm_message_support.py`

**Constraints:**
- models stay runtime-only
- model-visible transcript stays the canonical `assistant tool_call + tool result` history
- do not expose new provider-facing structured protocol surfaces

- [ ] **Step 1: Write the failing tests**

Lock:

- `LLMRequest` can carry one evidence-ledger payload
- zero-tool conversation requests can still omit it cleanly
- provider-visible tool transcript shape stays unchanged

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_message_support
```

Expected:

- new assertions fail because the evidence-ledger models do not exist yet

- [ ] **Step 3: Implement the models**

Required shape:

```python
class FinalizationEvidenceItem(BaseModel):
    ordinal: int
    tool_name: str
    tool_action: str | None = None
    payload_summary: str | None = None
    result_summary: str
    required_for_user_request: bool = True
    evidence_source: Literal["tool_result", "loop_meta"] = "tool_result"


class FinalizationEvidenceLedger(BaseModel):
    user_message: str
    tool_call_count: int
    model_request_count: int | None = None
    requires_result_coverage: bool = False
    requires_round_trip_report: bool = False
    items: list[FinalizationEvidenceItem] = Field(default_factory=list)
```

And add one optional request field:

```python
finalization_evidence_ledger: FinalizationEvidenceLedger | None = None
```

- [ ] **Step 4: Keep request serialization boundaries stable**

Confirm:

- existing provider payload builders do not serialize the ledger as a new transport field
- transcript messages remain the only model-visible tool-execution transcript surface

- [ ] **Step 5: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_message_support
```

**Done means:**

- evidence-ledger models exist
- request surface can carry them
- provider transcript shape has not widened

### Task 2: Build deterministic ledger assembly helpers

**Files:**
- Modify: `src/marten_runtime/runtime/tool_followup_support.py`
- Modify: `tests/test_tool_followup_support.py`

**Constraints:**
- derive only from existing finalization-contract state, structured request state, `tool_history`, and loop metadata
- do not add keyword / regex / phrase routing for ordinary user text
- reuse `recovery_fragment` as the primary source when present
- successful tools preserve execution order
- failed tools do not become required success evidence by default

- [ ] **Step 1: Write the failing tests**

Lock:

- one successful tool -> one evidence item
- three-tool chain preserves order
- `recovery_fragment` wins over ad hoc synthetic summarization
- loop-meta item appears only when relevant
- failed tool results are excluded from required success coverage by default

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_tool_followup_support
```

Expected:

- new evidence-ledger assertions fail because the builder does not exist yet

- [ ] **Step 3: Implement the assembly helpers**

Recommended helper surface:

```python
def build_finalization_evidence_ledger(
    *,
    user_message: str,
    tool_history: list[ToolExchange],
    model_request_count: int | None,
    requires_result_coverage: bool,
    requires_round_trip_report: bool,
) -> FinalizationEvidenceLedger: ...
```

Implementation requirements:

- iterate `tool_history` in order
- generate item summaries from:
  1. `recovery_fragment.text`
  2. direct deterministic render text
  3. thin synthetic summary derived from tool result structure
- include loop meta only when round-trip reporting is relevant

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_tool_followup_support
```

**Done means:**

- ledger assembly is deterministic
- success evidence is ordered and bounded
- failed-step handling is explicit and truthful

## Chunk 2: Prompt Assembly And Instruction Wiring

### Task 3: Inject the ledger into tool-followup and finalization-retry prompts

**Files:**
- Modify: `src/marten_runtime/runtime/llm_message_support.py`
- Modify: `tests/test_llm_message_support.py`

**Constraints:**
- zero-tool conversation requests must remain unchanged
- normal tool transcript replay must stay present
- ledger is additive, compact, and bounded
- prompt must not duplicate full transcript payload inside the ledger block

- [ ] **Step 1: Write the failing tests**

Lock:

- normal conversation request -> no ledger block
- tool-followup request with ledger -> system block included
- finalization-retry request with ledger -> system block included and no callable tools
- prompt-size regression checks:
  - single-tool followup
  - three-tool followup
  - finalization retry

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_message_support tests.test_llm_transport
```

Expected:

- ledger block assertions fail because prompt assembly does not inject it yet

- [ ] **Step 3: Implement ledger serialization helpers**

Recommended surface:

```python
def render_finalization_evidence_ledger_block(
    ledger: FinalizationEvidenceLedger | None,
) -> str | None: ...
```

Injection rules:

- add as one system block for tool-followup and finalization-retry requests when ledger is present
- keep ordinary conversation requests unchanged
- keep transcript and ledger both present
- keep the ledger compact and summary-oriented

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_message_support tests.test_llm_transport
```

**Done means:**

- ledger appears only where intended
- transcript replay remains canonical
- prompt growth is bounded and covered by tests

### Task 4: Add generic ledger-aware instruction text

**Files:**
- Modify: `src/marten_runtime/runtime/llm_request_instructions.py`
- Modify: `tests/test_llm_client.py`

**Constraints:**
- keep wording generic
- do not introduce tool-family routing hints for ordinary free-form user text
- `contract_repair` wording must remain inside the existing contract boundary

- [ ] **Step 1: Write the failing tests**

Lock:

- tool-followup instructions mention coverage of required evidence items when ledger is present
- finalization-retry instructions say no new tools and all required evidence is already available
- `contract_repair` wording stays generic and introduces no new family-routing text

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_client
```

Expected:

- new instruction assertions fail because wording has not been updated yet

- [ ] **Step 3: Implement the instruction changes**

Required behavior:

- tool-followup: point the model at the ledger coverage obligations
- finalization-retry: state clearly that all required evidence is already available and no new tools may be called
- contract-repair: remain within the current-turn contract boundary and avoid tool-family routing additions

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_client
```

**Done means:**

- prompt wording is ledger-aware
- wording remains LLM-first and routing-neutral

## Chunk 3: Recovery-Flow Alignment And Bounded Fallback

### Task 5: Make validator expectations derive from the same evidence source seen by the model

**Files:**
- Modify: `src/marten_runtime/runtime/recovery_flow.py`
- Modify: `tests/test_recovery_flow.py`

**Constraints:**
- required coverage must come from the same evidence-ledger source injected into prompts
- keep validator bounded
- do not widen `recovery_flow.py` into a second success-path summarizer
- failed tools must not become fabricated success coverage

- [ ] **Step 1: Write the failing tests**

Lock:

- final text covering all required evidence -> `accepted`
- omission of one required item -> `retryable_degraded`
- required round-trip statement present -> accepted
- required round-trip statement missing -> degraded
- partial-success chain -> successful evidence remains required while failed-step success is not fabricated
- `contract_repair` path still evaluates against the same bounded evidence source

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_recovery_flow
```

Expected:

- new ledger-driven assertions fail because validator still derives expectations from the older narrower shape

- [ ] **Step 3: Implement the validator alignment**

Implementation requirements:

- add helpers that derive required evidence items from the ledger or the same shared assembly rule
- keep existing false-claim checks for session / spawn-subagent contracts intact
- keep generic empty / generic-failure checks intact

- [ ] **Step 4: Keep fallback bounded and ordered**

Ensure degraded fallback:

- uses required evidence items in execution order
- includes loop meta only when required
- stays truthful to successful current-turn evidence

- [ ] **Step 5: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_recovery_flow
```

**Done means:**

- prompt, validator, and fallback all derive from the same evidence source
- omission and partial-success behavior are locked by tests

## Chunk 4: Loop Integration, Diagnostics, Contract-Repair And Zero-Tool Stability

### Task 6: Wire the ledger through the runtime loop

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `tests/runtime_loop/test_tool_followup_and_recovery.py`
- Modify: `tests/runtime_loop/test_direct_rendering_paths.py`

**Constraints:**
- tool-followup requests carry the ledger when tool history exists
- finalization-retry requests carry the ledger and no tools
- zero-tool conversation path must stay unchanged
- contract-repair path must stay inside current-turn contract boundaries and must not add family-routing behavior
- single-tool direct renders must remain one-hop

- [ ] **Step 1: Write the failing loop tests**

Lock:

- multi-tool followup request carries transcript + ledger
- finalization-retry request carries the same ledger
- thin final answer triggers retry
- same run enters `finalization_retry` at most once
- `contract_repair` continuity stays on the same evidence boundary
- zero-tool plain chat does not get ledger-specific retry pressure
- existing direct-render paths still short-circuit normally

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_direct_rendering_paths
```

Expected:

- loop assertions fail because ledger wiring and guards are not in place yet

- [ ] **Step 3: Implement the loop wiring**

Implementation requirements:

- build ledger from current-turn tool history and contract flags
- attach it to tool-followup requests
- attach the same logical evidence source to finalization-retry requests
- keep zero-tool path free of ledger side effects
- keep contract-repair generic and bounded

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_direct_rendering_paths
```

**Done means:**

- runtime loop uses the ledger only on the intended paths
- direct render, contract repair, and zero-tool behavior remain stable

### Task 7: Record and expose finalization diagnostics

**Files:**
- Modify: `src/marten_runtime/runtime/history.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `tests/test_runtime_history.py`
- Modify: `tests/test_http_runtime_diagnostics.py`

**Constraints:**
- diagnostics must explain acceptance / retry / fallback decisions
- diagnostic strings must be bounded and truncatable
- do not widen public diagnostics into a large replay blob

- [ ] **Step 1: Write the failing diagnostics tests**

Lock:

- accepted run records finalization assessment
- degraded run records missing evidence summary and retry trigger
- recovered run records fragment-recovery state
- diagnostics endpoint exposes the new fields without leaking unbounded payloads

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_runtime_history \
  tests.test_http_runtime_diagnostics
```

Expected:

- new diagnostics assertions fail because the fields do not exist yet

- [ ] **Step 3: Implement the diagnostics fields**

Target fields:

- `finalization.assessment`
- `finalization.request_kind`
- `finalization.required_evidence_count`
- `finalization.missing_evidence_items`
- `finalization.retry_triggered`
- `finalization.recovered_from_fragments`
- bounded `finalization.invalid_final_text`

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_runtime_history \
  tests.test_http_runtime_diagnostics
```

**Done means:**

- live/offline mismatches become diagnosable from one run record
- diagnostics remain bounded

## Chunk 5: Broader Regressions, Docs Sync, And Final Verification

### Task 8: Add acceptance and gateway regressions for the full surface

**Files:**
- Modify: `tests/test_acceptance.py`
- Modify: `tests/test_gateway.py`

**Constraints:**
- cover main chain and the four edge classes from the design review:
  - contract-repair continuity
  - partial-success / tool-failure truthfulness
  - zero-tool plain chat stability
  - prompt-size stability
- keep tests runtime-owned and channel-agnostic
- final proof must still cover transport and contract surfaces touched by this slice

- [ ] **Step 1: Write the failing acceptance / gateway tests**

Lock:

- thin-summary omission regression
- single-tool direct-render regression
- partial-success finalization regression
- zero-tool plain-chat regression
- prompt-size stability regression
- gateway-visible finalization diagnostics / state stability where applicable

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_acceptance tests.test_gateway
```

Expected:

- new regressions fail until the full slice is wired through

- [ ] **Step 3: Fix remaining gaps exposed by the broader tests**

Implementation notes:

- keep fixes inside the finalization slice
- do not patch with host-side routing
- prefer tightening shared evidence / prompt / validator wiring over test-only branches

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_acceptance tests.test_gateway
```

**Done means:**

- main-chain and edge regressions are both covered
- no test requires host-side natural-language routing to pass

### Task 9: Sync docs, continuity, and run final regression proof

**Files:**
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Modify: `STATUS.md`

**Constraints:**
- changelog entry must describe the durable runtime contract, not transient branch trivia
- `STATUS.md` must reflect actual slice completion and verification
- no stale “pending” wording after tests pass

- [ ] **Step 1: Update docs after code and tests are green**

Record:

- current-turn evidence ledger became part of the finalization contract
- prompt / validator / fallback now share one execution-derived evidence source
- the four edge regressions are covered by tests

- [ ] **Step 2: Run focused doc/continuity checks**

Run:

```bash
python - <<'PY'
from pathlib import Path
for path in [
    Path('docs/2026-04-24-current-turn-evidence-ledger-finalization-design.md'),
    Path('docs/2026-04-24-current-turn-evidence-ledger-finalization-implementation-plan.md'),
    Path('docs/ARCHITECTURE_CHANGELOG.md'),
    Path('STATUS.md'),
]:
    text = path.read_text()
    assert text.strip(), f"empty file: {path}"
print('docs-nonempty-ok')
PY
```

Expected:

- `docs-nonempty-ok`

- [ ] **Step 3: Run the final regression proof**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_tool_followup_support \
  tests.test_llm_message_support \
  tests.test_llm_client \
  tests.test_llm_transport \
  tests.test_recovery_flow \
  tests.test_runtime_history \
  tests.test_http_runtime_diagnostics \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_direct_rendering_paths \
  tests.contracts.test_runtime_contracts \
  tests.contracts.test_gateway_contracts \
  tests.test_acceptance \
  tests.test_gateway
```

Then run:

```bash
git diff --check
```

**Done means:**

- the full finalization slice is green on focused and broader regression suites
- docs and continuity match reality
- diff hygiene is clean

## Final Alignment Checklist

Before implementation is declared complete, confirm all of the following:

- evidence-ledger flags still derive only from existing contract state, structured request state, executed tool history, and runtime-owned loop metadata
- zero-tool plain conversation remains on the pre-ledger path
- single-tool direct renders still complete in one hop
- partial-success chains do not fabricate failed-step success
- `contract_repair` stays inside current-turn contract boundaries
- prompt-size tests prove the ledger is bounded and not duplicating transcript payloads unboundedly
- diagnostics explain whether a bad final answer was accepted, retried, or recovered
- no host-side natural-language routing helper was added
