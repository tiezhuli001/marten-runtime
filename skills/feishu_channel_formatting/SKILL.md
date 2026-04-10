---
skill_id: feishu_channel_formatting
name: Feishu Channel Formatting
description: Always-on Feishu formatting constraints for final user-visible replies. Use when the answer is heading to Feishu and must stay compact, skimmable, and card-friendly.
enabled: true
always_on: true
agents: [assistant]
channels: [feishu]
tags: [feishu, lark, formatting, channel]
---

Use these rules for all final Feishu replies.
- Lead with the direct answer or one short summary line.
- Only a one-line direct answer may stay plain text.
- Everything else must end with one trailing `feishu_card` JSON block.
- For structured replies, end with exactly one trailing fenced `feishu_card` block.
- The fence info string must be exactly `feishu_card`; do not use ```json, bare JSON, or any other wrapper for the card payload.
- Treat 2+ lines, 2+ bullets, lists, grouped items, status summaries, checks, candidate sets, ranked results, or multi-record output as structured replies.
- When you emit `feishu_card`, keep the visible answer to one short summary line.
- Do not keep any visible bullet list or second paragraph outside `feishu_card`.
- Do not append separators, extra paragraphs, or closing notes after `feishu_card`.
- Do not repeat the same bullet list both in the visible text and in `feishu_card`.
- Avoid Markdown tables in all Feishu replies.
- Never use Markdown tables, HTML, or code fences in the visible answer text.
- Prefer 2-5 flat bullets; for each item, prefer one compact line like `**名称**｜状态：...｜时间：...`.
- Use `title`, `summary`, and `sections` only; restate facts already present in the answer and do not add new facts in the card block.
- Do not emit keys like `type`, `template`, `items`, or other alternate card schemas.
- Canonical example: `{"title":"任务概览","summary":"共 2 项","sections":[{"items":["任务A｜已启用｜22:20","任务B｜已启用｜22:30"]}]}`.
- For GitHub trending answers, prefer `stars_period` over `stars_total`; if both appear, treat `stars_period` as the primary ranking signal and `stars_total` as optional secondary context.
- For GitHub trending answers, mention the trend window and fetched time using user-facing wording like `GitHub 日榜 Top 10（抓取于 2026-04-05 22:11）`.
- Do not write vague summaries like `Top 10 如下`; include the actual window such as `日榜`, `周榜`, or `月榜`.
- For GitHub trending answers, preserve the original repository order returned by the MCP result; this is the official GitHub Trending page order, not a local re-sort by `stars_period` or `stars_total`.
- For GitHub trending answers, do not re-rank, sort, or regroup trending items by stars, language, or topic.
- For GitHub trending answers, explicitly include one short user-facing note such as `榜单顺序遵循 GitHub Trending 页面` or `按 GitHub Trending 页面顺序` so users do not misread the list as a local stars sort.
- Keep that ordering note separate from the fetched-time wording; if the summary or title already contains `抓取于 ...`, do not repeat the fetched time again inside the ordering note.
- For ranked results such as GitHub trending, include numeric rank prefixes like `1.` / `2.` in `sections[].items` when rank is available.
- For ranked results such as GitHub trending, do not use alphabetical markers like `a.` / `b.` / `c.`.
- For GitHub trending fetched time, show the fetched date and time in one explicit string exactly as `YYYY-MM-DD HH:MM`; do not shorten it to `HH:MM` only.
- For automation status output, use `已启用` and `已暂停` as the only status labels; do not mix in `已禁用` or `已停用`.
- For automation summaries, keep the visible text factual and count-based; do not summarize shared category labels like `均为 GitHub 热榜推荐`.
- If you are not confident you can produce valid JSON, do not emit `feishu_card`.
- Never mention raw field names like `delivery_target`, `skill_id`, `automation_id`, or `trace_id`.
- `sections[].items` must be plain strings, never objects; flatten label/value content into one short string, and avoid nested list markers inside one item.
- For empty results, keep the same rule: one short explanation, and if it is not a one-line direct answer, include `feishu_card`.
- Do not expose internal ids or runtime plumbing.
