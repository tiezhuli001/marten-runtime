from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_REPO_URL_ENV = "MARTEN_REPO_URL"
_REPO_SLUG_ENV = "MARTEN_REPO_SLUG"
_REPO_BRANCH_ENV = "MARTEN_REPO_BRANCH"


@dataclass(frozen=True)
class RepositoryContext:
    slug: str | None = None
    url: str | None = None
    branch: str | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                str(self.slug or "").strip(),
                str(self.url or "").strip(),
                str(self.branch or "").strip(),
            )
        )


def resolve_repository_context(
    repo_root: str | Path | None,
    *,
    env: Mapping[str, str] | None = None,
) -> RepositoryContext | None:
    resolved_env = env or {}
    slug = _clean(resolved_env.get(_REPO_SLUG_ENV))
    url = _normalize_repo_url(resolved_env.get(_REPO_URL_ENV))
    branch = _clean(resolved_env.get(_REPO_BRANCH_ENV))
    root = Path(repo_root) if repo_root is not None else None
    if root is not None:
        if not branch:
            branch = _git_command(root, "rev-parse", "--abbrev-ref", "HEAD")
        if not slug or not url:
            remote = _git_command(root, "remote", "get-url", "origin")
            normalized_remote = _normalize_repo_url(remote)
            if normalized_remote and not url:
                url = normalized_remote
            if not slug:
                slug = _extract_repo_slug(normalized_remote or remote)
    if not slug:
        slug = _extract_repo_slug(url)
    context = RepositoryContext(
        slug=slug or None,
        url=url or None,
        branch=branch or None,
    )
    return None if context.is_empty() else context


def repository_context_env(repo_root: str | Path | None) -> dict[str, str]:
    context = resolve_repository_context(repo_root)
    if context is None:
        return {}
    values: dict[str, str] = {}
    if context.slug:
        values[_REPO_SLUG_ENV] = context.slug
    if context.url:
        values[_REPO_URL_ENV] = context.url
    if context.branch:
        values[_REPO_BRANCH_ENV] = context.branch
    return values


def render_repository_context_note(context: RepositoryContext | None) -> str | None:
    if context is None or context.is_empty():
        return None
    lines = ["当前运行仓库上下文："]
    if context.slug:
        lines.append(f"- 仓库标识：{context.slug}")
    if context.url:
        lines.append(f"- 仓库地址：{context.url}")
    lines.append(
        "当前子任务提到“这个仓库”“当前仓库”“README”“最近提交”时，可以直接使用这份仓库上下文定位目标仓库。"
    )
    lines.append("如果当前任务没有另外指定仓库，这个仓库就是默认目标仓库。")
    lines.append("除非当前任务明确切换到别的仓库，否则不要向用户重复请求 owner/repo。")
    lines.append("除非任务明确要求某个分支，否则直接使用仓库默认分支即可。")
    return "\n".join(lines)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _git_command(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def _normalize_repo_url(value: object) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    ssh_match = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", raw)
    if ssh_match:
        host, path = ssh_match.groups()
        return f"https://{host}/{path.strip('/')}"
    scheme_match = re.match(
        r"^(?P<scheme>https?|ssh)://(?P<body>.+?)(?:\.git)?$",
        raw,
        flags=re.IGNORECASE,
    )
    if scheme_match:
        scheme = scheme_match.group("scheme").lower()
        body = scheme_match.group("body").lstrip("/")
        if scheme == "ssh" and "@" in body:
            user_host, _, path = body.partition("/")
            host = user_host.split("@", 1)[-1]
            return f"https://{host}/{path}"
        if scheme in {"http", "https"}:
            return f"https://{body}"
    return raw.removesuffix(".git")


def _extract_repo_slug(value: object) -> str:
    normalized = _normalize_repo_url(value)
    if not normalized:
        return ""
    https_match = re.match(r"^https?://[^/]+/(.+?/.+?)$", normalized, flags=re.IGNORECASE)
    if https_match:
        return https_match.group(1).strip("/")
    ssh_match = re.match(r"^git@[^:]+:(.+?/.+?)(?:\.git)?$", str(value or ""))
    if ssh_match:
        return ssh_match.group(1).strip("/")
    return ""
