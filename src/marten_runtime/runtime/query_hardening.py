from __future__ import annotations

import re

# Shared pure matcher/extractor helpers live here only to remove duplicate
# truth between runtime components. This module is intentionally not a general
# intent-routing or payload-shaping subsystem: it may answer yes/no or extract
# text spans, but it must not decide tools, server_id/tool_name, or arguments.
# Route policy stays in `loop.py`, and prompt/instruction shaping stays in
# `llm_client.py`.
_GITHUB_REPO_URL_RE = re.compile(r"https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)")
_GITHUB_OWNER_REPO_RE = re.compile(r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)")


def extract_github_repo_query(message: str) -> str | None:
    url_match = _GITHUB_REPO_URL_RE.search(message)
    if url_match:
        return f"{url_match.group('owner')}/{url_match.group('repo')}"
    repo_match = _GITHUB_OWNER_REPO_RE.search(message)
    if repo_match and ("github" in message.lower() or "repo" in message.lower() or "仓库" in message):
        return f"{repo_match.group('owner')}/{repo_match.group('repo')}"
    return None


def is_runtime_context_query(message: str) -> bool:
    normalized = message.lower()
    if "需不需要压缩" in message:
        return True
    if "context" in normalized and any(
        token in normalized for token in ("window", "usage", "status", "compression", "compress", "detail")
    ):
        return True
    if "上下文" not in message:
        return False
    detail_tokens = (
        "窗口",
        "用了多少",
        "占用",
        "状态",
        "压缩",
        "使用详情",
        "使用情况",
        "具体使用",
        "具体的使用",
        "明细",
        "详情",
    )
    return any(token in message for token in detail_tokens)


def is_time_query(message: str) -> bool:
    normalized = message.lower()
    tokens = ("现在几点", "当前几点", "当前时间", "几点了", "what time is it", "北京时间", "utc 时间", "utc time")
    return any(token in normalized or token in message for token in tokens)


def is_github_repo_commit_query(message: str) -> bool:
    normalized = message.lower()
    commit_tokens = (
        "commit",
        "commits",
        "提交",
        "提交记录",
        "提交历史",
        "最近一次提交",
        "最新提交",
        "最后一次提交",
        "last commit",
        "latest commit",
    )
    return any(token in normalized or token in message for token in commit_tokens)


def is_github_repo_metadata_query(message: str) -> bool:
    if is_github_repo_commit_query(message):
        return False
    normalized = message.lower()
    metadata_tokens = (
        "默认分支",
        "描述",
        "stars",
        "forks",
        "issues",
        "open issues",
        "private",
        "语言",
        "仓库信息",
        "基本信息",
        "default branch",
        "description",
        "language",
        "metadata",
    )
    return any(token in normalized or token in message for token in metadata_tokens)
