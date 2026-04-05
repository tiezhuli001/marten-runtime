from __future__ import annotations

import os
import re
from datetime import datetime
from html import unescape
from typing import Literal
from urllib.parse import urlencode

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator

_ARTICLE_RE = re.compile(r"<article\b[^>]*class=\"[^\"]*Box-row[^\"]*\"[^>]*>(.*?)</article>", re.S)
_REPO_LINK_RE = re.compile(
    r"<h2\b[^>]*>.*?<a\s+[^>]*href=\"(?P<href>/[^\"#?]+/[^\"#?]+)\"[^>]*>(?P<text>.*?)</a>.*?</h2>",
    re.S,
)
_DESCRIPTION_RE = re.compile(r"<p\b[^>]*>(?P<text>.*?)</p>", re.S)
_LANGUAGE_RE = re.compile(r"<span[^>]*itemprop=\"programmingLanguage\"[^>]*>(?P<text>.*?)</span>", re.S)
_STARS_RE = re.compile(r"<a\s+href=\"/[^\"#?]+/[^\"#?]+/stargazers\"[^>]*>(?P<text>.*?)</a>", re.S)
_STARS_PERIOD_RE = re.compile(r"(?P<count>[\d,]+)\s+stars?\s+(today|this week|this month)", re.I)
_TAGS_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

mcp = FastMCP("github-trending", log_level="ERROR")


class TrendingRepositoriesRequest(BaseModel):
    since: Literal["daily", "weekly", "monthly"] = "daily"
    language: str | None = None
    limit: int = 10

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized.lower() in {"all", "any", "*"}:
            return None
        return normalized or None

    @field_validator("limit")
    @classmethod
    def _validate_limit(cls, value: int) -> int:
        if value <= 0 or value > 25:
            raise ValueError("limit must be between 1 and 25")
        return value


class TrendingRepositoryItem(BaseModel):
    rank: int
    full_name: str
    name: str
    owner: str
    url: str
    description: str | None = None
    language: str | None = None
    stars_total: int | None = None
    stars_period: int | None = None
    forks_period: int | None = None


class TrendingRepositoriesResponse(BaseModel):
    source: str = "github_trending"
    order_basis: str = "github_trending_page_rank"
    order_note: str = (
        "Items are returned in the official GitHub Trending page order and may not match a descending stars sort."
    )
    since: Literal["daily", "weekly", "monthly"]
    language: str | None = None
    fetched_at: datetime = Field(default_factory=datetime.now)
    fetched_at_display: str
    items: list[TrendingRepositoryItem] = Field(default_factory=list)


def parse_trending_repositories(html: str, *, limit: int) -> list[TrendingRepositoryItem]:
    items: list[TrendingRepositoryItem] = []
    for index, article in enumerate(_ARTICLE_RE.findall(html), start=1):
        if len(items) >= limit:
            break
        anchor_match = _REPO_LINK_RE.search(article)
        if anchor_match is None:
            continue
        href = anchor_match.group("href").strip()
        full_name = _normalize_text(anchor_match.group("text")).replace(" / ", "/")
        if "/" not in full_name:
            path_parts = href.strip("/").split("/", 2)
            if len(path_parts) < 2:
                continue
            full_name = f"{path_parts[0]}/{path_parts[1]}"
        owner, name = full_name.split("/", 1)
        description_match = _DESCRIPTION_RE.search(article)
        language_match = _LANGUAGE_RE.search(article)
        stars_match = _STARS_RE.search(article)
        stars_period_match = _STARS_PERIOD_RE.search(article)
        items.append(
            TrendingRepositoryItem(
                rank=index,
                full_name=full_name,
                owner=owner,
                name=name,
                url=f"https://github.com{href}",
                description=_normalize_text(description_match.group("text")) if description_match else None,
                language=_normalize_text(language_match.group("text")) if language_match else None,
                stars_total=_parse_int(_normalize_text(stars_match.group("text"))) if stars_match else None,
                stars_period=_parse_int(stars_period_match.group("count")) if stars_period_match else None,
            )
        )
    return items


def fetch_trending_html(request: TrendingRepositoriesRequest) -> str:
    fixture_path = os.environ.get("GITHUB_TRENDING_FIXTURE_PATH")
    if fixture_path:
        with open(fixture_path, encoding="utf-8") as handle:
            return handle.read()
    headers = {
        "User-Agent": "marten-runtime-github-trending/0.1",
        "Accept": "text/html,application/xhtml+xml",
    }
    response = httpx.get(_build_trending_url(request), headers=headers, timeout=20.0, follow_redirects=True)
    response.raise_for_status()
    return response.text


@mcp.tool()
def trending_repositories(
    since: str = "daily",
    language: str | None = None,
    limit: int = 10,
) -> dict:
    """Fetch GitHub Trending repositories for today, this week, or this month.

    Use this tool for 热榜 / trending requests instead of repository search.
    The response includes:
    - `since`: current trend window (`daily`, `weekly`, `monthly`)
    - `fetched_at`: when the榜单 was fetched; render it to users as an explicit date+time such as `YYYY-MM-DD HH:MM`
    - `fetched_at_display`: preformatted fetched time string in exact `YYYY-MM-DD HH:MM`; use this value as-is in user-visible text
    - `items[].rank`: numeric rank for each repository; use it when rendering Top-N lists
    - `items`: already in the official GitHub Trending page order; preserve the returned order
    - `order_basis`: current ordering contract; this tool returns `github_trending_page_rank`
    - `order_note`: explains that the official page order may not match a descending stars sort
    - `items[].stars_period`: stars gained in the current window (preferred for ranking/output)
    - `items[].stars_total`: cumulative stars (secondary context only)
    Do not re-sort, regroup, or re-rank the returned repositories.
    Do not assume the page order equals descending `stars_period` or descending `stars_total`.
    Do not shorten `fetched_at_display` to `HH:MM` only.
    When showing ranks, use numeric markers like `1.` `2.` `3.` and avoid alphabetical markers.
    """
    request = TrendingRepositoriesRequest(since=since, language=language, limit=limit)
    html = fetch_trending_html(request)
    fetched_at = datetime.now()
    response = TrendingRepositoriesResponse(
        since=request.since,
        language=request.language,
        fetched_at=fetched_at,
        fetched_at_display=_format_display_datetime(fetched_at),
        items=parse_trending_repositories(html, limit=request.limit),
    )
    return response.model_dump(mode="json")


def _build_trending_url(request: TrendingRepositoriesRequest) -> str:
    params = {"since": request.since}
    if request.language:
        params["l"] = request.language
    return f"https://github.com/trending?{urlencode(params)}"


def _normalize_text(value: str) -> str:
    stripped = _TAGS_RE.sub(" ", unescape(value))
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    return int(digits)


def _format_display_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    mcp.run("stdio")
