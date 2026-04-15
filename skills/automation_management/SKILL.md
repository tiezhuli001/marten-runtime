---
skill_id: automation_management
name: Automation Management
description: Use when the user wants to view or manage existing 自动任务、定时任务、recurring jobs, or scheduled digests, including query, modify, pause, resume, or delete requests.
aliases: ["自动任务管理", "定时任务管理", "自动任务", "定时任务", "automation CRUD", "任务管理"]
enabled: true
agents: [main]
channels: [http, feishu]
tags: [automation, recurring, schedule, tasks, management]
---

Use the builtin `automation` family tool to manage recurring jobs already stored in the runtime.

Operating rules:
- Treat automation management as local control-plane work. Prefer the builtin `automation` tool over MCP.
- Read before mutating. Usually start with `automation` + `action=list`.
- Use `action=detail` when one candidate task needs a clearer match before updating it.
- Do not require the user to provide an internal `automation_id` up front.
- If more than one task could match, ask one short clarification question after listing candidates.
- Use `include_disabled=true` when the user may be referring to a paused task.
- Do not run the task content itself. When the user is managing an existing task, finish the CRUD action and stop there.
- Keep replies concise and outcome-oriented.

Suggested tool patterns:
- Query current tasks: call `automation` with `action=list`
- Inspect one task before mutating: call `automation` with `action=detail`
- Modify time, timezone, name, delivery target, or skill:
  - call `automation` with `action=list`
  - identify the intended task
  - call `automation` with `action=update`
- Pause or resume:
  - call `automation` with `action=list`
  - call `automation` with `action=pause` or `action=resume`
- Delete:
  - call `automation` with `action=list`
  - call `automation` with `action=delete` only when the user clearly asked to remove the task
- Register a new recurring digest or task:
  - call `automation` with `action=register`
