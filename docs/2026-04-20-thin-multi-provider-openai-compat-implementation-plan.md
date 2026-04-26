# Thin Multi-Provider OpenAI-Compat Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add a thin multi-provider layer for `openai`, `minimax`, and `kimi` using a shared `openai_compat` adapter, explicit provider registry, and profile-level failover without widening the harness boundary.

**Architecture:** split non-secret provider connection metadata into `config/providers.toml`, narrow `config/models.toml` to `profile -> provider_ref -> model`, and replace the single-provider factory with `provider registry + openai_compat adapter + profile-level failover`. Keep provider choice host-side and keep tool choice LLM-side. Failover is allowed only on provider/transport/empty-output failures and only at `llm_first` or `llm_second` stage boundaries.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, unittest

---

## Source Documents

- Design source of truth:
  - `docs/2026-04-20-thin-multi-provider-openai-compat-design.md`
- Current implementation entry points:
  - `src/marten_runtime/config/models_loader.py`
  - `src/marten_runtime/runtime/llm_client.py`
  - `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
  - `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
  - `src/marten_runtime/runtime/loop.py`

## Locked Invariants

- keep the runtime center at `channel -> binding -> agent -> runtime loop -> llm client -> builtin/MCP/skill -> llm client -> channel`
- keep secrets in `.env`; never move secret values into TOML
- current phase supports only `openai`, `minimax`, `kimi`
- current phase introduces exactly one adapter family: `openai_compat`
- delete replaced single-provider code as soon as the new path is verified; do not keep legacy compatibility layers
- do not introduce LiteLLM, plugin manifests, provider hook frameworks, or semantic provider routing
- host owns provider config parsing, transport selection, failover, and diagnostics
- LLM owns tool choice, tool order, and whether any tool should be called
- do not reintroduce endpoint-guessing fallback logic inside the adapter
- provider endpoint capability must come from explicit config flags
- failover must never replay completed tool side effects
- `llm_second` failover may only regenerate the final answer from existing tool results

## Delivery Order

The work must be implemented in five strict chunks:

1. provider config split and loader
2. model profile narrowing and provider registry
3. `openai_compat` adapter extraction and factory cutover
4. profile-level failover with stage-safe boundaries
5. diagnostics, migration cleanup, and live verification

Do not start a later chunk until the current chunk passes its chunk verification and still matches the design doc.

## Chunk 1: Provider Config Split

### Task 1: Add provider config models and loader

**Files:**
- Create: `src/marten_runtime/config/providers_loader.py`
- Modify: `tests/test_models.py`
- Create: `tests/test_providers_loader.py`
- Create: `config/providers.example.toml`

**Constraints:**
- `providers_loader.py` must only parse non-secret provider metadata
- it must not read actual env secret values
- it must not construct clients
- it must reject missing `adapter`, missing `base_url`, and missing `api_key_env`
- it must require explicit endpoint capability flags for the current phase

- [ ] **Step 1: Write failing loader tests for the new config surface**

Add tests that lock:

- valid `providers.toml` loads three providers
- missing `adapter` fails
- missing `api_key_env` fails
- missing `base_url` fails
- missing `supports_responses_api` fails
- missing `supports_chat_completions` fails
- unknown adapter value fails

- [ ] **Step 2: Run the focused failing tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_providers_loader
```

Expected:

- the new test module fails because the loader does not exist yet

- [ ] **Step 3: Implement `ProviderConfig` and `ProvidersConfig`**

Required fields:

- `adapter`
- `base_url`
- `api_key_env`
- `extra_headers`
- `header_env_map`
- `supports_responses_api`
- `supports_chat_completions`

Required behavior:

- `extra_headers` accepts only fixed non-secret values
- `header_env_map` stores only `header_name -> env_var_name`
- no field in the loader reads env values

- [ ] **Step 4: Add `config/providers.example.toml`**

It must include sample entries for:

- `openai`
- `minimax`
- `kimi`

Each sample must declare explicit capability flags.

- [ ] **Step 5: Run the focused loader tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_providers_loader tests.test_models
```

Expected:

- provider loader tests pass
- existing model loader tests still pass or fail only on assertions that need the next task

**Done means:**

- provider config can be loaded independently from model profiles
- endpoint capability flags are explicit
- the loader does not read secrets or construct clients

### Task 2: Add runtime bootstrap support for provider config loading

**Files:**
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `tests/test_http_runtime_diagnostics.py`

**Constraints:**
- runtime bootstrap may load provider config into state
- it must not yet change client factory behavior in this chunk
- diagnostics must not expose secret values

- [ ] **Step 1: Add `providers_config` to runtime bootstrap state**

Load `config/providers.toml` if present and fall back to the example/default path shape.

- [ ] **Step 2: Add basic provider metadata to runtime diagnostics**

Add only:

- `provider_count`
- `providers[].provider_ref`
- `providers[].adapter`
- `providers[].base_url`
- `providers[].api_key_env`

- [ ] **Step 3: Run the diagnostics tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_runtime_diagnostics
```

Expected:

- diagnostics tests pass
- no secret values appear in runtime diagnostics

**Done means:**

- runtime can see provider config
- operators can inspect configured providers without seeing secrets

## Chunk 2: Narrow Models To Profile Semantics

### Task 3: Refine `ModelProfile` to use `provider_ref`

**Files:**
- Modify: `src/marten_runtime/config/models_loader.py`
- Modify: `config/models.toml`
- Modify: `config/models.example.toml`
- Modify: `tests/test_models.py`

**Constraints:**
- remove `base_url` and `api_key_env` from `ModelProfile`
- add `provider_ref`
- add `fallback_profiles`
- keep existing context window, tokenizer, and usage-related fields
- `models.toml` must stop being a provider connection surface
- do not preserve the old profile fields as compatibility aliases

- [ ] **Step 1: Write failing tests for the narrowed profile shape**

Lock:

- `provider_ref` is required
- `fallback_profiles` defaults to empty list
- old `base_url` and `api_key_env` fields are no longer the source of truth
- default example profiles reference `openai`, `minimax`, `kimi`

- [ ] **Step 2: Update the config examples**

Make both `models.toml` and `models.example.toml` reference:

- `openai_gpt5`
- `kimi_k2`
- `minimax_m25`

- [ ] **Step 3: Update the loader implementation**

Required behavior:

- profile loading stays deterministic
- missing `provider_ref` fails
- `fallback_profiles` remains a plain ordered list of profile names

- [ ] **Step 4: Run model-loader tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_models
```

Expected:

- all model-loader tests pass with the new profile structure

**Done means:**

- model profiles describe model choice only
- provider connection details have moved out of `models.toml`
- old profile-side provider connection fields are deleted from the main implementation

### Task 4: Add provider registry

**Files:**
- Create: `src/marten_runtime/runtime/provider_registry.py`
- Create: `tests/test_provider_registry.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`

**Constraints:**
- registry resolves providers; it does not issue requests
- registry resolves fallback chains; it does not execute failover
- registry must validate referenced provider names

- [ ] **Step 1: Write failing registry tests**

Lock:

- primary provider resolution by `provider_ref`
- ordered fallback profile resolution
- unknown provider reference fails
- unknown fallback profile fails
- duplicate fallback entries are rejected or normalized consistently

- [ ] **Step 2: Implement `resolve_provider()` and `resolve_fallback_profiles()`**

Required behavior:

- preserve fallback order as declared
- return provider metadata only
- do not read env secrets here

- [ ] **Step 3: Wire registry availability into runtime bootstrap state**

Expose the registry or its helper functions where the factory can use them later.

- [ ] **Step 4: Run focused registry tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_provider_registry tests.test_models
```

Expected:

- registry tests pass
- model tests remain green

**Done means:**

- any profile can resolve to an explicit primary provider and an explicit ordered fallback chain

## Chunk 3: Extract The OpenAI-Compatible Adapter

### Task 5: Move the current OpenAI transport into `openai_compat`

**Files:**
- Create: `src/marten_runtime/runtime/llm_adapters/openai_compat.py`
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Modify: `tests/test_llm_transport.py`
- Modify: `tests/test_runtime_usage.py`

**Constraints:**
- extract behavior; do not widen behavior
- preserve existing `/responses` routing rules for GPT-5 family
- preserve usage normalization, tool schema mapping, diagnostics, and retry behavior
- adapter selection must use explicit provider capability flags
- do not add endpoint-guessing fallback logic
- after extraction, remove the obsolete single-provider transport implementation instead of keeping both versions

- [ ] **Step 1: Write or adjust failing tests for the new adapter boundary**

Lock:

- GPT-5 family uses `/responses` only when the provider supports it
- chat models use `/chat/completions` only when the provider supports it
- unsupported endpoint combination raises a clear configuration error
- tool schema conversion remains unchanged
- usage extraction remains unchanged

- [ ] **Step 2: Extract `OpenAICompatLLMClient`**

Required behavior:

- constructor accepts provider metadata from registry/loader
- `provider_name` reflects provider ref, not a hardcoded brand string
- request headers include:
  - bearer auth from `api_key_env`
  - fixed `extra_headers`
  - env-derived headers from `header_env_map`

- [ ] **Step 3: Keep a thin compatibility seam in `llm_client.py`**

`llm_client.py` should become a construction layer, not the long-term home of provider-family transport code.

- [ ] **Step 4: Delete the replaced single-provider transport code**

Required behavior:

- remove the old embedded provider-family implementation that has been superseded by `runtime/llm_adapters/openai_compat.py`
- keep only the construction surface that the rest of the runtime imports
- do not leave dead helper branches behind

- [ ] **Step 5: Run focused transport and usage tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_transport tests.test_runtime_usage
```

Expected:

- transport tests pass
- usage tests pass

**Done means:**

- `openai`, `minimax`, and `kimi` can all be served by the same adapter family
- no endpoint guessing has been introduced
- the replaced single-provider transport code has been removed

### Task 6: Cut over the factory to registry + adapter

**Files:**
- Modify: `src/marten_runtime/runtime/llm_client.py`
- Modify: `src/marten_runtime/interfaces/http/bootstrap_runtime.py`
- Modify: `tests/test_llm_transport.py`
- Modify: `tests/contracts/test_runtime_contracts.py`

**Constraints:**
- factory chooses adapter by `provider_ref -> adapter`
- factory may read env values for auth at construction time
- factory must not contain per-message provider routing logic
- after cutover, remove the obsolete hardcoded `provider == "openai"` branch entirely

- [ ] **Step 1: Write failing factory tests**

Lock:

- `openai_gpt5` builds an `openai_compat` client for `openai`
- `kimi_k2` builds an `openai_compat` client for `kimi`
- `minimax_m25` builds an `openai_compat` client for `minimax`
- unsupported adapter fails clearly
- missing API key env fails clearly

- [ ] **Step 2: Update `build_llm_client()`**

Required behavior:

- resolve profile
- resolve provider
- construct adapter-specific client
- keep existing default-client caching behavior in bootstrap factory

- [ ] **Step 3: Run focused factory and contract tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_transport tests.contracts.test_runtime_contracts
```

Expected:

- factory tests pass
- runtime contract tests still pass

**Done means:**

- the runtime no longer has a single hardcoded provider family at the factory boundary
- no dead hardcoded single-provider branch remains in the factory

## Chunk 4: Add Stage-Safe Profile-Level Failover

### Task 7: Add failover policy and execution helpers

**Files:**
- Create: `src/marten_runtime/runtime/llm_failover.py`
- Create: `tests/test_llm_failover.py`
- Modify: `src/marten_runtime/runtime/provider_retry.py`

**Constraints:**
- failover is based only on normalized provider failure conditions and `EMPTY_FINAL_RESPONSE`
- failover is not based on user message content
- failover must preserve declared fallback order
- failover must distinguish `llm_first` and `llm_second`

- [ ] **Step 1: Write failing failover policy tests**

Lock:

- 429 triggers fallback
- 529 triggers fallback
- timeout triggers fallback
- transport error triggers fallback
- `PROVIDER_RESPONSE_INVALID` triggers fallback
- `EMPTY_FINAL_RESPONSE` triggers fallback
- auth/config errors do not trigger fallback

- [ ] **Step 2: Add helper APIs for failover decisions**

Required surface:

- `should_failover(error_code, stage)`
- `next_fallback_profile(current_profile, fallback_profiles, attempted_profiles)`

- [ ] **Step 3: Run focused failover policy tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_failover
```

Expected:

- failover policy tests pass

**Done means:**

- the runtime has a narrow, explicit failover policy with no semantic routing behavior

### Task 8: Integrate failover into `RuntimeLoop` without replaying tool side effects

**Files:**
- Modify: `src/marten_runtime/runtime/loop.py`
- Modify: `src/marten_runtime/runtime/history.py`
- Modify: `tests/runtime_loop/test_tool_followup_and_recovery.py`
- Modify: `tests/runtime_loop/test_context_status_and_usage.py`
- Create: `tests/runtime_loop/test_provider_failover.py`

**Constraints:**
- `llm_first` failover may re-run the first LLM request with a fallback profile
- `llm_second` failover may only re-run final answer generation using the existing tool result
- tool execution must happen at most once per completed tool step
- failover must be visible in run history

- [ ] **Step 1: Write failing runtime-loop tests for stage-safe failover**

Required scenarios:

- first-turn provider error falls back before any tool call
- first-turn empty output falls back before any tool call
- second-turn provider error after tool success reuses the existing tool result
- second-turn empty output after tool success reuses the existing tool result
- tool call count remains exactly one in the second-turn failover path

- [ ] **Step 2: Add attempt tracking in run history**

Record:

- attempted profiles
- attempted providers
- failover trigger
- final provider ref
- stage at which failover occurred

- [ ] **Step 3: Integrate the failover loop into `RuntimeLoop`**

Required behavior:

- preserve existing normal success path
- preserve existing tool-followup path
- failover only on allowed errors
- never re-run an already completed tool action because of provider switching

- [ ] **Step 4: Run focused runtime-loop failover tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.runtime_loop.test_provider_failover tests.runtime_loop.test_tool_followup_and_recovery tests.runtime_loop.test_context_status_and_usage
```

Expected:

- failover loop tests pass
- no regression in tool-followup behavior

**Done means:**

- the runtime can recover from provider failures without violating tool-side-effect boundaries

## Chunk 5: Diagnostics, Migration, And End-To-End Proof

### Task 9: Expand diagnostics for provider visibility

**Files:**
- Modify: `src/marten_runtime/interfaces/http/runtime_diagnostics.py`
- Modify: `src/marten_runtime/interfaces/http/app.py`
- Modify: `tests/test_gateway.py`
- Modify: `tests/test_http_runtime_diagnostics.py`

**Constraints:**
- diagnostics must stay secret-safe
- diagnostics must let operators distinguish:
  - config errors
  - provider busy/rate limited
  - provider empty output
  - fallback success

- [ ] **Step 1: Add failing diagnostics tests**

Lock:

- `/diagnostics/runtime` shows provider registry metadata
- `/diagnostics/run/{run_id}` shows attempted profiles/providers and final provider
- failover trigger is visible after a fallback path

- [ ] **Step 2: Implement diagnostics serialization changes**

Required fields:

- runtime:
  - `provider_count`
  - `providers`
  - `default_profile`
- run:
  - `provider_ref`
  - `attempted_profiles`
  - `attempted_providers`
  - `failover_trigger`
  - `final_provider_ref`
  - `failover_stage`

- [ ] **Step 3: Run diagnostics and gateway tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_http_runtime_diagnostics tests.test_gateway
```

Expected:

- diagnostics tests pass
- gateway tests still pass

**Done means:**

- operators can tell what provider path actually happened on any run

### Task 10: Complete config migration and compatibility cleanup

**Files:**
- Modify: `config/models.toml`
- Modify: `config/models.example.toml`
- Create: `config/providers.toml`
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `tests/test_acceptance.py`

**Constraints:**
- new config files become the canonical shape
- migration must stay minimal
- do not add compatibility shims that keep both worlds alive indefinitely
- after migration, remove the replaced old config shape from the main code path

- [ ] **Step 1: Add or update real `config/providers.toml`**

It must define:

- `openai`
- `minimax`
- `kimi`

- [ ] **Step 2: Update docs for the new config split**

Document:

- secrets stay in `.env`
- provider metadata goes to `providers.toml`
- model choice stays in `models.toml`

- [ ] **Step 3: Update acceptance coverage for the new config shape**

Add or adjust tests so acceptance builds a runtime with the split config layout.

- [ ] **Step 4: Delete obsolete config-shape compatibility code**

Required behavior:

- remove main-path support for profile-side `base_url` and `api_key_env`
- remove any temporary migration helpers once the repo config files and tests are on the new shape

- [ ] **Step 5: Run focused acceptance tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_acceptance
```

Expected:

- acceptance tests pass under the split config model

**Done means:**

- the repository’s canonical configuration surface matches the design
- the old config shape is no longer kept alive in the main implementation

### Task 11: Run full regression and live verification

**Files:**
- Modify: `STATUS.md`

**Constraints:**
- do not claim completion without both regression and live proof
- live verification must use the exact provider/profile surfaces implemented above

- [ ] **Step 1: Run the full targeted regression pack**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_providers_loader \
  tests.test_models \
  tests.test_provider_registry \
  tests.test_llm_transport \
  tests.test_runtime_usage \
  tests.test_llm_failover \
  tests.runtime_loop.test_provider_failover \
  tests.runtime_loop.test_tool_followup_and_recovery \
  tests.runtime_loop.test_context_status_and_usage \
  tests.test_http_runtime_diagnostics \
  tests.test_gateway \
  tests.test_acceptance \
  tests.contracts.test_runtime_contracts
```

Expected:

- all listed tests pass

- [ ] **Step 2: Run config-level smoke checks**

Check:

- runtime boots with `openai_gpt5`
- runtime boots with fallback chain configured
- runtime diagnostics show provider registry

- [ ] **Step 3: Run live provider smoke**

Required live checks:

- one plain chat on `openai_gpt5`
- one plain chat on `kimi_k2`
- one plain chat on `minimax_m25`
- one forced fallback path where the primary profile is intentionally unavailable or returns empty output

Required evidence:

- run diagnostics for each smoke
- attempted profiles/providers visible when fallback occurs

- [ ] **Step 4: Run Feishu-shaped end-to-end verification**

Required prompts:

- plain conversation
- explicit runtime query
- explicit tool request

Validation targets:

- no provider secrets in any card or diagnostics
- provider failure messages remain user-readable
- successful fallback still produces stable final output

- [ ] **Step 5: Update `STATUS.md` with final implementation reality**

Write:

- what shipped
- what failed or was deferred
- exact verification commands and outcomes

**Done means:**

- the implementation is verified by both regression and live runtime evidence

## Hard Rejection Criteria

Stop and rework if any implementation introduces one of these:

- endpoint-guessing fallback inside the adapter
- provider selection by user-message semantics
- repeated tool execution during provider failover
- secret values stored in TOML
- diagnostics exposing secret values
- a second adapter family in the current phase
- LiteLLM or plugin-platform expansion
- replaced single-provider code kept around as dead compatibility baggage

## Final Plan-vs-Design Checklist

Before implementation starts, confirm the plan still matches `docs/2026-04-20-thin-multi-provider-openai-compat-design.md` on these points:

- provider set is exactly `openai`, `minimax`, `kimi`
- adapter set is exactly `openai_compat`
- secrets stay in `.env`
- `providers.toml` is non-secret metadata only
- `models.toml` is narrowed to profile/model/provider reference data
- failover is profile-level only
- failover is allowed only for provider/transport/empty-output failures
- `llm_second` failover reuses existing tool results
- host never decides tool choice
- replaced old code paths are deleted rather than preserved

Plan execution must pause if any code change proposal violates one of these checks.
