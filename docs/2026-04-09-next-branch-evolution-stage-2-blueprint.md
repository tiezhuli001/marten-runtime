# Next-Branch Evolution Stage 2 Blueprint For `runtime/loop.py`

## Purpose

This blueprint translates the Stage 2 decision matrix into a **function-level split plan** for `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/loop.py`.

It is intentionally narrower than a refactor wishlist.

Its job is to answer:

1. which helper clusters stay in `loop.py`
2. which helper clusters may move now without behavior change
3. which helper clusters must wait because they are still too coupled
4. which exact tests and live checks gate each slice

---

## Governing Boundaries

This blueprint is constrained by all of the following:

- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-design.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-next-branch-evolution-execution-plan.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- `/Users/litiezhu/workspace/github/marten-runtime/docs/architecture/adr/0001-thin-harness-boundary.md`

Non-negotiable interpretation:

- `RuntimeLoop.run()` remains the orchestration owner
- Stage 2 may split helper ownership, not runtime authority
- route policy stays in `loop.py`
- fail-closed provider failure handling stays in force
- no extracted module may become a planner / intent router / policy center

---

## Cluster Inventory And Ownership Decision

| cluster | current symbols | blueprint status | target owner | why this status is approved | tests that gate movement |
|---|---|---|---|---|---|
| turn orchestration / final event ownership | `RuntimeLoop.run`, `_record_failure`, `_record_recovery`, `_append_post_turn_summary` | `keep-in-loop` | `loop.py` | These functions own run lifecycle, event emission, failure recording, and post-turn bookkeeping. Moving them would spread orchestration authority instead of thinning helpers. | `tests.test_runtime_loop`, `tests.test_contract_compatibility` |
| tool-outcome summary policy and fact synthesis | `_summarize_completed_tool_episode`, `_fallback_tool_episode_summary`, `_extract_rule_based_tool_outcome_summary`, `_infer_episode_source_kind`, `_collect_structured_hint_facts`, `_merge_tool_episode_facts`, `_resolve_summary_volatile_flag` | `extract-later` | maybe `tool_outcome_flow.py` for a smaller helper subset only | The current cluster mixes summary policy, structured-fact synthesis, volatility rules, and append timing. It is not yet thin enough to move wholesale. Only a smaller pure subset may move later. | targeted summary regressions in `tests.test_runtime_loop`; broader branch regression before any later move |
| provider-failure classification and elapsed-time utility | `_is_provider_failure`, `_elapsed_ms` | `keep-in-loop` | `loop.py` | These helpers are tiny and directly tied to run orchestration semantics. Extraction would not materially improve boundaries. | `tests.test_runtime_loop`, `tests.test_contract_compatibility` |
| forced-route policy entrypoints | `_select_forced_tool_route`, `_select_automation_route`, `_select_trending_route`, `_build_explicit_github_repo_commit_payload` | `keep-in-loop` | `loop.py` | These functions decide top-level route/action policy. Moving them out would only hide route policy in another file and violate the anti-drift goal. | runtime-loop forced-route regressions; independent-port runtime/time/GitHub checks |
| pure matcher and argument-normalization helpers used by forced routes | `_is_time_query`, `_build_forced_time_payload`, `_is_automation_query`, `_is_automation_list_query`, `_is_automation_detail_query`, `_is_trending_query`, `_looks_like_automation_registration_query`, `_build_trending_arguments`, `_extract_automation_id_for_detail` | `extract-now` | extend `query_hardening.py` (preferred) or equally thin shared helper | These helpers are text/pattern/payload normalization utilities. They do not need runtime state, event emitters, or tool history handles. They are the safest first extraction seam. | `tests.test_query_hardening` first, then focused `tests.test_runtime_loop`, then contract regression if semantics move |
| deterministic direct rendering | `_render_direct_tool_text`, `_render_direct_mcp_text`, `_render_github_trending_text`, `_render_github_list_commits_text`, `_parse_mcp_result_payload` | `extract-now` | `direct_rendering.py` | This cluster transforms already-available tool output into final text and is largely pure. It is a strong candidate for behavior-preserving extraction. | render-focused `tests.test_runtime_loop`; `tests.test_gateway` if visible text changes; independent-port builtin/MCP probes if output changes |
| recovery rendering for already-successful tool results | `_recover_tool_result_text`, `RuntimeLoop._recover_successful_tool_followup_text`, `RuntimeLoop._is_generic_tool_failure_text` | `extract-later` | `recovery_flow.py` only if kept thin after direct-render extraction | This cluster depends on the direct-render helpers and is conceptually separate, but it still sits close to run/failure semantics. It should move only after direct rendering is isolated and the residual recovery seam remains thin. | recovery-focused runtime-loop tests; targeted MCP follow-up failure cases |
| Feishu-specific protocol guard ownership | `llm_client._requires_feishu_card_protocol_guard` (cross-file sidecar seam, not a `loop.py` symbol) | `extract-now` as sidecar slice | Feishu channel-owned boundary under `channels/feishu/` | This is not a `loop.py` split, but it is part of the same evolution boundary tightening. Ownership should move out of core `llm_client.py` once channel metadata/instruction materialization is ready. | `tests.test_llm_client`, `tests.test_feishu`, `tests.test_gateway`, `tests.test_contract_compatibility` |

---

## Execution Order Frozen By This Blueprint

### Slice 1 — Shared matcher convergence only

Move only the pure matcher / argument-normalization helpers into `query_hardening.py` or an equally thin shared helper.

Must remain true:

- `_select_forced_tool_route` stays in `loop.py`
- no route ordering logic leaves `loop.py`
- no new `intent_detector.py` or classifier center appears

### Slice 2 — Feishu guard migration sidecar

Move Feishu protocol ownership toward the Feishu channel boundary.

Must remain true:

- HTTP traffic must not accidentally inherit Feishu card rules
- Feishu formatting behavior must not silently weaken
- `llm_client.py` may consume already-resolved channel-specific metadata/text, but it should stop inferring Feishu protocol ownership from skill ids directly if the replacement is verified

### Slice 3 — Deterministic direct-render extraction

Move only pure render transforms for already-successful builtin/MCP tool results.

Must remain true:

- no recovery policy moves in this slice
- no route policy moves in this slice
- if a helper decides whether to recover, it does not belong in this slice

### Slice 4 — Recovery-only extraction (optional)

Attempt only after Slice 3 stays green.

Must remain true:

- provider failure before any successful tool result stays fail-closed
- event emission, failure recording, and run finalization stay in `loop.py`
- if recovery extraction needs runtime state handles or callbacks, abort the extraction and keep it in `loop.py`

### Slice 5 — Tool-outcome helper subset extraction (optional and likely partial)

Attempt only if a clearly pure/near-pure subset exists after prior slices.

Must remain true:

- summary policy, append timing, and run-level mutation remain in `loop.py` unless a smaller subset is obviously separable
- if the candidate extraction starts needing half of `RuntimeLoop`, skip it in this branch

---

## First-Code-Slice Definition

The exact first code slice approved by this blueprint is:

### First code slice

**Shared matcher convergence into `query_hardening.py` without moving route policy**

Approved candidate functions:

- `_is_time_query`
- `_build_forced_time_payload`
- `_is_automation_query`
- `_is_automation_list_query`
- `_is_automation_detail_query`
- `_is_trending_query`
- `_looks_like_automation_registration_query`
- `_build_trending_arguments`
- `_extract_automation_id_for_detail`

Explicitly **not** part of the first slice:

- `_select_forced_tool_route`
- `_select_automation_route`
- `_select_trending_route`
- `_build_explicit_github_repo_commit_payload`
- any summary/recovery/failure orchestration helper

Why this is first:

- it removes duplicated or scattered pure matcher logic
- it reduces `loop.py` density without hiding policy ownership
- it directly addresses the review recommendation about duplicated `_is_*_query` logic
- it has the clearest test seam (`tests.test_query_hardening.py`)

---

## Test Matrix Per Slice

### Slice 1 — Shared matcher convergence

Required:

1. `cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_query_hardening`
2. focused `tests.test_runtime_loop` covering time / automation / trending / GitHub route hardening
3. if matcher semantics change externally, run `tests.test_contract_compatibility tests.test_gateway`

Live checks only if externally visible routing changes:

- runtime context query
- builtin time query
- trending query

### Slice 2 — Feishu guard migration

Required:

1. `tests.test_llm_client`
2. `tests.test_feishu`
3. `tests.test_gateway`
4. `tests.test_contract_compatibility`

Live checks if visible protocol/render output changes:

- Feishu-formatted turn
- plain HTTP `/messages` turn to confirm no Feishu leakage

### Slice 3 — Direct rendering extraction

Required:

1. focused direct-render tests in `tests.test_runtime_loop`
2. `tests.test_gateway` if user-visible text paths move
3. broader runtime regression if MCP render helpers moved

Live checks if visible output changes:

- builtin time
- builtin runtime context
- GitHub latest commit
- trending
- skill load if render path is touched

### Slice 4 — Recovery extraction

Required:

1. recovery-focused `tests.test_runtime_loop`
2. `tests.test_runtime_mcp` if GitHub/MCP recovery moved
3. broader branch regression if any failure-handling seam changes

Live checks if recovery behavior changes:

- latest-commit turn with injected or reproducible follow-up failure path
- any other path whose user-visible recovery wording changed

### Slice 5 — Tool-outcome helper subset extraction

Required:

1. summary-focused `tests.test_runtime_loop`
2. broader branch regression

Live checks if summary-visible output changes:

- follow-up conversation after builtin tool
- follow-up conversation after MCP tool

---

## Stop Rules

Stop the current slice immediately if any of the following becomes true:

- the extracted helper needs runtime state objects, queue state, event emitters, or callbacks
- the extracted module starts deciding route order or route policy
- the extracted module starts owning failure recording or run finalization
- the extraction requires reintroducing degraded-success provider fallback
- the extraction requires broad prompt/capability redesign in the same commit

If any stop rule triggers, keep the helper in `loop.py`, record the reason in `STATUS.md`, and move to the next approved seam only after re-checking the matrix.

---

## Expected End State Of Stage 2

If this blueprint is followed correctly:

- `loop.py` remains the orchestration owner
- duplicated pure matcher logic converges into shared helper ownership
- Feishu protocol ownership moves closer to the Feishu channel boundary
- direct-render helpers become easier to scan and test in isolation
- recovery and summary helpers move only if the seam remains genuinely thin
- no accidental planner / intent-router / policy-center drift appears
