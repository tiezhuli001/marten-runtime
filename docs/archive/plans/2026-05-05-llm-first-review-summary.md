# 2026-05-05 LLM-First Review Summary

## Scope

This summary preserves the durable outcome of a 23-round review sequence on the eval-foundation branch. The review converged repeated findings into root-cause groups and verified the surviving runtime contracts.

## Root-Cause Groups

Seven groups explained the repeated findings:

1. durable memory intent and mutation grounding
2. live time, date, and weekday grounding
3. live runtime-context grounding
4. session and subagent success grounding
5. tool-followup and recovery evidence coverage
6. eval run metadata and artifact parity
7. stricter grounding aligned with updated test expectations

The repeated review loop came from nearby language and contract variants surfacing around the same ownership boundaries. The durable correction moved enforcement from phrase-level patches toward structured claims backed by current-turn tool evidence.

## Surviving Contracts

- Live time and runtime-state claims require current-turn evidence.
- Memory mutations require structured intent and successful memory-tool evidence.
- Session and subagent success claims require matching tool results.
- Exact tool-result summaries take precedence before broader evidence-token checks.
- Eval metadata, artifact paths, dirty-state capture, and run identity remain internally consistent.
- Tests assert grounded outputs produced by the current contracts.

## Additional Test-Lifecycle Fix

The review also found a test-app cleanup gap. Shared test support now finalizes background workers, subagent services, and temporary directories so SQLite and worker lifecycle noise cannot leak between tests.

## Verification Retained

- focused two-case runtime follow-up verification: pass
- hotspot regression pack: `184` tests passed
- open-ended adversarial probes: `4/4` passed
- full test suite, compile, and diff checks: pass

## Current Successors

- LLM-first routing boundary: `docs/architecture/adr/0004-llm-first-tool-routing-boundary.md`
- Current runtime path: `.cs/spec/runtime-main-chain.md`
- Current continuity and evidence behavior: `.cs/spec/continuity-and-capabilities.md`
- Architecture timeline: `docs/ARCHITECTURE_CHANGELOG.md`
- Runtime recovery and owner tests: `src/marten_runtime/runtime/` and `tests/`
