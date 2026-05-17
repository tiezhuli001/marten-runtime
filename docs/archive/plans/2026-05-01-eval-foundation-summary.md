# 2026-05-01 Eval Foundation Summary

This note replaces the two long execution plans from 2026-04-30 and 2026-05-01. The implementation details now live in code, tests, suites, reports, and the active architecture docs.

## Scope

- `main_chain_core` verifies the default runtime spine through the HTTP app and diagnostics.
- `memory_long_horizon` verifies continuity behavior through the same eval runner.
- `subagent_task_progress` verifies parent / child task progress through the same eval runner.
- `main_chain_mcp` is a live-only suite for real provider, real MCP server, and real GitHub results.
- `subagent_external_mcp_completion` is a live-only suite for child-agent completion through real MCP results.
- `main_chain_subagent` stays dependency-gated where external services are required.

## Durable Sources

- `docs/2026-04-30-main-chain-eval-foundation-design.md`
- `docs/ARCHITECTURE_EVOLUTION.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/README.md`
- `scripts/run_eval.py`
- `src/marten_runtime/evals/`
- `evals/suites/`
- `evals/cases/`
- `tests/evals/`

## Runtime Boundary

The eval subsystem is an offline harness layer. It drives the real HTTP/runtime/diagnostics path and compares observable outputs. It does not add host-side message intent routing to the runtime path.

## Verification Entrypoints

```bash
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite main_chain_core --mode scripted --profile openai_gpt_5_4 --baseline latest_passed
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite memory_long_horizon --mode scripted --profile openai_gpt_5_4 --baseline latest_passed
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite subagent_task_progress --mode scripted --profile openai_gpt_5_4 --baseline latest_passed
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite main_chain_mcp --mode live --profile openai_gpt_5_4 --baseline latest_passed
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite subagent_external_mcp_completion --mode live --profile openai_gpt_5_4 --baseline latest_passed
```

## Removed Historical Files

- `docs/archive/plans/2026-04-30-main-chain-eval-foundation-execution-plan.md`
- `docs/archive/plans/2026-05-01-memory-subagent-eval-execution-plan.md`

Those files were implementation handoff plans. Their lasting contracts are now represented by the durable sources above.
