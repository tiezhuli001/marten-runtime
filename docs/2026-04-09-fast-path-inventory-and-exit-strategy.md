# 2026-04-09 Fast-Path Inventory And Exit Strategy

## Purpose

This document began as the **Stage 1 inventory baseline** for host-side fast paths, forced routes, direct-render shortcuts, and recovery shortcuts in `marten-runtime`.

It is now also the **Stage 2 decision matrix** for the next-branch evolution work.

Its job is to make three things explicit before any code motion:

1. which shortcuts remain temporarily accepted
2. which shortcuts are shrink/remove candidates but not yet safe to remove
3. which helper clusters may move structurally without changing behavior

---

## Non-Negotiable Global Boundary

The current runtime contract remains:

- **LLM-first by default**
- provider failures remain **fail-closed**
- no degraded-success fallback may be reintroduced for provider-auth or provider-transport failure before any useful tool result exists
- Stage 2 may reorganize helper ownership, but it may not silently convert the runtime into a broader planner / intent router / policy center

This means:

- direct render of already-successful tool results is still allowed
- recovery from already-available tool results is still allowed
- provider failure before any successful tool result is **not** eligible for success-style fallback

---

## Decision Status Vocabulary

Each row below must use exactly one Stage 2 decision status:

- `retain-now-with-explicit-deviation`
- `extract-without-behavior-change`
- `shrink-later-after-replacement-evidence`
- `remove-when-replacement-verified`

Interpretation:

- `retain-now-with-explicit-deviation`
  - keep the behavior in this branch
  - explicitly record why it is a conscious deviation from a purer LLM-only boundary
  - define what evidence would justify removing it later
- `extract-without-behavior-change`
  - keep the behavior, but it is safe to move helper ownership if the seam stays thin
- `shrink-later-after-replacement-evidence`
  - keep the behavior for now, but Stage 2 should treat it as a scope-reduction candidate rather than a stable permanent surface
- `remove-when-replacement-verified`
  - current ownership/location is not accepted as long-term architecture; removal or relocation is the intended end state once replacement proof exists

---

## Stage 2 Decision Matrix

| surface | current owner | approved stage-2 status | why this status is approved now | required replacement / exit evidence | preferred owner after evolution | required verification if changed |
|---|---|---|---|---|---|---|
| runtime context forced route | `src/marten_runtime/runtime/loop.py::_select_forced_tool_route` + `src/marten_runtime/runtime/query_hardening.py::is_runtime_context_query` | `retain-now-with-explicit-deviation` | Real-time context usage / compaction-health questions must not be answered from stale model memory. Current live baseline proves this route prevents wrong or stale context answers and avoids wasting the first LLM turn. | Remove only after repeated source-backed live verification shows the model reliably selects `runtime.context_status` across Chinese/English/paraphrased context-health prompts without stale-number regressions. | route policy stays in `loop.py`; pure matcher ownership may remain shared in `query_hardening.py` | focused `tests.test_runtime_loop`; independent-port runtime-context query; follow-up context query after tool-heavy turn; verify tool call + `llm_request_count` |
| time forced route | `src/marten_runtime/runtime/loop.py::_select_forced_tool_route` + `src/marten_runtime/runtime/loop.py::_is_time_query` | `retain-now-with-explicit-deviation` | Current-time questions are a narrow real-time class where remembered or hallucinated answers are obviously unacceptable. The forced route also preserves the already-verified zero-LLM builtin path. | Remove only after live verification proves the model always calls builtin `time` for current-time/timezone questions and never answers from memory. | route policy stays in `loop.py`; pure matcher/payload extraction may move to `query_hardening.py` | focused runtime-loop tests; independent-port builtin time query; verify text shape, tool call, and `llm_request_count=0` if still intended |
| automation forced route family | `src/marten_runtime/runtime/loop.py::_select_automation_route` + `_is_automation_*_query` | `shrink-later-after-replacement-evidence` | The family tool still protects against list/detail prompts being answered as loose prose or routed to the wrong action. However, this is a stronger host-side routing deviation and should be shrunk once model/tool-call behavior is proven stable enough. | Shrink only after live and regression evidence shows correct `automation` family tool selection across list/detail/create ambiguity, including mixed Chinese/English prompts, without route-order hacks. | route policy remains in `loop.py`; pure matchers may converge into `query_hardening.py` | runtime-loop + gateway automation regressions; independent-port automation list/detail probes if routing changes |
| trending forced route family | `src/marten_runtime/runtime/loop.py::_select_trending_route` + `_is_trending_query` | `shrink-later-after-replacement-evidence` | The current route carries typo tolerance and avoids collisions with automation-registration phrasing. It is useful, but it is still a host-side NL routing surface that should eventually shrink. | Shrink only after replacement proof covers trending typos, period selection (`daily`/`weekly`/`monthly`), and automation-vs-trending disambiguation without regressing tool choice. | route policy remains in `loop.py`; pure matchers/argument builders may converge into shared helper ownership | focused trending regression; independent-port trending query verification; inspect MCP tool call shape |
| explicit GitHub repo commit payload shortcut | `src/marten_runtime/runtime/loop.py::_build_explicit_github_repo_commit_payload` + shared repo extraction helpers | `shrink-later-after-replacement-evidence` | Explicit latest-commit requests are still a known confusion point for models (`updated_at` vs latest commit). The payload shortcut remains justified short-term, but it is not accepted as a permanent broad routing policy. | Shrink only after the model repeatedly chooses `github.list_commits(perPage=1)` correctly for URL and `owner/repo` commit queries without extra exploration or metadata confusion. | top-level action selection remains in `loop.py`; repo extraction stays shared | focused runtime-loop GitHub latest-commit tests; independent-port explicit latest-commit probe; inspect `/diagnostics/run/{run_id}` |
| explicit GitHub repo metadata shortcut | `src/marten_runtime/runtime/loop.py` + shared repo metadata detection helpers | `shrink-later-after-replacement-evidence` | Explicit repo metadata prompts still benefit from narrow hardening because the model can over-explore MCP or confuse repo lookup with commit lookup. Long-term, this should shrink behind stronger capability/prompt evidence. | Shrink only after repeated live probes show direct `search_repositories(query=repo:owner/name)` selection without exploratory tool chatter or commit/metadata confusion. | top-level action selection remains in `loop.py`; pure repo matchers stay shared | focused runtime-loop metadata tests; independent-port repo metadata probe; inspect tool call + follow-up behavior |
| deterministic direct render for builtin tools | `src/marten_runtime/runtime/loop.py::_render_direct_tool_text` | `extract-without-behavior-change` | This is not a planner surface. It is a deterministic rendering shortcut for already-successful builtin results and keeps low-risk builtin turns thin. | Future removal would require proof that LLM follow-up adds value without cost/instability, but that is not a goal of this branch. | `src/marten_runtime/runtime/direct_rendering.py` if the seam stays pure | runtime-loop render regressions; independent-port builtin time/runtime checks if visible text changes |
| deterministic direct render for MCP results | `src/marten_runtime/runtime/loop.py::_render_direct_mcp_text`, `_render_github_trending_text`, `_render_github_list_commits_text` | `extract-without-behavior-change` | These helpers render already-available MCP results and protect narrow paths from unnecessary second-round model instability. The behavior is accepted; only ownership may move. | Future removal would require proof that follow-up LLM rendering is equally stable and worth the extra turn, which is outside this branch. | `src/marten_runtime/runtime/direct_rendering.py` if extraction remains pure | runtime-loop MCP render regressions; independent-port trending/latest-commit probes if visible output changes |
| successful-tool follow-up recovery text | `src/marten_runtime/runtime/loop.py::_recover_successful_tool_followup_text` and `_recover_tool_result_text` | `extract-without-behavior-change` | Recovering from a late follow-up failure after a successful tool result is still within the thin-harness boundary. This is distinct from provider-degraded success before any tool result. | No behavior shrink is approved in this branch. Only helper relocation is approved if the recovery seam remains thin and side-effect free. | `src/marten_runtime/runtime/recovery_flow.py` only if extraction stays thin; otherwise keep in `loop.py` | recovery-focused runtime-loop tests; MCP recovery tests; targeted injected follow-up-failure cases |
| request-specific GitHub instruction shaping | `src/marten_runtime/runtime/llm_client.py::_request_specific_instruction` | `retain-now-with-explicit-deviation` | This is the clearest deliberate deviation from a purer capability-only LLM boundary, but current evidence still shows it protects against wrong GitHub tool choice and commit/metadata confusion. It must remain explicit rather than accidental. | Shrink/remove only after capability text + model behavior repeatedly prove correct GitHub tool choice and answer accuracy without request-specific JSON-shaped guidance. | stays temporarily in `llm_client.py`; long-term goal is narrower capability/prompt ownership, not wider runtime policy | direct `tests.test_llm_client`; runtime-loop GitHub query regressions; independent-port latest-commit + metadata probes |
| Feishu card protocol guard in LLM client | `src/marten_runtime/runtime/llm_client.py::_requires_feishu_card_protocol_guard` | `remove-when-replacement-verified` | The behavior is required, but `llm_client.py` should not permanently own Feishu channel protocol knowledge. The ownership itself is the thing approved for removal. | Remove direct `llm_client.py` inference only after channel-owned metadata/instruction injection preserves current Feishu behavior and does not leak Feishu protocol into HTTP traffic. | Feishu channel-owned boundary under `src/marten_runtime/channels/feishu/` | `tests.test_llm_client`, `tests.test_feishu`, gateway/contract regression, and Feishu-focused live verification if visible output changes |
| tool-outcome summary injection | `src/marten_runtime/runtime/loop.py` + `src/marten_runtime/runtime/llm_client.py` | `extract-without-behavior-change` | Tool-outcome summaries are part of the already-approved continuity surface. The current branch may only reorganize pure/near-pure summary composition helpers, not redesign the summary policy. | No behavior shrink is approved in this branch. Revisit only after summary-value evidence changes. | `tool_outcome_flow.py` only if the helper subset is clearly pure/near-pure; otherwise keep mixed ownership | runtime-loop summary regressions; follow-up conversation reusing prior tool outcomes on independent port |

---

## Explicit Accepted Deviations (Approved For This Branch)

The following items are now explicitly recorded as **accepted temporary deviations** rather than implicit historical accidents:

### 1. Runtime context forced route

- accepted because stale remembered context numbers are worse than a narrow host-side route for this class of prompt
- exit condition: repeated live proof that LLM-only selection stays correct across paraphrases and tool-heavy follow-up turns

### 2. Time forced route

- accepted because current-time questions are objectively real-time and should not rely on model memory
- exit condition: repeated live proof that LLM-only selection always chooses builtin `time` instead of answering directly

### 3. Request-specific GitHub instruction shaping

- accepted only as a narrow temporary correctness guard for explicit GitHub commit/metadata requests
- exit condition: capability/prompt-only behavior repeatedly selects the correct GitHub tool without JSON-shaped request hardening

These deviations are also mirrored into `docs/ARCHITECTURE_CHANGELOG.md` because they are no longer just local working notes.

---

## Stage 2 Blueprint Hooks

This matrix intentionally feeds the separate function-level split blueprint.

The approved reading is:

- **route policy stays in `loop.py` for now**
- **pure matcher duplication may converge into shared helper ownership**
- **deterministic render helpers are extraction candidates**
- **recovery helpers are extraction candidates only if they stay thin**
- **Feishu protocol ownership should move toward the Feishu channel boundary**
- **tool-outcome summary helpers may move only if the extracted subset is still obviously not a policy center**

---

## Deferred / Not Approved In This Document

This document does **not** approve any of the following by itself:

- immediate removal of forced routes
- any new generic `intent_detector.py` or classifier subsystem
- provider-auth / provider-transport degraded-success fallback
- broad prompt/capability redesign as part of the same slice as structural extraction
- moving half of `RuntimeLoop` state into helper modules just to make the file shorter
