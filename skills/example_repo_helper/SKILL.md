---
skill_id: example_repo_helper
name: Example Repo Helper
description: Prefer repository-aware reasoning for app-local tasks.
enabled: true
always_on: false
agents: [main]
channels: [http, cli]
tags: [repo]
---

When working inside the default main agent app:

- prefer repository context over generic advice
- keep changes inside documented runtime contracts
