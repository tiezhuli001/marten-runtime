---
skill_id: self_improve
name: Self Improve
description: Use when the runtime needs to synthesize lesson candidates from repeated failures and later recoveries for the default assistant agent.
aliases: ["self improve", "runtime lessons", "lesson synthesis"]
enabled: true
agents: [assistant]
channels: [http, feishu]
tags: [self_improve, lessons, diagnostics]
---

Use the `self_improve` family tool to synthesize candidate lessons from repeated failures and later recoveries.

Operating rules:
- This skill is for internal self-improve turns only. Do not activate it for normal user requests.
- Start by calling `self_improve` with `action=list_evidence`.
- Optionally inspect current active lessons through `self_improve` with `action=list_system_lessons` to avoid duplicates.
- Only derive candidates from repeated failures and later recoveries. Ignore one-off incidents.
- Keep rules short, stable, and implementation-agnostic.
- Save candidates through `self_improve` with `action=save_candidate`.
- Do not edit AGENTS.md.
- Do not rewrite bootstrap files.
