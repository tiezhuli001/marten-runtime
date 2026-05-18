---
skill_id: long-run-execution
name: Long-Run Execution
description: Use for long running execution tasks where each chunk must be verified before continuing.
enabled: true
agents: [main]
channels: [eval]
tags: [eval, long-running, verification]
---

# Long-Run Execution

For each chunk:

1. Lock target outcome, boundary, and proof.
2. Execute the smallest useful slice.
3. Run the relevant tests or evals.
4. Check documents and implementation for drift.
5. Continue only after the proof result is recorded.

For challenge eval work, verify chunk output with unit tests, scripted eval when available, live eval when required, and report artifacts including Challenge Delta.
