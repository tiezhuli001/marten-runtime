---
skill_id: automation_management
name: Automation Management
description: Use when the user wants to view or manage existing 自动任务、定时任务、recurring jobs, or scheduled digests, including query, modify, pause, resume, or delete requests.
aliases: ["自动任务管理", "定时任务管理", "自动任务", "定时任务", "automation CRUD", "任务管理"]
enabled: true
agents: [assistant]
channels: [http, feishu]
tags: [automation, recurring, schedule, tasks, management]
---

Use the builtin automation tools to manage recurring jobs already stored in the runtime.

Operating rules:
- Treat automation management as local control-plane work. Prefer builtin tools over MCP.
- Read before mutating. Usually start with `list_automations`.
- Do not require the user to provide an internal `automation_id` up front.
- If more than one task could match, ask one short clarification question after listing candidates.
- Use `include_disabled=true` when the user may be referring to a paused task.
- Do not run the task content itself. When the user is managing an existing task, finish the CRUD action and stop there.
- Keep replies concise and outcome-oriented.

Suggested tool patterns:
- Query current tasks: call `list_automations`
- Modify time, timezone, name, delivery target, or skill:
  - call `list_automations`
  - identify the intended task
  - call `update_automation`
- Pause or resume:
  - call `list_automations`
  - call `pause_automation` or `resume_automation`
- Delete:
  - call `list_automations`
  - call `delete_automation` only when the user clearly asked to remove the task
