---
skill_id: example_time
name: Example Time
description: Tell the agent to prefer real time tools.
enabled: true
always_on: false
agents: [assistant]
channels: [http]
tags: [time]
---

When the user asks for current time or timezone:

- prefer a real tool over hallucinated text
- mention timezone when available
