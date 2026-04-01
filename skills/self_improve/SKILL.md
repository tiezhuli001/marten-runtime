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

Use the self-improve builtin tools to synthesize candidate lessons from repeated failures and later recoveries.

Operating rules:
- This skill is for internal self-improve turns only. Do not activate it for normal user requests.
- Start by calling `list_self_improve_evidence`.
- Optionally inspect current active lessons through `list_system_lessons` to avoid duplicates.
- Only derive candidates from repeated failures and later recoveries. Ignore one-off incidents.
- Keep rules short, stable, and implementation-agnostic.
- Save candidates through `save_lesson_candidate`.
- Do not edit AGENTS.md.
- Do not rewrite bootstrap files.
