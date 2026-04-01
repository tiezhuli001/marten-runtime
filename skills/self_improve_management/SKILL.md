---
skill_id: self_improve_management
name: Self Improve Management
description: Use when the user wants to inspect self-improve candidates, active runtime lessons, or remove an incorrect candidate.
aliases: ["自我提升", "候选规则", "经验规则", "runtime lessons", "候选 lesson"]
enabled: true
agents: [assistant]
channels: [http, feishu]
tags: [self_improve, lessons, candidates, diagnostics]
---

Use the self-improve management builtin tools to inspect runtime-learned candidate rules and active lessons.

Operating rules:
- This skill is for normal user-facing inspection and cleanup turns.
- Start with `get_self_improve_summary` or `list_lesson_candidates` when the user asks what was learned recently.
- Use `get_lesson_candidate_detail` when one candidate needs more detail.
- Use `list_system_lessons` when the user asks what is currently active in the runtime-managed lessons layer.
- Use `delete_lesson_candidate` only when the user clearly asks to remove a candidate rule.
- You may delete lesson candidates.
- You must not delete active lessons.
- Do not mention table names, SQL, or database internals in user-facing replies.
