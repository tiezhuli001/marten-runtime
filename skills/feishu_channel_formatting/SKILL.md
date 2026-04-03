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
- Treat 2+ lines, 2+ bullets, lists, grouped items, status summaries, checks, candidate sets, ranked results, or multi-record output as structured replies.
- When you emit `feishu_card`, keep the visible answer to one short summary line.
- Do not keep any visible bullet list or second paragraph outside `feishu_card`.
- Do not repeat the same bullet list both in the visible text and in `feishu_card`.
- Avoid Markdown tables in all Feishu replies.
- Never use Markdown tables, HTML, or code fences in the visible answer text.
- Prefer 2-5 flat bullets; for each item, prefer one compact line like `**名称**｜状态：...｜时间：...`.
- Use `title`, `summary`, and `sections` only; restate facts already present in the answer and do not add new facts in the card block.
- Do not emit keys like `type`, `template`, `items`, or other alternate card schemas.
- Canonical example: `{"title":"任务概览","summary":"共 2 项","sections":[{"items":["任务A｜已启用｜22:20","任务B｜已启用｜22:30"]}]}`.
- If you are not confident you can produce valid JSON, do not emit `feishu_card`.
- Never mention raw field names like `delivery_target`, `skill_id`, `automation_id`, or `trace_id`.
- `sections[].items` must be plain strings, never objects; flatten label/value content into one short string.
- For empty results, keep the same rule: one short explanation, and if it is not a one-line direct answer, include `feishu_card`.
- Do not expose internal ids or runtime plumbing.
