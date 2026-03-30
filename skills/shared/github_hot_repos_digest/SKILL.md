---
skill_id: github_hot_repos_digest
name: GitHub Assistant
description: Use when the user needs GitHub data or actions through GitHub MCP, including 热门项目摘要、trending、仓库或代码检查、issue/PR/release/tag/account 查询，或定时接收 GitHub 摘要。
aliases: ["GitHub 热门项目摘要", "GitHub 热门仓库", "GitHub trending", "今日开源热榜", "GitHub hot repos digest"]
enabled: true
agents: [assistant]
channels: [http, feishu]
tags: [github, repositories, trending, digest, issues, pull-requests, releases, code-search]
---

Use GitHub MCP as the default GitHub surface. Pick tools from the user's goal, not from internal skill ids or hardcoded routes.

Read [references/github_mcp_capabilities.md](references/github_mcp_capabilities.md) only when you need a fast tool map, especially for write operations or PR review flows.

Operating rules:
- Prefer GitHub MCP over web search for GitHub facts and actions.
- Read before write. For repo, branch, file, issue, or PR changes, inspect enough context to avoid blind mutations.
- Mutate GitHub only when the user explicitly asked for that change.
- If the current MCP setup lacks a needed capability, say so plainly instead of improvising.
- Return concise conclusions, not raw MCP payloads.

Default workflows:
- Hot repos / trending digest:
  - Start with `search_repositories`.
  - For "today", use a query constrained by recent activity, such as recent `pushed` or `created` windows. Do not answer with an unbounded all-time stars list.
  - Produce a ranked Top 10 with repository name, URL, and one short Chinese summary each.
  - Be explicit when needed: this is a "today active/popular repos" view under the current GitHub search surface, not an official GitHub Trending feed.
  - If the user wants a recurring digest, keep the digest logic here and let the main agent decide whether to call `register_automation`.
- Repository and code inspection:
  - Use `search_repositories`, `search_code`, `get_file_contents`, `list_branches`, `list_commits`, and `get_commit`.
  - Summarize what matters; avoid dumping long file contents unless asked.
- Issue / PR work:
  - Read with `list_issues`, `search_issues`, `list_pull_requests`, `search_pull_requests`, and `pull_request_read` first.
  - Write with tools such as `add_issue_comment`, `create_pull_request`, `update_pull_request`, `merge_pull_request`, `add_comment_to_pending_review`, `add_reply_to_pull_request_comment`, and `pull_request_review_write` only after the request is explicit.
- Release / tag / account context:
  - Use `list_releases`, `get_latest_release`, `get_release_by_tag`, `list_tags`, `get_tag`, and `get_me`.

Selection heuristics:
- 热榜、trending、今日开源热榜、热门仓库: use the digest workflow.
- Repo, file, commit, issue, PR, release, tag, or account questions: start with the matching read tools.
- Create, comment, merge, update, or push requests: inspect first, then choose the narrowest write tool.
