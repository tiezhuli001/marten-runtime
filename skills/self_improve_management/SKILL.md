---
skill_id: self_improve_management
name: Self Improve Management
description: Use when the user wants to inspect self-improve candidates, active runtime lessons, or remove an incorrect candidate.
aliases: ["自我提升", "候选规则", "经验规则", "runtime lessons", "候选 lesson"]
enabled: true
agents: [main]
channels: [http, feishu]
tags: [self_improve, lessons, candidates, diagnostics]
---

Use the `self_improve` family tool to inspect runtime-learned candidate rules and active lessons.

Operating rules:
- This skill is for normal user-facing inspection and cleanup turns.
- Start with `self_improve` + `action=summary` or `action=list_candidates` when the user asks what was learned recently.
- Use `self_improve` + `action=candidate_detail` when one candidate needs more detail.
- Use `self_improve` + `action=list_system_lessons` when the user asks what is currently active in the runtime-managed lessons layer.
- Use `self_improve` + `action=delete_candidate` only when the user clearly asks to remove a candidate rule.
- You may delete lesson candidates.
- You must not delete active lessons.
- Do not mention table names, SQL, or database internals in user-facing replies.
