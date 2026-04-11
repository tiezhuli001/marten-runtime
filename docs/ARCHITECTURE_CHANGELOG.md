# Architecture Changelog

This file is the append-only architecture evolution log for `marten-runtime`.

Use it to answer:

- what architecture changed
- why the change happened
- which ADR or design doc is now authoritative
- what verification proved the new baseline

Do not use this file for day-to-day task tracking. Local continuity belongs in a local-only `STATUS.md`.

Historical verification commands in older entries may still reference pre-2026-04-11 mega-file test modules such as `tests.test_feishu` or `tests.test_runtime_loop`. For current runnable verification entrypoints, follow the active README / docs index / slimming plans instead of replaying those historical command blocks verbatim.

For this repository, `ARCHITECTURE_CHANGELOG.md` is the primary carrier of architecture timeline truth. Historical design or execution docs should be summarized here before they are archived or removed.

## Source Of Truth Rules

- Stable architectural decisions live in `docs/architecture/adr/`.
- Time-ordered architecture evolution is recorded here.
- Detailed execution history may still exist in local `STATUS.md`, but `STATUS.md` is not a repository source of truth.
- If a change updates the runtime boundary, default capability surface, or long-lived subsystem role, add an entry here.

## Entries

### 2026-04-11: Repo Slimming Shifted Test Surface Into Shards, Archived One More Branch Doc, And Started Core Seam Extraction

- Change:
  - the five legacy mega test modules were removed from the active suite:
    - `tests/test_runtime_loop.py`
    - `tests/test_feishu.py`
    - `tests/test_tools.py`
    - `tests/test_contract_compatibility.py`
    - `tests/test_runtime_mcp.py`
  - their coverage now lives under runtime-aligned shard directories:
    - `tests/runtime_loop/`
    - `tests/feishu/`
    - `tests/tools/`
    - `tests/contracts/`
    - `tests/runtime_mcp/`
  - `runtime/loop.py` shed one more pure summary-fallback seam:
    - fallback tool-outcome summary assembly now lives in `src/marten_runtime/runtime/tool_outcome_flow.py`
    - `loop.py` no longer carries the inline rule-based summary/fallback summary helpers
    - draft+fallback summary merge logic also now lives in `src/marten_runtime/runtime/tool_outcome_flow.py`
  - `src/marten_runtime/interfaces/http/bootstrap_runtime.py` removed duplicate family-tool registrations for:
    - `mcp`
    - `automation`
    - `runtime`
    - `self_improve`
  - default runtime asset truth is now thinner and shared:
    - added `src/marten_runtime/apps/runtime_defaults.py`
    - `bootstrap_runtime.py` and `config/agents_loader.py` now resolve the current default runtime asset from one shared module instead of repeating `example_assistant` path/default literals inline
  - `src/marten_runtime/runtime/llm_client.py` moved request-specific/tool-followup instruction assembly into:
    - `src/marten_runtime/runtime/llm_request_instructions.py`
  - `interfaces/http` moved serializer/provider seams out of the route/bootstrap files:
    - `src/marten_runtime/interfaces/http/channel_event_serialization.py`
    - `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
    - `src/marten_runtime/interfaces/http/feishu_runtime_services.py`
  - `channels/feishu/service.py` shed one more pure helper cluster into:
    - `src/marten_runtime/channels/feishu/service_support.py`
  - `channels/feishu/rendering.py` shed title/text-cleanup helpers into:
    - `src/marten_runtime/channels/feishu/rendering_support.py`
  - `runtime/llm_client.py` shed provider/payload helpers into:
    - `src/marten_runtime/runtime/llm_provider_support.py`
  - active docs were trimmed again by moving:
    - `docs/2026-04-09-fast-path-inventory-and-exit-strategy.md`
    - to `docs/archive/branch-evolution/2026-04-09-fast-path-inventory-and-exit-strategy.md`
  - archive was reduced again by deleting redundant branch-execution docs:
    - `docs/archive/branch-evolution/2026-04-09-next-branch-evolution-execution-plan.md`
    - `docs/archive/branch-evolution/2026-04-09-next-branch-evolution-stage-2-execution-plan.md`
  - two more absorbed historical design docs were deleted instead of archived:
    - `docs/2026-03-30-conversation-lanes-provider-resilience-design.md`
    - `docs/2026-03-30-self-improve-design.md`
- Why:
  - test sharding makes the repo smaller and easier to evolve without changing runtime behavior
  - the new core seam continues the approved “pure helper out, orchestration stays in `RuntimeLoop`” direction
  - duplicate family-tool registration was unnecessary bootstrap noise and was also stripping richer parameter schemas off the family tools
  - the fast-path inventory remained useful as branch-history evidence, but no longer deserved to stay on the active docs surface
- Source of truth:
  - `docs/superpowers/plans/2026-04-11-repo-slimming-master-plan.md`
  - `docs/superpowers/plans/2026-04-11-core-module-slimming-plan.md`
  - `docs/superpowers/plans/2026-04-11-test-suite-slimming-plan.md`
  - `docs/superpowers/plans/2026-04-11-documentation-slimming-plan.md`
  - `src/marten_runtime/runtime/tool_outcome_flow.py`
  - `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - `src/marten_runtime/apps/runtime_defaults.py`
  - `src/marten_runtime/channels/feishu/service_support.py`
  - `src/marten_runtime/channels/feishu/rendering_support.py`
  - `src/marten_runtime/runtime/llm_provider_support.py`
- Verification:
  - full unit suite:
    - `PYTHONPATH=src python -m unittest -v`
      - pass, `503` tests green after the documentation cleanup plus Feishu/LLM helper follow-up slices
  - core baseline / focused regression:
    - `PYTHONPATH=src python -m unittest -v tests.test_query_hardening tests.test_direct_rendering tests.test_recovery_flow tests.test_llm_client tests.runtime_loop.test_forced_routes tests.runtime_loop.test_direct_rendering_paths tests.runtime_loop.test_tool_followup_and_recovery tests.runtime_loop.test_context_status_and_usage tests.runtime_loop.test_automation_and_trending_routes tests.runtime_mcp.test_github_shortcuts tests.runtime_mcp.test_followup_recovery tests.feishu.test_rendering tests.feishu.test_delivery tests.feishu.test_websocket_service tests.test_gateway tests.tools.test_automation_tool tests.tools.test_runtime_and_skill_tools tests.tools.test_self_improve_tool tests.contracts.test_gateway_contracts tests.contracts.test_runtime_contracts tests.test_acceptance`
      - pass, `285` tests green
  - summary-fallback seam regression:
    - `PYTHONPATH=src python -m unittest -v tests.test_tool_outcome_flow tests.runtime_loop.test_tool_followup_and_recovery`
      - pass, `26` tests green
  - bootstrap dedupe regression:
    - `PYTHONPATH=src python -m unittest -v tests.contracts.test_runtime_contracts.RuntimeContractTests.test_runtime_bootstrap_preserves_family_tool_parameter_schemas tests.test_gateway tests.tools.test_automation_tool tests.tools.test_runtime_and_skill_tools tests.tools.test_self_improve_tool tests.contracts.test_gateway_contracts tests.contracts.test_runtime_contracts`
      - pass, `88` tests green
  - live `/messages` verification against updated local services:
    - plain chat: final reply succeeded
    - builtin time: final reply succeeded and used `time`
    - builtin runtime: final reply succeeded and used `runtime`
    - GitHub MCP `get_me`: final reply succeeded and used `mcp`
    - skill load `example_time`: final reply succeeded and used `skill`
    - artifacts:
      - `/Users/litiezhu/workspace/github/marten-runtime/.logs/local_feishu_simulation_20260411.json`
      - `/Users/litiezhu/workspace/github/marten-runtime/.logs/local_feishu_simulation_20260411_port8002.json`
      - `/Users/litiezhu/workspace/github/marten-runtime/.logs/local_feishu_simulation_20260411_port8003.json`
      - `/Users/litiezhu/workspace/github/marten-runtime/.logs/local_feishu_simulation_20260411_port8004.json`

### 2026-04-10: Automation Family Direct Render Was Unified Behind One Thin Follow-Up Seam

- Change:
  - successful `automation` family-tool turns no longer depend on a second LLM pass to summarize already-complete structured results
  - the current direct-render surface for `automation` now covers:
    - `list`
    - `detail`
    - `register`
    - `update`
    - `pause`
    - `resume`
    - `delete`
  - `runtime/loop.py` no longer carries an inline `automation list only` gate; instead it delegates follow-up direct-render eligibility to one thin helper in `runtime/direct_rendering.py`
- Why:
  - live validation showed the earlier `automation.list`-only shortcut fixed the immediate list-loss problem, but left the family in an inconsistent state where list and detail/mutation actions followed different rendering contracts
  - the successful `automation` tool results are already complete user-facing answers, so a second LLM turn added latency and formatting drift without adding meaningful reasoning value
  - the accepted boundary remained:
    - keep tool selection LLM-first
    - keep `loop.py` thin
    - move family-level direct-render policy into a small deterministic seam rather than spreading action-specific branches through the runtime loop
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/direct_rendering.py`
  - `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/tools/builtins/automation_tool.py`
- Verification:
  - focused TDD / regression:
    - `PYTHONPATH=src python -m unittest -v tests.test_tools.ToolTests.test_render_automation_tool_text_formats_detail_result tests.test_tools.ToolTests.test_render_automation_tool_text_formats_register_result tests.test_tools.ToolTests.test_render_automation_tool_text_formats_pause_resume_update_delete_results tests.test_runtime_loop.RuntimeLoopTests.test_runtime_uses_llm_first_for_natural_language_automation_detail_query tests.test_runtime_loop.RuntimeLoopTests.test_runtime_allows_main_agent_to_register_automation_via_family_tool tests.test_runtime_loop.RuntimeLoopTests.test_runtime_does_not_misroute_automation_registration_prompt_to_trending_fast_path`
      - pass
  - broader regression:
    - `PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_feishu tests.test_gateway tests.test_tools tests.test_direct_rendering`
      - pass, `195` tests green
  - live HTTP verification after restart:
    - `当前有哪些定时任务？`
      - `run_10f682d9`, `llm_request_count = 1`, `tool_payload.action = list`
    - `请看下 automation_id 为 github_trending_digest_2230 的定时任务详情`
      - `run_7950b85e`, `llm_request_count = 1`, `tool_payload.action = detail`

### 2026-04-09: Temporary Fast-Path Deviations And Stage 2 Exit Conditions Were Made Explicit

- Change:
  - the next-branch evolution documentation now explicitly records which host-side fast paths are accepted temporary deviations versus shrink/remove candidates
  - the following items are now recorded as explicit temporary deviations instead of implicit historical behavior:
    - runtime context forced route
    - time forced route
    - request-specific GitHub instruction shaping
  - Feishu card protocol ownership is now documented as a remove-when-replacement-verified boundary: the behavior remains required, but direct Feishu protocol inference should move toward the Feishu channel layer once verified
  - Stage 2 now also has a function-level `runtime/loop.py` split blueprint that freezes the extraction order and stop rules before code movement
- Why:
  - the 2026-04-09 review correctly called out that several fast paths had become de facto architecture decisions without being written down as such
  - before further extraction work, the repo needed explicit answers for:
    - which deviations are consciously tolerated for now
    - what evidence is required before shrinking or removing them
    - which `runtime/loop.py` seams are real versus only superficially separable
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [2026-04-09 Next-Branch Evolution Design](./archive/branch-evolution/2026-04-09-next-branch-evolution-design.md)
  - [2026-04-09 Fast-Path Inventory And Exit Strategy](./archive/branch-evolution/2026-04-09-fast-path-inventory-and-exit-strategy.md)
  - [2026-04-09 Next-Branch Evolution Stage 2 Blueprint](./archive/branch-evolution/2026-04-09-next-branch-evolution-stage-2-blueprint.md)
- Verification:
  - documentation consistency checks:
    - confirmed the fast-path inventory no longer contains `pending-stage-2-decision` rows
    - confirmed the Stage 2 blueprint exists and names the first approved code slice
    - confirmed the Stage 2 reference plan includes both `_is_*_query` shared-helper convergence and Feishu-guard migration tasks

### 2026-04-08: Tool-Result Recovery Now Wins Over Late Follow-Up Failures During GitHub MCP Turns

- Change:
  - the runtime now prefers already-available deterministic tool renders over late follow-up failures when a GitHub MCP turn has already produced enough result to answer
  - the thin recovery surface now covers three real live failure classes:
    - first-LLM provider failure on explicit GitHub latest-commit queries
    - `llm_second` provider timeout after a successful `github.list_commits` call
    - `ToolCallRejected` on `llm_second` after a successful `github.list_commits` call
  - deterministic `github.list_commits` rendering now covers both:
    - successful latest-commit payloads
    - `404 Not Found` error payloads
- Why:
  - extreme live queue/soak replays still exposed a thin but real bad-ending class: the runtime sometimes had the correct GitHub commit result in hand, but a late follow-up model failure or disallowed extra tool request could still downgrade the user-visible reply into a generic failure
  - this was not a routing or MCP execution problem; it was a final-turn recovery problem
  - the approved boundary remained: keep harness thin, recover from already-present tool results, and do not add a heavier planner/constraint subsystem
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [2026-04-07 LLM Tool Episode Summary Design](./archive/2026-04-07-llm-tool-episode-summary-design.md)
  - local continuity details in `STATUS.md`
- Verification:
  - focused regression:
    - `PYTHONPATH=src python -m unittest -v tests.test_runtime_loop.RuntimeLoopTests.test_runtime_recovers_direct_commit_text_when_followup_requests_disallowed_tool tests.test_runtime_loop.RuntimeLoopTests.test_runtime_recovers_direct_commit_text_when_followup_provider_call_times_out tests.test_runtime_loop.RuntimeLoopTests.test_runtime_recovers_explicit_github_404_commit_query_after_first_llm_provider_failure`
      - pass
  - broader regression:
    - `PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_gateway tests.test_feishu tests.test_runtime_mcp`
      - pass, `170` tests green
  - live pressure verification:
    - `/Users/litiezhu/workspace/github/marten-runtime/.logs/ultra_mix_live_20260408_225729.json`
      - 16-turn mixed soak, all succeeded
    - `/Users/litiezhu/workspace/github/marten-runtime/.logs/extreme_long_live_20260408_225749.json`
      - 20-turn mixed soak, all succeeded
    - `/Users/litiezhu/workspace/github/marten-runtime/.logs/extreme_long_live_20260408_225949.json`
      - second 20-turn mixed soak, all succeeded
    - `/Users/litiezhu/workspace/github/marten-runtime/.logs/ultra_queue_live_20260408_225853.json`
      - captured the pre-fix `TOOL_NOT_ALLOWED after successful MCP` edge case
    - `/Users/litiezhu/workspace/github/marten-runtime/.logs/ultra_queue_recheck_live_20260408_230832.json`
      - same-conversation queue recheck after the fix, all 10 requests succeeded
    - `/Users/litiezhu/workspace/github/marten-runtime/.logs/extreme_queue_live_20260408_225741.json`
      - extreme queue replay succeeded
    - `/Users/litiezhu/workspace/github/marten-runtime/.logs/extreme_queue_live_20260408_230114.json`
      - second extreme queue replay succeeded

### 2026-04-08: Explicit GitHub MCP Repo Queries Now Use Thin Direct MCP Calls, And Queue Wait Is Bound To Real Runs

- Change:
  - explicit GitHub repo queries that already identify a concrete repo now avoid extra MCP exploration and route to one thin direct GitHub MCP call on the first tool step
  - the current happy-path behavior remains:
    - explicit repo-metadata queries use `github.search_repositories(query=repo:owner/name)` and still pay one follow-up LLM turn
    - explicit latest-commit queries use `github.list_commits(perPage=1)` and still pay one follow-up LLM turn on the normal success path
  - the current direct deterministic rendering surface is narrower than the initial change wording implied:
    - it is available for `github.list_commits(perPage=1)` when the runtime already has enough tool result to recover from a late follow-up failure
    - it does **not** replace the normal follow-up LLM on the repo-metadata path
  - run diagnostics now bind lane wait signals onto the actual runtime run record with:
    - `queue_depth_at_enqueue`
    - `queue_wait_ms`
    - `waited_in_lane`
- Why:
  - operators were still seeing GitHub MCP turns take ~tens of seconds even after tool routing had already been narrowed, because the expensive part had become the post-tool follow-up LLM
  - at the same time, same-conversation follow-up checks such as `现在上下文窗口用多少？` looked confusing in practice because queue state only existed in lane stats, not on the eventual run that answered the user
  - later implementation and review made the steady-state behavior clearer: direct MCP routing is the baseline improvement here, while deterministic direct render is a narrower recovery tool rather than the general repo-query end state
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [2026-04-07 LLM Tool Episode Summary Design](./archive/2026-04-07-llm-tool-episode-summary-design.md)
  - `/Users/litiezhu/workspace/github/marten-runtime/tests/test_runtime_loop.py`
  - local continuity details in `STATUS.md`
- Verification:
  - `PYTHONPATH=src python -m unittest -v tests.test_runtime_lanes tests.test_runtime_loop tests.test_feishu tests.test_contract_compatibility`
    - pass, `138` tests green at the time of the original change
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `389` tests green at the time of the original change
  - current code/test alignment to preserve in closure review:
    - `tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_query_to_direct_mcp_call`
      - proves explicit repo-metadata happy path still uses `len(llm.requests) == 2` and `run.llm_request_count == 2`
    - `tests.test_runtime_loop.RuntimeLoopTests.test_runtime_shortcuts_explicit_github_repo_commit_query_to_list_commits`
      - proves explicit latest-commit happy path still uses `len(llm.requests) == 2` and `run.llm_request_count == 2`
    - queued follow-up runtime queries still carry run-level queue diagnostics such as `queue_depth_at_enqueue` and `queue_wait_ms`

### 2026-04-08: Direct Runtime Context-Status Turns No Longer Claim A Tool-Followup Peak That Never Happened

- Change:
  - direct `runtime.context_status` turns now keep run-level peak semantics aligned with the actual turn shape
  - when the runtime returns the builtin status text directly without a second LLM follow-up, the diagnostics stay on:
    - `peak_stage=initial_request`
    - `peak_input_tokens_estimate == initial_input_tokens_estimate` unless a real heavier stage occurred
  - `tool_result.current_run` now mirrors the run diagnostics instead of fabricating `tool_followup` on runtime-only turns
- Why:
  - operators were seeing an internal inconsistency where outer run diagnostics said `initial_request` but the embedded runtime tool payload still claimed `tool_followup`
  - that made `runtime.context_status` less trustworthy precisely in the path intended for debugging context pressure
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [2026-04-07 Context Usage Accuracy Design](./archive/2026-04-07-context-usage-accuracy-design.md)
  - [2026-04-07 Context Usage Accuracy Plan](./archive/plans/2026-04-07-context-usage-accuracy-plan.md)
- Verification:
  - `PYTHONPATH=src python -m unittest -v tests.test_runtime_loop tests.test_tools tests.test_feishu`
    - pass, `134` tests green
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `382` tests green
  - live `/messages` verification after local service restart confirmed:
    - `run_0f57407b`: `initial=2789`, `peak=2789`, outer `peak_stage=initial_request`, embedded `current_run.peak_stage=initial_request`
    - `run_eda8b556`: `initial=2960`, `peak=2960`, outer `peak_stage=initial_request`, embedded `current_run.peak_stage=initial_request`

### 2026-04-07: Context Usage Accuracy Became Provider-First With Payload-Based Preflight Estimation

- Change:
  - `runtime.context_status` no longer relies on a partial-text `len(text)//4` estimate as its primary visible truth
  - OpenAI-compatible replies now normalize provider `usage` into one runtime shape with:
    - `input_tokens`
    - `output_tokens`
    - `total_tokens`
    - optional cached/reasoning fields
  - preflight estimation now runs against the final outbound payload shape instead of a hand-picked subset of prompt text
  - the runtime now distinguishes:
    - `last_actual_usage`
    - `next_request_estimate`
    - `estimate_source`
    - raw `context_window` vs `effective_window`
  - run/session state now persists:
    - latest actual provider usage
    - preflight estimate and estimator kind
  - run-level pressure now distinguishes:
    - initial outbound request size for the turn
    - peak preflight pressure after tool-result injection
    - peak stage (`initial_request` vs `tool_followup`)
  - `runtime.context_status` now surfaces a compact `current_run` block so operators can see whether the turn became much heavier only after tool/MCP payload injection
  - fallback order is now fixed as:
    - provider actual usage
    - tokenizer family backend
    - deterministic script-aware `rough`
- Why:
  - the previous visible usage number was useful only as a rough trend and undercounted tool schema, tool history, and wrapper overhead
  - compaction decisions and user-facing status needed a number with materially better reference value without widening the thin runtime architecture
  - the approved boundary was to improve accounting quality, not to grow a heavy prompt-accounting or memory platform
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [2026-04-07 Context Usage Accuracy Design](./archive/2026-04-07-context-usage-accuracy-design.md)
  - [2026-04-07 Context Usage Accuracy Plan](./archive/plans/2026-04-07-context-usage-accuracy-plan.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_runtime_usage tests.test_usage_estimator tests.test_models tests.test_runtime_loop tests.test_session tests.test_tools tests.test_contract_compatibility -v`
    - pass, `104` tests green
  - `PYTHONPATH=src python -m unittest tests.test_runtime_usage tests.test_usage_estimator tests.test_models tests.test_session tests.test_runtime_capabilities tests.test_runtime_context tests.test_runtime_loop tests.test_tools tests.test_contract_compatibility tests.test_acceptance -v`
    - pass, `126` tests green
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `326` tests green
  - local HTTP `/messages` smoke confirmed:
    - plain turn, runtime status turn, tool-heavy automation turn, and follow-up status turn all stayed on the real runtime chain
    - preflight estimates grew with added/tool-heavy turns (`2374 -> 2422 -> 2473 -> 2525`)
    - session-scoped latest actual usage updated from provider/test-double usage
  - controlled pressure probe confirmed:
    - plain turn: `initial=87`, `peak=87`
    - skill-heavy turn: `initial=398`, `peak=398`
    - MCP-heavy turn: `initial=221`, `peak=1573`, `peak_stage=tool_followup`
  - real provider sequence on conversation `usage-accuracy-live-20260407b` confirmed:
    - `当前上下文窗口多大？`, `现在上下文用了多少？`, and `上下文状态怎么样，需不需要压缩？` each called `runtime.context_status`
    - `当前有哪些自动化任务？如果没有就直接说没有。` called `automation`
    - tokenizer preflight estimates increased across the sequence (`2383 -> 2443 -> 2543 -> 2653 -> 2694`)
    - runtime tool surfaced previous-call actual totals (`2069 -> 2229 -> 2303`) instead of stale remembered values
  - follow-up summary tightening + real `/messages` live comparison on 2026-04-07 confirmed:
    - targeted summary tests now verify that completed tool-heavy runs explicitly say `峰值主要来自工具结果注入后`, while non-tool peaks do not get that label
    - real provider `/messages` probes produced:
      - plain: `initial=2369`, `peak=2369`, `peak_stage=initial_request`
      - builtin `runtime`: `initial=2382`, `peak=2419`, `peak_stage=tool_followup`
      - MCP-heavy: `initial=2441`, `peak=8714`, `peak_stage=tool_followup`
      - `skill.load(example_time)`: `initial=2415`, `peak=2415`, `peak_stage=initial_request`
    - this confirmed that the large context spikes show up mainly in tool/MCP result injection paths, while small skill bodies may still fit under the initial-request ceiling

### 2026-04-07: Session Replay And Runtime Follow-up Semantics Were Tightened For Real Context-Status Queries

- Change:
  - session replay now drops the paired preceding user turn when a noisy assistant turn is trimmed from replay
  - runtime capability text now explicitly requires natural-language context-window / context-usage / compaction-health questions to call `runtime.context_status` instead of answering from remembered values
  - runtime tool follow-up now injects a narrow system instruction so the post-tool answer stays focused on the current runtime result and does not re-open unrelated older topics
- Why:
  - live Feishu/HTTP validation exposed two real drift paths:
    - trimming a noisy assistant reply could leave an orphaned old user request in replay, causing later turns to unexpectedly re-answer that stale request
    - after one successful `runtime.context_status` call, later paraphrases like `现在上下文用了多少` could be answered from stale memory instead of querying the current run state again
  - these are runtime continuity / tool-semantics problems, not product-level feature gaps
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [2026-04-06 Thin LLM Context Compaction Design](./archive/2026-04-06-thin-llm-context-compaction-design.md)
  - [2026-04-07 Thin LLM Context Compaction Plan](./archive/plans/2026-04-07-thin-llm-context-compaction-plan.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_runtime_capabilities tests.test_models -v`
    - pass, `19` tests green
  - `PYTHONPATH=src python -m unittest tests.test_runtime_context tests.test_runtime_loop tests.test_contract_compatibility tests.test_acceptance tests.test_feishu -v`
    - pass, `123` tests green
  - live HTTP/provider sequence on `debug-seq-ctx-2` confirmed:
    - no GitHub trending content leaked into context-status answers
    - `当前上下文窗口多大？`, `现在上下文用了多少`, and `上下文状态怎么样，需不需要压缩？` each called `runtime.context_status`
    - reported usage increased with the conversation (`932 -> 966 -> 995`) instead of repeating a stale prior value
  - live same-conversation overlap probe on `debug-serial-ctx-1` confirmed ordered runs:
    - `run_a400bb50` (`mcp github_trending`)
    - `run_d0d22802` (`runtime.context_status`)

### 2026-04-07: Runtime Context Status Became A Builtin Family Tool Instead Of Inline Channel Telemetry

- Change:
  - added one new builtin family tool `runtime` with action `context_status`
  - the default assistant-visible family-tool surface is now:
    - `automation`
    - `mcp`
    - `runtime`
    - `self_improve`
    - `skill`
    - `time`
  - the runtime tool returns a compact, user-readable context summary instead of dumping full internal telemetry
  - tool execution now supports an internal `tool_context` channel so thin builtins can read current run/session/request state without polluting model-visible payloads
  - the current agent model profile is resolved from routing/bootstrap state, so `context_status` does not degrade to `unknown` when a test double or custom LLM client omits `profile_name`
- Why:
  - context-window usage and compaction state are useful user-facing questions, but they should not bloat every normal channel reply
  - the approved boundary is: user asks → model calls one runtime builtin → builtin returns a concise summary → model decides how to explain it
  - this keeps detailed telemetry in diagnostics/logs while giving the model one safe, thin inspection path
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [2026-04-06 Thin LLM Context Compaction Design](./archive/2026-04-06-thin-llm-context-compaction-design.md)
  - [2026-04-07 Thin LLM Context Compaction Plan](./archive/plans/2026-04-07-thin-llm-context-compaction-plan.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_runtime_capabilities tests.test_tools tests.test_runtime_loop tests.test_contract_compatibility tests.test_acceptance -v`
    - pass, `84` tests green
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `310` tests green
  - local HTTP smoke confirmed:
    - `/messages` can trigger `runtime.context_status`
    - the tool result stays compact and user-readable
    - the reported `model_profile` matches the selected routed profile


### 2026-04-07: Thin LLM Context Compaction Became The Long-Thread Continuity Baseline

- Change:
  - added one thin compact-checkpoint layer around oversized conversation history only
  - the runtime now stores the latest compact artifact in session state and reuses it on later turns
  - proactive compaction can trigger from model-window-aware pressure thresholds
  - reactive compaction can retry once after prompt-too-long-like provider failures
  - HTTP `/messages` now passes per-agent compaction settings, persists compact artifacts, and reinjects compact summaries on continuation turns
  - the compact path preserves runtime scaffolding and does **not** replace:
    - `system_prompt`
    - app/bootstrap prompt assets
    - skill summaries or activated skill bodies
    - capability catalog text
    - MCP/tool schema exposure
- Why:
  - the runtime already had better replay/working-context governance, but very long threads still needed one thin checkpoint path when model context pressure rises
  - the chosen boundary keeps the architecture inside the approved MVP scope instead of growing into a memory platform, background summarizer, or retrieval layer
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [2026-04-06 Thin LLM Context Compaction Design](./archive/2026-04-06-thin-llm-context-compaction-design.md)
  - [2026-04-07 Thin LLM Context Compaction Plan](./archive/plans/2026-04-07-thin-llm-context-compaction-plan.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_models tests.test_session tests.test_compaction_trigger tests.test_compaction_runner tests.test_runtime_context tests.test_runtime_loop tests.test_acceptance -v`
    - pass, `63` tests green
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `302` tests green
  - local HTTP end-to-end smoke confirmed:
    - proactive checkpoint creation
    - compact-summary reinjection
    - diagnostics visibility for the run
    - final reply continuity after compaction

### 2026-04-05: GitHub Trending Became A Repo-Local MCP Sidecar Instead Of A Skill-Only Approximation

- Change:
  - added one repo-local stdio MCP sidecar at [github_trending.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/mcp_servers/github_trending.py)
  - the new sidecar exposes exactly one tool:
    - `trending_repositories`
  - registered the sidecar through [mcps.json](/Users/litiezhu/workspace/github/marten-runtime/mcps.json) instead of adding a runtime builtin or GitHub-specific routing branch
  - the temporary GitHub skill bridge was first narrowed and has now been removed; trending requests now rely on the MCP sidecar plus automation-boundary compatibility instead of a GitHub-specific skill file
- Why:
  - the upstream official GitHub MCP surface currently exposes repository search but not a real trending feed
  - using `search_repositories` plus prompt/skill rules was a semantic approximation and added avoidable LLM/tool turns
  - the thinner boundary is: model selects MCP → sidecar fetches/parses GitHub Trending → renderer formats result
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [2026-04-05 GitHub Trending MCP Plan](./archive/plans/2026-04-05-github-trending-mcp-plan.md)
- Verification:
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `269` tests green
  - live runtime diagnostics now discover `github_trending` with one tool `trending_repositories`
  - live request `帮我看下今天 github 热门仓库` on run `run_a2d2f279` used:
    - `mcp.list`
    - `mcp.call(server_id=github_trending, tool_name=trending_repositories)`
  - corrected live parse output now preserves canonical repo URLs and sane `stars_total` extraction from GitHub Trending HTML
  - live GitHub Trending HTML re-check on `2026-04-06` confirmed the returned list follows the official page order rather than a local descending-stars sort
  - latest Feishu wording now explicitly states `按 GitHub Trending 页面顺序` and avoids repeating fetched time in both the summary and the ordering note
### 2026-04-02: Feishu Outbound Rendering Settled On One Generic Renderer + One Thin Always-On Skill

- Change:
  - finalized the Feishu outbound boundary around:
    - one generic renderer in [rendering.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/rendering.py)
    - transport-only delivery in [delivery.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/delivery.py)
    - one thin always-on Feishu skill in [feishu_channel_formatting/SKILL.md](/Users/litiezhu/workspace/github/marten-runtime/skills/feishu_channel_formatting/SKILL.md)
  - the generic renderer now owns:
    - protocol parsing for observed provider output shapes
    - one schema `2.0` card skeleton
    - unified final/error card presentation
    - structured-reply canonicalization that strips duplicated visible bullets outside `feishu_card`
  - the Feishu skill now enforces the stable channel rule:
    - one-line direct answers may stay plain text
    - multi-line or grouped replies should end with one trailing `feishu_card`
  - no business-specific renderer taxonomy, delivery-side semantic classification, or host-side intent routing was introduced
- Why:
  - the real Feishu issues were a mix of presentation flatness, provider output drift, and duplicate visible content
  - those problems were best solved by strengthening one generic renderer and one thin channel skill, not by adding more renderer families or prompt-heavy host logic
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [Feishu Generic Card Protocol Design](./2026-04-01-feishu-generic-card-protocol-design.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_skills tests.test_contract_compatibility tests.test_runtime_loop -v`
    - pass
  - focused renderer regressions cover:
    - protocol-backed card rendering
    - inline / wrapped / invoke-style protocol parsing
    - one-line final and error card rendering
    - duplicate visible bullet stripping
  - local and live Feishu smoke confirmed the renderer path stays stable without widening the architecture

### 2026-04-01: `time` Capability Text Was Hardened For Natural-Language Clock Queries

- Change:
  - strengthened the `time` capability summary, usage rules, and tool description so natural-language clock requests like `现在几点` and `what time is it` explicitly route through the live `time` tool instead of relying on model memory
  - kept the fix inside capability/tool exposure text and did not add a new bootstrap-level intent rule or host-side router
- Why:
  - the previous live validation exposed a real prompt-to-tool compliance gap: the model sometimes answered current-time questions from stale memory
  - this boundary belongs in tool semantics, not in a widened bootstrap policy layer
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_runtime_capabilities tests.test_contract_compatibility tests.test_bootstrap_prompt tests.test_models -v`
    - pass, `44` tests green
  - focused live probes confirmed natural-language current-time requests now execute the `time` tool instead of answering from memory

### 2026-04-01: Repository Hygiene Boundaries Were Tightened

- Change:
  - added `apps/example_assistant/SYSTEM_LESSONS.md` to `.gitignore`
  - formalized `SYSTEM_LESSONS.md` as a runtime-managed artifact instead of a repository baseline file
  - introduced `docs/archive/` and moved completed one-off audits and the completed refinement plan out of the primary docs path
  - recorded the bootstrap cleanup plan at `docs/archive/plans/2026-04-01-bootstrap-assembly-hygiene-plan.md`
- Why:
  - runtime-generated files should not keep dirtying the repository after normal live runs
  - completed audits and plans were competing with current source-of-truth docs and active reading paths
  - the main remaining structural hotspot is `interfaces/http/bootstrap.py`, so the next active plan should focus there explicitly
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_bootstrap_prompt tests.test_self_improve_gate tests.test_contract_compatibility tests.test_skills -v`
  - docs and README entry paths now separate active docs from archive docs

### 2026-03-31: ADR + Architecture Changelog Becomes The Long-Term Source Of Truth

- Change:
  - introduced `docs/architecture/adr/` as the stable home for non-drifting architecture decisions
  - introduced this `docs/ARCHITECTURE_CHANGELOG.md` as the append-only architecture evolution log
  - moved repository continuity away from tracked `STATUS.md`; `STATUS.md` is now local-only and ignored by git
- Why:
  - `STATUS.md` was useful for active execution, but it mixed temporary task state with long-lived architecture truth
  - future agents need a durable source of truth for boundaries without replaying local execution history
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Supporting design docs:
  - [Private Agent Harness Design](./2026-03-29-private-agent-harness-design.md)
  - [Progressive Disclosure Capability Design](./2026-03-31-progressive-disclosure-llm-first-capability-design.md)
- Verification:
  - `PYTHONPATH=src python -m unittest -v`
  - docs index and live verification checklist updated to point at ADR + changelog rather than tracked `STATUS.md`

### 2026-03-31: Progressive Disclosure Refinement And Harness-Only Tightening Is The Current Baseline

- Change:
  - locked the default assistant-visible surface to five family entrypoints: `automation`, `mcp`, `self_improve`, `skill`, `time`
  - kept skill exposure as summary-first with body-on-demand
  - kept MCP exposure as family-level and server-summary-first, with detail and call on demand
  - removed remaining host-side keyword routing and extra prompt narration
- Why:
  - the runtime must stay a thin harness instead of drifting into host-side intent routing or a heavyweight capability framework
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
- Supporting design docs:
  - [Progressive Disclosure Capability Design](./2026-03-31-progressive-disclosure-llm-first-capability-design.md)
  - [Architecture Audit](./archive/audits/ARCHITECTURE_AUDIT.md)
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_models tests.test_bootstrap_prompt tests.test_runtime_capabilities tests.test_contract_compatibility -v`
  - live probes confirmed plain chat, `time`, `mcp`, automation summary, and self-improve summary on the runtime path

### 2026-03-30: Conversation Lanes And Provider Resilience Became Part Of The Runtime Baseline

- Change:
  - added same-conversation FIFO queueing for HTTP and Feishu interactive ingress
  - added retry normalization for retryable provider transport and upstream failures
  - replaced placeholder queue diagnostics with live `conversation_lanes` diagnostics
- Why:
  - overlapping turns and provider jitter were destabilizing the live interactive chain
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
- Supporting design docs:
  - timeline truth absorbed into ADR 0001 + this changelog; the original conversation-lanes/provider-resilience design doc was removed during repo slimming
- Verification:
  - `PYTHONPATH=src python -m unittest tests.test_runtime_lanes tests.test_gateway tests.test_feishu tests.test_provider_retry tests.test_runtime_loop tests.test_contract_compatibility -v`
  - `/diagnostics/queue` now returns live lane stats instead of placeholder output

### 2026-03-30: Self-Improve Was Accepted As A Narrow Runtime Learning Slice

- Change:
  - added failure/recovery evidence recording, candidate generation, lesson acceptance, and active lesson export through `SYSTEM_LESSONS.md`
  - kept self-improve scoped to runtime learning and candidate management, not generic memory or architecture truth
- Why:
  - the runtime needs a thin way to preserve recurring operational lessons without widening into a memory platform
- Source of truth:
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Supporting design docs:
  - timeline truth absorbed into ADR 0003 + this changelog; the original self-improve design doc was removed during repo slimming
- Verification:
  - self-improve tests and live runtime summary paths remain green
