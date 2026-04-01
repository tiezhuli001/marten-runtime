# Architecture Changelog

This file is the append-only architecture evolution log for `marten-runtime`.

Use it to answer:

- what architecture changed
- why the change happened
- which ADR or design doc is now authoritative
- what verification proved the new baseline

Do not use this file for day-to-day task tracking. Local continuity belongs in a local-only `STATUS.md`.

## Source Of Truth Rules

- Stable architectural decisions live in `docs/architecture/adr/`.
- Time-ordered architecture evolution is recorded here.
- Detailed execution history may still exist in local `STATUS.md`, but `STATUS.md` is not a repository source of truth.
- If a change updates the runtime boundary, default capability surface, or long-lived subsystem role, add an entry here.

## Entries

### 2026-04-01: Feishu Live Validation Confirmed The Current Baseline And Exposed Two Follow-Up Workstreams

- Change:
  - revalidated one real Feishu conversation with three back-to-back operator turns on the same chat
  - confirmed the chain still honors same-conversation FIFO under live websocket ingress
  - confirmed the `time` tool now resolves natural-language current-time requests to `Asia/Shanghai` instead of falling back to `UTC`
- Why:
  - this round was intended to verify the post-fix Feishu chain against the real chat surface rather than only local HTTP smoke
  - the live run also clarified which remaining issues are true follow-up work versus baseline regressions
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Verification:
  - real Feishu chat `oc_5091efbdd295f49cad9bdeed9d92b7ae` produced three successful runs on one shared `session_id = sess_b21c9ef2`
  - `run_1d429ad0`:
    - used `time` with empty payload
    - `tool_result.timezone = Asia/Shanghai`
    - `llm_request_count = 2`
  - `run_61c2b511`:
    - used `automation(action=list)`
    - returned two enabled automations
    - `llm_request_count = 2`
  - `run_00f7c1c9`:
    - used `self_improve(action=list_candidates)`
    - returned zero candidates
    - `llm_request_count = 2`
  - `/diagnostics/runtime` after the run showed:
    - Feishu websocket `connected = true`
    - `dead_letter.count = 0`
    - `duplicate_total = 0`
    - `max_queue_depth = 2`
- Follow-up backlog:
  - performance investigation:
    - break down per-run first-LLM, tool execution, second-LLM, and outbound delivery latency so the current live slowness can be attributed precisely instead of guessing at MCP or skill disclosure
  - unified message pipeline:
    - harden Feishu inbound normalization, websocket event handling, and outbound card rendering as one coherent message pipeline
    - current hotspots are [inbound.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/inbound.py), [service.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/service.py), and [delivery.py](/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/channels/feishu/delivery.py)
    - goals are fewer intermittent parse failures and a more intentional outbound card presentation

### 2026-04-01: Fresh Live Validation Reconfirmed The Baseline On `127.0.0.1:8074`

- Change:
  - re-ran full repository verification plus a fresh live runtime on `127.0.0.1:8074`
  - revalidated same-conversation FIFO under `4` overlapping HTTP turns on one shared conversation
  - revalidated explicit `time` and GitHub MCP usage with tool-forcing prompts against the live runtime
  - revalidated Feishu websocket stability and manual Feishu delivery through `codex_live_validation_temp`
- Why:
  - the cleanup and docs-source-of-truth pass needed a fresh post-cleanup proof, not only the earlier `8072` evidence
  - the main chain must keep proving that queue serialism, MCP latency, and Feishu delivery still hold after repository hygiene changes
- Source of truth:
  - [ADR 0001: Thin Harness Boundary](./architecture/adr/0001-thin-harness-boundary.md)
  - [ADR 0002: Progressive Disclosure Default Surface](./architecture/adr/0002-progressive-disclosure-default-surface.md)
  - [ADR 0003: Self-Improve Is Runtime Learning, Not Architecture Memory](./architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md)
- Verification:
  - full regression:
    - `PYTHONPATH=src python -m unittest -v`
    - pass, `233` tests green
  - live runtime bootstrap:
    - `GET /healthz` returned `{"status":"ok"}`
    - `GET /diagnostics/runtime` showed `llm_model = MiniMax-M2.5`, `tool_count = 5`, `mcp_server_count = 2`, GitHub MCP `state = discovered`, and Feishu websocket `connected = true`
  - same-conversation FIFO:
    - `4` concurrent requests on `conversation_id = live-fifo-timeforced-8074` all succeeded on one shared `session_id = sess_408a41c9`
    - elapsed times were `6.711s`, `13.874s`, `20.489s`, and `30.280s`
    - `/diagnostics/queue` recorded `max_queue_depth = 4`
    - all `4` completed runs used the `time` tool with `timezone = Asia/Shanghai`
  - MCP latency:
    - `3/3` explicit GitHub prompts succeeded with final text `login = tiezhuli001`, `public_repos = 8`
    - elapsed times were `20.635s`, `13.994s`, and `12.528s`
    - completed runs `run_d5071887`, `run_b58cadd1`, and `run_abd3c548` all executed `mcp -> detail(github) -> call(get_me)`
  - Feishu stability and delivery:
    - three runtime samples over roughly `20s` kept websocket `running = true`, `connected = true`, `reconnect_attempts = 0`
    - `dead_letter.count` stayed `0`
    - manual trigger `POST /automations/codex_live_validation_temp/trigger` returned final text `实时链路验证通过。`
    - post-trigger runtime diagnostics showed `delivery_sessions.closed_count = 1`, websocket still `connected = true`, and `dead_letter.count = 0`
- Notes:
  - a natural-language FIFO probe using `现在几点？` also stayed serial and reused one session, but `3/4` runs did not call the `time` tool and answered with stale `2025-07-10` timestamps
  - this is a live prompt-to-tool compliance drift in the model path, not a queue failure; the tool-forced probe above is the authoritative queue/tool baseline for this run

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
  - `PYTHONPATH=src python -m unittest -v`
    - pass, `234` tests green
  - fresh live runtime on `127.0.0.1:8074`:
    - `GET /healthz` returned `{"status":"ok"}`
    - `GET /diagnostics/runtime` showed Feishu websocket `connected = true`
    - three plain natural-language probes using `现在几点？请直接回答。` all succeeded
    - completed runs `run_2644cb88`, `run_3d61178c`, and `run_994f5305` all executed the `time` tool instead of answering from memory

### 2026-04-01: Repository Hygiene Boundaries Were Tightened

- Change:
  - added `apps/example_assistant/SYSTEM_LESSONS.md` to `.gitignore`
  - formalized `SYSTEM_LESSONS.md` as a runtime-managed artifact instead of a repository baseline file
  - introduced `docs/archive/` and moved completed one-off audits and the completed refinement plan out of the primary docs path
  - added a new active follow-up plan at `docs/plans/2026-04-01-bootstrap-assembly-hygiene-plan.md`
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
  - docs and README entry paths now point to active docs versus archive docs separately

### 2026-03-31: Harder Live Validation Reconfirmed The Current Baseline

- Change:
  - re-ran live validation against a fresh local runtime on `127.0.0.1:8072`
  - pushed same-conversation FIFO overlap harder with `4` concurrent HTTP turns on one `conversation_id`
  - sampled explicit GitHub MCP usage `3` times with a prompt that forced `get_me`
  - sampled Feishu websocket runtime stability over `30` seconds and re-validated delivery through manual automation trigger
- Why:
  - the new ADR + changelog source of truth needed fresh run-time evidence, not only historical test status
  - this repo must keep proving that the thin-harness baseline still holds under overlap and real external capability usage
- Verification:
  - FIFO pressure:
    - all `4` overlapping turns completed successfully
    - all `4` turns reused the same `session_id`
    - `max_queue_depth = 4`
    - `max_observed_queued_items_total = 3`
  - MCP latency:
    - `3/3` runs succeeded
    - elapsed time was `9.528s`, `12.459s`, and `9.459s`
    - all runs used the model-visible `mcp` family tool and successfully called GitHub `get_me`
  - Feishu stability:
    - websocket stayed `running = true`, `connected = true`, `reconnect_attempts = 0` across `3` samples
    - `dead_letter_count` stayed `0`
    - manual trigger `POST /automations/codex_live_validation_temp/trigger` returned final text `实时链路验证通过。`
    - post-trigger diagnostics still showed `connected = true`, `dead_letter_count = 0`, and `closed_delivery_sessions = 1`

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
  - [Conversation Lanes And Provider Resilience Design](./2026-03-30-conversation-lanes-provider-resilience-design.md)
  - [Self-Improve Design](./2026-03-30-self-improve-design.md)
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
  - [Conversation Lanes And Provider Resilience Design](./2026-03-30-conversation-lanes-provider-resilience-design.md)
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
  - [Self-Improve Design](./2026-03-30-self-improve-design.md)
- Verification:
  - self-improve tests and live runtime summary paths remain green
