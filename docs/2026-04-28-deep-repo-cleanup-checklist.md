Date: 2026-04-28
Status: execution in progress for this round
Scope: current working tree deep repo-scan; this file supersedes `docs/2026-04-28-aggressive-repo-cleanup-checklist.md` as the active cleanup handoff

# 2026-04-28 Deep Repo Cleanup Checklist

This is the current execution handoff for the next slimming wave.

Read in this order before deleting anything:

1. `README.md`
2. `docs/README.md`
3. `docs/ARCHITECTURE_EVOLUTION.md`
4. `docs/ARCHITECTURE_CHANGELOG.md`
5. `docs/CONFIG_SURFACES.md`
6. this file

## Goal And Active Spine

Repository goal:

- keep `marten-runtime` as a thin agent runtime harness centered on:
  - `channel -> binding -> runtime loop -> builtin tool / MCP / skill -> delivery / diagnostics`

Audit ordering for this round:

1. remove historical docs that no longer describe any live contract
2. challenge single-consumer support splits that now have sharper owners
3. shrink the biggest surviving test seams where overlap is still larger than the active runtime spine needs

## Surface Snapshot

- tracked surface on the current working tree:
  - `src`: `142` Python files / `23164` lines / `32.6%` of tracked `src+tests+docs` lines
  - `tests`: `115` Python files / `36735` lines / `51.7%`
  - `docs`: `31` Markdown files / `11354` lines / `16.0%`
- `docs/archive/`: `13` Markdown files / `4414` lines / `38.9%` of remaining docs
- churn since `2026-04-01`:
  - `src`: `20675` added / `5270` deleted
  - `tests`: `41351` added / `9328` deleted
  - `docs`: `28316` added / `7815` deleted
- biggest remaining test concentration:
  - finalization / transport cluster: `6695` lines
  - gateway / Feishu cluster: `6407` lines
  - session cluster: `2783` lines
  - control-plane tool cluster: `2620` lines

## Deep Audit Notes

- the first aggressive cleanup queue is already closed in `STATUS.md`
- the new cleanup value sits in:
  - stale historical docs that still survive after their code paths disappeared
  - one single-consumer in-memory store split under `subagents/`
  - large test families that still carry multi-owner assertions in one file
- low-caller scans still surface many `0` or `1` caller modules, but most of them are legitimate owner files on the active spine; the next safe code deletion target is small

## Executed On 2026-04-28

- stale archive-doc wave completed:
  - deleted `docs/archive/audits/2026-03-31-repo-cleanup-audit.md`
  - deleted `docs/archive/2026-03-31-agent-domain-query-adapter-design.md`
  - deleted `docs/archive/2026-03-31-automation-domain-adapter-design.md`
  - deleted `docs/archive/plans/2026-04-05-delete-github-hot-repos-digest-plan.md`
  - shrank `docs/archive/README.md` and compressed `docs/archive/plans/2026-04-11-repo-slimming-summary.md`
  - retired `docs/2026-04-28-aggressive-repo-cleanup-checklist.md`
- single-consumer subagent-store split completed:
  - inlined the in-memory task store into `src/marten_runtime/subagents/service.py`
  - deleted `src/marten_runtime/subagents/store.py`
  - deleted `tests/test_subagent_store.py`
  - reused `tests/support/feishu_builders.py::FakeDeliveryClient` in `tests/test_self_improve_review_dispatcher.py`
- gateway / Feishu first-wave acceptance thinning completed:
  - removed three non-smoke acceptance tests whose owner truth already lived in lower suites
  - `tests/test_acceptance.py` now keeps `14` end-to-end scenarios instead of `17`

## Delete-Ready Now (Executed 2026-04-28)

- path-or-group:
  - `docs/archive/audits/2026-03-31-repo-cleanup-audit.md`
  - `docs/archive/2026-03-31-agent-domain-query-adapter-design.md`
  - `docs/archive/2026-03-31-automation-domain-adapter-design.md`
  - candidate-type: stale adapter-wave archive set
  - key-evidence:
    - `2026-03-31-repo-cleanup-audit.md` is `244` lines with `0` active refs
    - the two adapter design docs are only referenced by `docs/archive/README.md` and that stale audit
    - the current working tree already removed the underlying adapter code:
      - `src/marten_runtime/data_access/adapter.py`
      - `src/marten_runtime/data_access/specs.py`
      - `tests/test_data_access_adapter.py`
    - the active runtime path already documents the direct-store control-plane shape:
      - automation family tool -> automation store
      - self-improve family surface -> runtime-managed SQLite state
  - surviving-contract:
    - current control-plane truth already lives in `README.md`, `docs/README.md`, `docs/ARCHITECTURE_CHANGELOG.md`, and the code/tests
  - missing-proof:
    - `contract-proof`: shrink `docs/archive/README.md` so it no longer promises this adapter-wave trio
  - fastest-next-check:
    - run basename scans for all three files after `docs/archive/README.md` is updated
  - suggested-action:
    - replace the trio with one short archive note, then delete all three files in one slice

- path-or-group: `docs/archive/plans/2026-04-05-delete-github-hot-repos-digest-plan.md`
  - candidate-type: executed removal plan for a now-absent skill path
  - key-evidence:
    - `535` lines
    - current filename refs come from the older 2026-04-28 aggressive checklist rather than from the active docs path
    - the repository already moved GitHub trending onto the MCP sidecar path:
      - `README.md`
      - `docs/CONFIG_SURFACES.md`
      - `src/marten_runtime/mcp_servers/github_trending.py`
    - the skill-removal wave itself is already reflected in the working tree
  - surviving-contract:
    - GitHub trending runtime truth now lives on the MCP-first docs and code path
  - missing-proof:
    - `contract-proof`: move the active backlog pointer away from the older checklist first
  - fastest-next-check:
    - repoint `docs/README.md` and `docs/archive/plans/2026-04-11-repo-slimming-summary.md` to this deep checklist, then rerun a basename scan
  - suggested-action:
    - delete the plan in the same doc slice that retires the old aggressive checklist

## High-Probability Next (Executed 2026-04-28)

- path-or-group:
  - `docs/2026-04-28-aggressive-repo-cleanup-checklist.md`
  - `docs/archive/plans/2026-04-11-repo-slimming-summary.md`
  - candidate-type: executed cleanup handoff docs that still carry the old live backlog pointer
  - key-evidence:
    - the older aggressive checklist is `417` lines and its executable queue is already closed in `STATUS.md`
    - the 2026-04-11 summary is `89` lines and now mainly serves as a bridge to that older checklist
    - the active docs path used to point at the older checklist as the current backlog source
    - historical references now sit mostly in `STATUS.md`, not in the active reading path
  - surviving-contract:
    - one current cleanup handoff
    - one short 2026-04-11 historical summary if the archive still needs it
  - missing-proof:
    - `contract-proof`: decide whether historical references in `STATUS.md` stay as-is, or whether they should be compressed to one short “executed 2026-04-28 queue” note before the old checklist disappears
  - fastest-next-check:
    - search `README.md`, `docs/README.md`, `docs/archive/plans/2026-04-11-repo-slimming-summary.md`, and `STATUS.md` for the old checklist path
  - suggested-action:
    - keep this deep checklist as the only live backlog, compress the 04-11 summary to one brief historical note, and then retire the older checklist

- path-or-group:
  - `src/marten_runtime/subagents/store.py`
  - `tests/test_subagent_store.py`
  - candidate-type: single-consumer in-memory store split plus isolated contract suite
  - key-evidence:
    - the runtime has one real consumer: `src/marten_runtime/subagents/service.py`
    - direct imports are otherwise limited to:
      - `tests/test_subagent_store.py`
      - `tests/test_self_improve_review_dispatcher.py`
    - the store file is a small mutable state holder:
      - create / get / list
      - queued -> running
      - terminal transitions
      - result/error payload attachment
    - the previous subagent owner-thinning wave already clarified the outer owners:
      - store lifecycle
      - service queue/timeout/completion
      - tool contract
      - parent-session terminal contract
      - self-improve review integration
  - surviving-contract:
    - `SubagentService` still needs one bounded task-state container
    - tests still need one way to assert queue/terminal transitions and child-session linkage
  - missing-proof:
    - `owner-proof`
    - `contract-proof`
  - fastest-next-check:
    - confirm that no runtime code outside `SubagentService` constructs `InMemorySubagentStore`, then decide whether the state holder belongs as a private inner owner inside `service.py`
  - suggested-action:
    - either inline the store into `subagents/service.py` or convert it into a service-private helper and absorb `tests/test_subagent_store.py` assertions into service/contract suites

- path-or-group:
  - `tests/test_self_improve_review_dispatcher.py::_FakeDeliveryClient`
  - `tests/support/feishu_builders.py::FakeDeliveryClient`
  - candidate-type: local helper duplication inside test support
  - key-evidence:
    - `tests/test_self_improve_review_dispatcher.py` still defines a private `_FakeDeliveryClient`
    - `tests/support/feishu_builders.py` already exports a shared `FakeDeliveryClient`
    - both helpers keep the same core contract:
      - record delivered payloads
      - return `ok=True`
      - synthesize `message_id`
  - surviving-contract:
    - review-dispatch tests need only one successful delivery recorder
  - missing-proof:
    - `owner-proof`: confirm the review-dispatch tests do not need a narrower payload type or custom `add_reaction` shape
  - fastest-next-check:
    - swap the local fake for the shared helper in one narrow test slice and rerun the review-dispatch suite
  - suggested-action:
    - reuse the shared helper and delete the private duplicate

## Aggressive Candidate Backlog

- path-or-group:
  - `tests/test_llm_transport.py`
  - `tests/runtime_loop/test_tool_followup_and_recovery.py`
  - `tests/test_tool_followup_support.py`
  - `tests/runtime_mcp/test_followup_recovery.py`
  - candidate-type: finalization / transport / followup / MCP overlap cluster
  - key-evidence:
    - `6695` lines combined
    - theme census:
      - `tests/test_llm_transport.py`: `50` tests; `48` payload/transport-heavy and `12` also touch followup/recovery concerns
      - `tests/runtime_loop/test_tool_followup_and_recovery.py`: `48` tests; `23` followup/recovery-heavy, `11` session-related, `5` MCP-related
      - `tests/runtime_mcp/test_followup_recovery.py`: `20` tests focused on live MCP thread/deadline behavior
    - this cluster already absorbed repeated dedupe waves and is still the largest single test concentration left
  - surviving-contract:
    - `tests/test_llm_transport.py` owns provider payloads, timeout budgets, tool/capability injection, and response-shape normalization
    - `tests/test_tool_followup_support.py` owns tool-result normalization, direct-render eligibility, and followup request assembly
    - `tests/runtime_loop/test_tool_followup_and_recovery.py` owns loop orchestration, finalization retry, recovery fragments, and persisted tool-summary behavior
    - `tests/runtime_mcp/test_followup_recovery.py` owns live MCP worker/deadline behavior
    - `tests/test_acceptance.py` should keep only one end-to-end smoke per behavior family
  - missing-proof:
    - `owner-proof`
    - `contract-proof`
  - fastest-next-check:
    - label the `12` cross-theme tests inside `tests/test_llm_transport.py` and move any loop/followup ownership down to the loop or followup-support suites
  - suggested-action:
    - thin cross-owner assertions out of `tests/test_llm_transport.py` first, then re-check the loop suite for MCP/session spillover

- path-or-group:
  - `tests/test_gateway.py`
  - `tests/contracts/test_gateway_contracts.py`
  - `tests/feishu/test_delivery.py`
  - `tests/feishu/test_rendering.py`
  - `tests/feishu/test_websocket_service.py`
  - `tests/test_acceptance.py`
  - candidate-type: gateway / Feishu / delivery / public-contract overlap cluster
  - key-evidence:
    - `6233` lines combined
    - theme census:
      - `tests/test_gateway.py`: `25` tests; `21` gateway-contract heavy and `11` also touch Feishu behavior
      - `tests/feishu/test_websocket_service.py`: `29` tests; `28` Feishu-heavy and `11` also touch gateway-contract behavior
      - `tests/test_acceptance.py`: `14` tests after the first owner-thinning wave; the remaining suite should stay smoke-only
    - owner-thinning already removed some duplicated card/footer assertions, yet the cross-surface overlap is still large
  - surviving-contract:
    - `tests/test_gateway.py` owns HTTP envelope, session isolation, `/messages` final event shape, and non-channel gateway behavior
    - `tests/contracts/test_gateway_contracts.py` owns public HTTP/event contract fields and error-code surfaces
    - `tests/feishu/test_rendering.py` owns card/plain-text rendering
    - `tests/feishu/test_delivery.py` owns delivery transport, message update flow, and usage-summary attachment
    - `tests/feishu/test_websocket_service.py` owns websocket ingress, queueing, dedupe, and offload behavior
    - `tests/test_acceptance.py` owns cross-surface smoke only
  - missing-proof:
    - `owner-proof`
  - fastest-next-check:
    - tag every Feishu-specific assertion that still lives in `tests/test_gateway.py` or `tests/test_acceptance.py`, then keep exactly one acceptance scenario per channel behavior family
  - suggested-action:
    - make `tests/test_acceptance.py` smaller before touching the lower-level Feishu suites

- path-or-group:
  - `tests/test_session.py`
  - `tests/test_sqlite_session_store.py`
  - `tests/test_session_transition.py`
  - `tests/tools/test_session_tool.py`
  - `tests/test_session_compaction_worker.py`
  - `tests/test_subagent_runtime_loop.py`
  - candidate-type: SQLite-only session contract cluster
  - key-evidence:
    - `2783` lines combined
    - the runtime already standardized on SQLite-only session persistence
    - `tests/tools/test_session_tool.py` still carries `19` session-focused tests on the user-facing surface
    - `tests/test_sqlite_session_store.py` is now one of the largest remaining owner suites at `747` lines
  - surviving-contract:
    - `tests/test_sqlite_session_store.py` owns persistence details and migration-state behavior
    - `tests/tools/test_session_tool.py` owns user-facing `list/show/new/resume`
    - `tests/test_session_transition.py` owns switch/resume contract and source-session compaction enqueue rules
    - `tests/test_session_compaction_worker.py` owns job claim/apply/failure behavior
    - `tests/test_subagent_runtime_loop.py` keeps only child-session continuity that truly crosses into runtime behavior
  - missing-proof:
    - `owner-proof`
  - fastest-next-check:
    - build a switch/resume assertion matrix and remove any session-tool or runtime-loop assertion that repeats store-level truth
  - suggested-action:
    - slim the session cluster after the finalization and gateway clusters

- path-or-group:
  - `tests/test_skills.py`
  - `tests/tools/test_self_improve_tool.py`
  - `tests/test_self_improve_review_dispatcher.py`
  - `tests/tools/test_automation_tool.py`
  - `tests/test_automation_store.py`
  - `tests/test_automation.py`
  - `tests/test_runtime_capabilities.py`
  - candidate-type: control-plane tool / skill / capability overlap cluster
  - key-evidence:
    - `2620` lines combined
    - this cluster keeps accumulating domain-surface assertions outside the main runtime path
    - helper duplication already exists inside the cluster
  - surviving-contract:
    - `tests/test_skills.py` owns skill loading/visibility and repo-visible skill surface
    - `tests/tools/test_self_improve_tool.py` owns self-improve tool CRUD/detail behavior
    - `tests/test_self_improve_review_dispatcher.py` owns trigger dispatch and review notification flow
    - `tests/tools/test_automation_tool.py` owns automation tool surface behavior
    - `tests/test_automation_store.py` owns automation persistence semantics
    - `tests/test_runtime_capabilities.py` owns capability wording and schema exposure
  - missing-proof:
    - `owner-proof`
  - fastest-next-check:
    - isolate capability wording assertions from CRUD/detail assertions and delete any domain-store proof that still lives in runtime-capability or skills tests
  - suggested-action:
    - thin helper duplication first, then split the cluster by owner role instead of by product name

- path-or-group:
  - `docs/2026-03-29-private-agent-harness-design.md`
  - `docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md`
  - `docs/2026-04-01-feishu-generic-card-protocol-design.md`
  - `docs/2026-04-17-langfuse-observability-design.md`
  - candidate-type: root-level durable design quartet
  - key-evidence:
    - `1877` lines combined
    - current active refs come from:
      - `docs/ARCHITECTURE_EVOLUTION*.md`
      - `docs/ARCHITECTURE_CHANGELOG.md`
      - ADR references
      - `docs/README.md`
    - these four files now form most of the remaining non-archive dated-doc surface
  - surviving-contract:
    - thin-harness boundary
    - progressive-disclosure / LLM-first routing boundary
    - Feishu card rendering boundary
    - Langfuse observability boundary
  - missing-proof:
    - `contract-proof`
  - fastest-next-check:
    - move any still-live durable rule into ADRs, `docs/ARCHITECTURE_CHANGELOG.md`, or `docs/ARCHITECTURE_EVOLUTION*.md`, then decide which originals still deserve root placement
  - suggested-action:
    - challenge the quartet only after the stale archive-doc wave is finished

- path-or-group:
  - `docs/archive/2026-04-06-thin-llm-context-compaction-design.md`
  - `docs/archive/2026-04-07-context-usage-accuracy-design.md`
  - `docs/archive/2026-04-07-llm-tool-episode-summary-design.md`
  - `docs/archive/plans/2026-04-01-bootstrap-assembly-hygiene-plan.md`
  - `docs/archive/plans/2026-04-01-feishu-message-pipeline-unification-plan.md`
  - `docs/archive/plans/2026-04-05-github-trending-mcp-plan.md`
  - `docs/archive/plans/2026-04-07-context-usage-accuracy-plan.md`
  - `docs/archive/plans/2026-04-07-llm-tool-episode-summary-plan.md`
  - `docs/archive/plans/2026-04-07-thin-llm-context-compaction-plan.md`
  - `docs/archive/branch-evolution/2026-04-09-fast-path-inventory-and-exit-strategy.md`
  - candidate-type: archive traceability cohort with active changelog/evolution links
  - key-evidence:
    - this cohort accounts for most of the remaining `docs/archive/` line count
    - unlike the stale adapter-wave docs, these files still have active `ARCHITECTURE_CHANGELOG.md` or `ARCHITECTURE_EVOLUTION*.md` links
    - archive now holds `6249` lines, almost half of all docs
  - surviving-contract:
    - timeline traceability for compaction, context-usage, tool-episode summary, GitHub trending MCP, and branch-evolution boundary changes
  - missing-proof:
    - `contract-proof`
  - fastest-next-check:
    - identify which active changelog/evolution entries still require a full document link and which can be reduced to inline summary text
  - suggested-action:
    - prune the archive cohort after the root design quartet decision

- path-or-group:
  - `src/marten_runtime/interfaces/http/bootstrap.py`
  - `src/marten_runtime/agents/router.py`
  - candidate-type: thin wrapper / named-contract residue
  - key-evidence:
    - `bootstrap.py` is a re-export file over `bootstrap_runtime.py` and `bootstrap_handlers.py`
    - `agents/router.py` is a small precedence wrapper with one runtime consumer and a dedicated test file
    - both files are valid abstractions today, but both have low deletion yield compared with the larger test/doc seams
  - surviving-contract:
    - stable import surface for HTTP runtime assembly
    - explicit agent-routing precedence contract
  - missing-proof:
    - `contract-proof`
    - `owner-proof`
  - fastest-next-check:
    - count direct importers and verify whether collapsing either file removes more code than it redistributes
  - suggested-action:
    - revisit only after the big test clusters and stale docs are thinner

## Not-a-Cleanup-Priority

- path or group:
  - `src/marten_runtime/runtime/loop.py`
  - `src/marten_runtime/runtime/recovery_flow.py`
  - `src/marten_runtime/session/sqlite_store.py`
  - why it stays out of scope this round:
    - these are large because they are active owner modules on the runtime spine

- path or group:
  - `src/marten_runtime/channels/feishu/delivery_session.py`
  - `src/marten_runtime/channels/feishu/rendering_support.py`
  - `src/marten_runtime/channels/feishu/service_support.py`
  - why it stays out of scope this round:
    - each file has a low caller count, but each carries real delivery, rendering, or queue-diagnostics behavior

- path or group: `src/marten_runtime/mcp_servers/github_trending.py`
  - why it stays out of scope this round:
    - config wiring and active docs still treat it as the live repo-local MCP sidecar

- path or group: thin `memory` runtime surface
  - why it stays out of scope this round:
    - active docs already define a bounded retained product surface for explicit cross-session user facts and preferences

- path or group: `docs/archive/audits/ARCHITECTURE_AUDIT.md`
  - why it stays out of scope this round:
    - ADR and changelog entries still use it as an architecture-reference artifact

## Cleanup Execution Package

- scope:
  - finish one stale-doc deletion wave first
  - then execute one narrow code/test cleanup wave with the highest proof density
  - keep larger test-family slimming as explicit owner-map work rather than opportunistic deletion

- ordered-actions:
  1. completed: adopt this file as the active cleanup handoff by pointing `docs/README.md` and `docs/archive/plans/2026-04-11-repo-slimming-summary.md` here
  2. completed: delete the stale adapter-wave archive set:
     - `docs/archive/audits/2026-03-31-repo-cleanup-audit.md`
     - `docs/archive/2026-03-31-agent-domain-query-adapter-design.md`
     - `docs/archive/2026-03-31-automation-domain-adapter-design.md`
  3. completed: retire the executed GitHub hot-repos removal plan once the old checklist is no longer the live backlog pointer
  4. completed: run one narrow code/test slice on:
     - `src/marten_runtime/subagents/store.py`
     - `tests/test_subagent_store.py`
     - `tests/test_self_improve_review_dispatcher.py::_FakeDeliveryClient`
  5. completed first wave on `gateway / Feishu`:
     - thinned `tests/test_acceptance.py` down toward smoke-only ownership
  6. remaining choice for the next cleanup wave:
     - finalization / transport
     - gateway / Feishu lower-surface overlap
     - session
     - control-plane tools

- verification:
  - stale-doc basename scans:
    - `rg -n '<basename>' README.md docs src tests STATUS.md`
  - compile safety:
    - `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`
  - subagent/store slice:
    - `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_subagent_service tests.tools.test_subagent_tools tests.contracts.test_subagent_contracts tests.test_self_improve_review_dispatcher`
  - gateway smoke guard when touching large test clusters:
    - `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_acceptance tests.test_gateway tests.feishu.test_delivery tests.feishu.test_rendering`
  - finalization guard when touching transport/followup cluster:
    - `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_transport tests.test_tool_followup_support tests.runtime_loop.test_tool_followup_and_recovery tests.runtime_mcp.test_followup_recovery`

- stop-conditions:
  - stop a doc deletion when the file still carries a live active-doc dependency outside archive/index history
  - stop a source deletion when more than one runtime consumer or one public contract still depends on the split
  - stop a large test-thinning wave when one assertion family still lacks a single surviving owner suite
