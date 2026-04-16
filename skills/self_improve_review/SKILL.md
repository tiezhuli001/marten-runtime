---
skill_id: self_improve_review
name: Self Improve Review
description: Use only inside internal review subagents to classify bounded self-improve evidence into lesson proposals, skill proposals, or nothing worth saving.
aliases: ["review subagent", "self improve review", "skill candidate review"]
enabled: true
agents: [main]
channels: [http, feishu]
tags: [self_improve, review, skill_candidate]
---

Use this skill only inside runtime-owned self-improve review children.

Operating rules:
- This skill is classification-only. It is not the source of truth for persistence, notification, or promotion.
- Read the bounded review payload and return structured JSON only.
- Propose a lesson only when the evidence is short, stable, reusable, and specific.
- Propose a skill candidate only when the evidence shows a reusable multi-step workflow.
- Use `nothing_to_save_reason` when the evidence is weak, one-off, or already covered.
- Do not edit AGENTS.md.
- Do not rewrite bootstrap files.
- Do not directly notify the user.
- Do not directly promote official skills.
- Do not open nested subagents.
