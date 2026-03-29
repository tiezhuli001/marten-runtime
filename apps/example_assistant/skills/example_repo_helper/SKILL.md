---
skill_id: example_repo_helper
name: Example Repo Helper
description: Prefer repository-aware reasoning for app-local tasks.
enabled: true
always_on: false
agents: [assistant]
channels: [http, cli]
tags: [repo]
---

When working inside the example assistant app:

- prefer repository context over generic advice
- keep changes inside documented runtime contracts
