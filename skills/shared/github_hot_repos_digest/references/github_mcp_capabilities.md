# GitHub MCP Capabilities

This reference groups the GitHub MCP tools currently visible in this runtime so the skill can choose an appropriate path quickly.

## Read-oriented tools

- Account and identity: `get_me`
- Repository discovery: `search_repositories`, `search_users`, `fork_repository`
- Repository contents: `get_file_contents`, `search_code`
- Branches and commits: `list_branches`, `list_commits`, `get_commit`
- Issues: `issue_read`, `list_issues`, `search_issues`
- Pull requests: `pull_request_read`, `list_pull_requests`, `search_pull_requests`
- Releases and tags: `list_releases`, `get_latest_release`, `get_release_by_tag`, `list_tags`, `get_tag`

## Write-oriented tools

- Files and branches: `create_branch`, `create_or_update_file`, `push_files`, `delete_file`
- Issues: `issue_write`, `add_issue_comment`, `sub_issue_write`, `assign_copilot_to_issue`
- Pull requests and reviews: `create_pull_request`, `update_pull_request`, `update_pull_request_branch`, `merge_pull_request`, `pull_request_review_write`, `add_comment_to_pending_review`, `add_reply_to_pull_request_comment`, `request_copilot_review`
- Repository creation: `create_repository`

## Tool-choice heuristics

- Need to understand what is hot or notable on GitHub today:
  - Start with `search_repositories`
- Need to inspect repository structure or code:
  - Start with `search_code` or `get_file_contents`
- Need to inspect workflow or delivery state:
  - Start with `list_issues`, `list_pull_requests`, `list_releases`, `list_commits`
- Need to write back to GitHub:
  - Read first, then choose the narrowest write tool that matches the requested action

## Safety heuristics

- Prefer read tools until the user's requested mutation is explicit.
- Avoid broad write actions when a narrower comment or PR update tool is sufficient.
- If the user asks for a recurring digest, the main agent should decide whether to call `register_automation`; this reference only helps the skill perform GitHub work once it has been selected.
