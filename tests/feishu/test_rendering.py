import json
import unittest
from unittest.mock import patch

from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.rendering import (
    FeishuCardProtocol,
    normalize_feishu_durable_text,
    normalize_feishu_visible_text,
    parse_feishu_card_protocol,
    render_final_reply_card,
)


class FeishuRenderingTests(unittest.TestCase):
    def test_parse_feishu_card_protocol_extracts_trailing_block(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前有 2 个任务。\n\n```feishu_card\n"
            '{"title":"任务","summary":"共 2 项","sections":[{"items":["A","B"]}]}\n'
            "```"
        )

        self.assertEqual(visible, "当前有 2 个任务。")
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "任务")
        self.assertEqual(protocol.summary, "共 2 项")
        self.assertEqual(protocol.sections[0].items, ["A", "B"])

    def test_parse_feishu_card_protocol_rejects_unsupported_keys(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            '检查结果。\n\n```feishu_card\n{"title":"ok","actions":[1]}\n```'
        )

        self.assertEqual(visible, '检查结果。\n\n```feishu_card\n{"title":"ok","actions":[1]}\n```')
        self.assertEqual(protocol, None)

    def test_parse_feishu_card_protocol_accepts_provider_style_invoke_block(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前有 **2 个定时任务**：\n\n"
            "- **GitHub热榜推荐**：每天 22:20｜已启用\n"
            "- **GitHub热榜推荐**：每天 22:30｜已启用\n\n"
            "<invoke name=\"feishu_card\">\n"
            "<parameter name=\"title\">定时任务概览</parameter>\n"
            "<parameter name=\"summary\">当前共 2 个定时任务</parameter>\n"
            "<parameter name=\"sections\">[{\"title\": \"任务列表\", \"items\": [\"GitHub热榜推荐：每天 22:20｜已启用\", \"GitHub热榜推荐：每天 22:30｜已启用\"]}]</parameter>\n"
            "</invoke>"
        )

        self.assertEqual(
            visible,
            "当前有 **2 个定时任务**：\n\n- **GitHub热榜推荐**：每天 22:20｜已启用\n- **GitHub热榜推荐**：每天 22:30｜已启用",
        )
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "定时任务概览")
        self.assertEqual(protocol.summary, "当前共 2 个定时任务")
        self.assertEqual(protocol.sections[0].title, "任务列表")
        self.assertEqual(
            protocol.sections[0].items,
            ["GitHub热榜推荐：每天 22:20｜已启用", "GitHub热榜推荐：每天 22:30｜已启用"],
        )

    def test_parse_feishu_card_protocol_accepts_provider_invoke_block_with_trailing_closer(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前共有 **2 个定时任务**。\n\n"
            "<invoke name=\"feishu_card\">\n"
            "<parameter name=\"title\">定时任务列表</parameter>\n"
            "<parameter name=\"summary\">共 2 项</parameter>\n"
            "<parameter name=\"sections\">[{\"items\": [\"GitHub热榜推荐｜已启用｜22:20\", \"GitHub热榜推荐｜已启用｜22:30\"]}]</parameter>\n"
            "</invoke>\n"
            "</minimax:tool_call>"
        )

        self.assertEqual(visible, "当前共有 **2 个定时任务**。")
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "定时任务列表")
        self.assertEqual(protocol.summary, "共 2 项")
        self.assertEqual(
            protocol.sections[0].items,
            ["GitHub热榜推荐｜已启用｜22:20", "GitHub热榜推荐｜已启用｜22:30"],
        )

    def test_parse_feishu_card_protocol_accepts_minimax_wrapper_before_invoke_block(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "<minimax:tool_call>\n"
            "<invoke name=\"feishu_card\">\n"
            "<parameter name=\"title\">GitHub 今日热榜</parameter>\n"
            "<parameter name=\"summary\">共 10 项</parameter>\n"
            "<parameter name=\"sections\">[{\"items\": [\"1｜gallery｜+286 ⭐\", \"2｜mlx-vlm｜+408 ⭐\"]}]</parameter>\n"
            "</invoke>\n"
            "</minimax:tool_call>"
        )

        self.assertEqual(visible, "")
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "GitHub 今日热榜")
        self.assertEqual(protocol.summary, "共 10 项")

    def test_parse_feishu_card_protocol_accepts_bare_marker_plus_json_suffix(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前有 **2 个定时任务**：\n\n"
            "- **GitHub热榜推荐**：每天 22:20｜已启用\n"
            "- **GitHub热榜推荐**：每天 22:30｜已启用\n\n"
            "feishu_card\n"
            "{\"title\":\"定时任务列表\",\"sections\":[{\"title\":\"任务\",\"items\":[\"GitHub热榜推荐：每天 22:20｜已启用\",\"GitHub热榜推荐：每天 22:30｜已启用\"]}]}"
        )

        self.assertEqual(
            visible,
            "当前有 **2 个定时任务**：\n\n- **GitHub热榜推荐**：每天 22:20｜已启用\n- **GitHub热榜推荐**：每天 22:30｜已启用",
        )
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "定时任务列表")
        self.assertEqual(protocol.sections[0].title, "任务")
        self.assertEqual(
            protocol.sections[0].items,
            ["GitHub热榜推荐：每天 22:20｜已启用", "GitHub热榜推荐：每天 22:30｜已启用"],
        )

    def test_parse_feishu_card_protocol_accepts_json_fenced_wrapper_object(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前共有 **2 个定时任务**。\n\n"
            "```json\n"
            '{"feishu_card":{"title":"定时任务列表","summary":"当前共 2 个定时任务","sections":[{"items":["任务1：GitHub热榜推荐 - 每天 22:20（启用）","任务2：GitHub热榜推荐 - 每天 22:30（启用）"]}]}}\n'
            "```"
        )

        self.assertEqual(visible, "当前共有 **2 个定时任务**。")
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "定时任务列表")
        self.assertEqual(protocol.summary, "当前共 2 个定时任务")
        self.assertEqual(
            protocol.sections[0].items,
            ["任务1：GitHub热榜推荐 - 每天 22:20（启用）", "任务2：GitHub热榜推荐 - 每天 22:30（启用）"],
        )

    def test_parse_feishu_card_protocol_accepts_bare_marker_then_fenced_json(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前共有 **2 个自动任务**。\n\n"
            "feishu_card\n"
            "```json\n"
            '{"title":"自动任务概览","summary":"共 2 个定时任务","sections":[{"items":["GitHub热榜推荐｜每天 22:20｜已启用","GitHub热榜推荐｜每天 22:30｜已启用"]}]}\n'
            "```"
        )

        self.assertEqual(visible, "当前共有 **2 个自动任务**。")
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "自动任务概览")
        self.assertEqual(protocol.summary, "共 2 个定时任务")
        self.assertEqual(
            protocol.sections[0].items,
            ["GitHub热榜推荐｜每天 22:20｜已启用", "GitHub热榜推荐｜每天 22:30｜已启用"],
        )

    def test_parse_feishu_card_protocol_accepts_bare_trailing_protocol_json(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前共有 2 个自动任务，都是 GitHub 热榜推荐。\n\n"
            '{"title":"自动任务概览","summary":"共 2 项","sections":[{"items":["GitHub热榜推荐｜已启用｜22:20","GitHub热榜推荐｜已启用｜22:30"]}]}'
        )

        self.assertEqual(visible, "当前共有 2 个自动任务，都是 GitHub 热榜推荐。")
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "自动任务概览")
        self.assertEqual(protocol.summary, "共 2 项")
        self.assertEqual(
            protocol.sections[0].items,
            ["GitHub热榜推荐｜已启用｜22:20", "GitHub热榜推荐｜已启用｜22:30"],
        )

    def test_parse_feishu_card_protocol_accepts_fenced_block_with_trailing_note(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "✅ 工具状态检查完成\n\n"
            "```feishu_card\n"
            '{"title":"工具状态","summary":"共 3 项","sections":[{"items":["普通对话正常","builtin 工具正常","mcp 工具正常"]}]}\n'
            "```\n\n"
            "接下来继续做 live 验证。"
        )

        self.assertEqual(visible, "✅ 工具状态检查完成\n\n接下来继续做 live 验证。")
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "工具状态")
        self.assertEqual(protocol.summary, "共 3 项")

    def test_normalize_feishu_visible_text_strips_trailing_fence_residue_after_protocol_parse(self) -> None:
        text = (
            "处理完成。\n\n"
            "```feishu_card\n"
            '{"title":"结果","summary":"1 条","sections":[{"items":["ok"]}]}\n'
            "```\n```"
        )

        self.assertEqual(normalize_feishu_visible_text(text), "处理完成。")

    def test_normalize_feishu_visible_text_strips_trailing_invoke_residue_after_protocol_parse(self) -> None:
        text = (
            "处理完成。\n\n"
            "<invoke name=\"feishu_card\">\n"
            "<parameter name=\"title\">结果</parameter>\n"
            "<parameter name=\"summary\">1 条</parameter>\n"
            "<parameter name=\"sections\">[{\"items\": [\"ok\"]}]</parameter>\n"
            "</invoke>\n"
            "</minimax:tool_call>"
        )

        self.assertEqual(normalize_feishu_visible_text(text), "处理完成。")

    def test_normalize_feishu_visible_text_keeps_plain_xml_like_trailing_line_without_protocol_context(
        self,
    ) -> None:
        text = "XML 示例：\n</invoke>"
        self.assertEqual(normalize_feishu_visible_text(text), text)

    def test_normalize_feishu_durable_text_preserves_protocol_summary_and_sections(self) -> None:
        text = (
            "处理完成。\n\n"
            "```feishu_card\n"
            '{"title":"结果","summary":"共 2 项","sections":[{"title":"详情","items":["builtin 正常","mcp 正常"]}]}\n'
            "```"
        )

        self.assertEqual(
            normalize_feishu_durable_text(text),
            "处理完成。\n\n共 2 项\n\n详情\n- builtin 正常\n- mcp 正常",
        )

    def test_normalize_feishu_durable_text_preserves_provider_invoke_detail(self) -> None:
        text = (
            "已完成检查。\n\n"
            "<invoke name=\"feishu_card\">\n"
            "<parameter name=\"title\">检查结果</parameter>\n"
            "<parameter name=\"summary\">共 2 项</parameter>\n"
            "<parameter name=\"sections\">[{\"title\": \"详情\", \"items\": [\"builtin 正常\", \"mcp 正常\"]}]</parameter>\n"
            "</invoke>\n"
            "</minimax:tool_call>"
        )

        self.assertEqual(
            normalize_feishu_durable_text(text),
            "已完成检查。\n\n共 2 项\n\n详情\n- builtin 正常\n- mcp 正常",
        )

    def test_normalize_feishu_durable_text_keeps_plain_non_protocol_text(self) -> None:
        text = "最近一次提交时间是：`2026-04-17T09:55:00Z`"
        self.assertEqual(normalize_feishu_durable_text(text), text)

    def test_parse_feishu_card_protocol_strips_trailing_followup_offer_from_visible_text(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "最近一次提交时间是：`2026-04-17T09:55:00Z`\n\n"
            "如果你需要，我也可以继续帮你换算成北京时间。"
        )

        self.assertEqual(visible, "最近一次提交时间是：`2026-04-17T09:55:00Z`")
        self.assertIsNone(protocol)

    def test_render_final_reply_card_strips_trailing_followup_offer(self) -> None:
        card = render_final_reply_card(
            "最近一次提交时间是：`2026-04-17T09:55:00Z`\n\n"
            "如果你需要，我也可以继续帮你换算成北京时间。"
        )

        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "最近一次提交时间是：`2026-04-17T09:55:00Z`")
        self.assertEqual(card["header"]["title"]["content"], "仓库最近提交")

    def test_parse_feishu_card_protocol_accepts_inline_trailing_protocol_json(self) -> None:
        visible, protocol = parse_feishu_card_protocol(
            "当前共有 **3 个定时任务**，都是 GitHub 热门仓库推送：\n\n"
            "- **GitHub热榜推荐**｜22:20｜已启用\n"
            "- **GitHub热榜推荐**｜22:00｜已启用\n"
            "- **GitHub热榜推荐**｜22:30｜已启用\n\n"
            "均推送到同一个飞书会话。"
            '{"title":"定时任务概览","summary":"共 3 项","sections":[{"items":["GitHub热榜推荐｜22:20｜已启用","GitHub热榜推荐｜22:00｜已启用","GitHub热榜推荐｜22:30｜已启用"]}]}'
        )

        self.assertEqual(
            visible,
            "当前共有 **3 个定时任务**，都是 GitHub 热门仓库推送：\n\n"
            "- **GitHub热榜推荐**｜22:20｜已启用\n"
            "- **GitHub热榜推荐**｜22:00｜已启用\n"
            "- **GitHub热榜推荐**｜22:30｜已启用\n\n"
            "均推送到同一个飞书会话。",
        )
        self.assertIsInstance(protocol, FeishuCardProtocol)
        self.assertEqual(protocol.title, "定时任务概览")
        self.assertEqual(protocol.summary, "共 3 项")

    def test_render_final_reply_card_strips_inline_trailing_protocol_json(self) -> None:
        card = render_final_reply_card(
            "当前共有 **3 个定时任务**，都是 GitHub 热门仓库推送：\n\n"
            "- **GitHub热榜推荐**｜22:20｜已启用\n"
            "- **GitHub热榜推荐**｜22:00｜已启用\n"
            "- **GitHub热榜推荐**｜22:30｜已启用\n\n"
            "均推送到同一个飞书会话。"
            '{"title":"定时任务概览","summary":"共 3 项","sections":[{"items":["GitHub热榜推荐｜22:20｜已启用","GitHub热榜推荐｜22:00｜已启用","GitHub热榜推荐｜22:30｜已启用"]}]}'
        )

        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["title"]["content"], "定时任务概览")
        self.assertEqual(card["header"]["template"], "indigo")
        elements = card["body"]["elements"]
        self.assertEqual(
            elements[0]["content"],
            "当前共有 **3 个定时任务**，都是 GitHub 热门仓库推送：\n\n均推送到同一个飞书会话。",
        )
        self.assertEqual(elements[1]["tag"], "hr")
        self.assertEqual(elements[2]["content"], "**📌 共 3 项**")
        self.assertEqual(
            elements[3]["content"],
            "**🗂️ 详情**",
        )
        self.assertEqual(
            elements[4]["content"],
            "- GitHub热榜推荐｜22:20｜已启用\n- GitHub热榜推荐｜22:00｜已启用\n- GitHub热榜推荐｜22:30｜已启用",
        )


    def test_render_final_reply_card_strips_visible_markdown_table_when_protocol_sections_exist(self) -> None:
        card = render_final_reply_card(
            "今日 GitHub 热榜（2026-04-05）:\n\n"
            "| 排名 | 仓库 | 语言 | 今日新增 | 简介 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 1 | google-ai-edge/gallery | Kotlin | +286 | 本地ML/GenAI用例展示 |\n"
            "| 2 | mlx-vlm | Python | +408 | VLM |\n\n"
            '{"title":"今日GitHub热榜","summary":"共 10 项","sections":[{"items":["google-ai-edge/gallery｜Kotlin｜+286｜本地ML/GenAI用例展示","mlx-vlm｜Python｜+408｜VLM"]}]}'
        )

        elements = card["body"]["elements"]
        self.assertEqual(card["header"]["title"]["content"], "今日GitHub热榜")
        self.assertEqual(elements[0]["content"], "今日 GitHub 热榜（2026-04-05）:")
        self.assertEqual(elements[1]["tag"], "hr")
        self.assertEqual(elements[2]["content"], "**📌 共 10 项**")
        self.assertEqual(elements[3]["content"], "**🗂️ 详情**")
        self.assertEqual(
            elements[4]["content"],
            "- google-ai-edge/gallery｜Kotlin｜+286｜本地ML/GenAI用例展示\n- mlx-vlm｜Python｜+408｜VLM",
        )

    def test_render_final_reply_card_uses_generic_visual_slot_order(self) -> None:
        card = render_final_reply_card(
            "当前有 2 个任务。\n\n```feishu_card\n"
            '{"title":"启用中的任务","summary":"共 2 项","sections":[{"title":"任务列表","items":["日报同步：每天 22:20","失败样本回看：每 6 小时"]}]}\n'
            "```"
        )

        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["title"]["content"], "启用中的任务")
        self.assertEqual(card["header"]["template"], "indigo")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "当前有 2 个任务。")
        self.assertEqual(elements[1]["tag"], "hr")
        self.assertEqual(elements[2]["content"], "**📌 共 2 项**")
        self.assertEqual(elements[3]["content"], "**🗂️ 任务列表**")
        self.assertEqual(elements[4]["content"], "- 日报同步：每天 22:20\n- 失败样本回看：每 6 小时")

    def test_render_final_reply_card_deduplicates_visible_bullets_when_protocol_present(self) -> None:
        card = render_final_reply_card(
            "当前共有 **3 个定时任务**，都是 GitHub 热门仓库推送：\n\n"
            "- **GitHub热榜推荐**｜22:20｜已启用\n"
            "- **GitHub热榜推荐**｜22:00｜已启用\n"
            "- **GitHub热榜推荐**｜22:30｜已启用\n\n"
            '{"title":"定时任务概览","summary":"共 3 项","sections":[{"items":["GitHub热榜推荐｜22:20｜已启用","GitHub热榜推荐｜22:00｜已启用","GitHub热榜推荐｜22:30｜已启用"]}]}'
        )

        self.assertEqual(card["header"]["title"]["content"], "定时任务概览")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "当前共有 **3 个定时任务**，都是 GitHub 热门仓库推送：")
        self.assertEqual(elements[2]["content"], "**📌 共 3 项**")
        self.assertEqual(
            elements[4]["content"],
            "- GitHub热榜推荐｜22:20｜已启用\n- GitHub热榜推荐｜22:00｜已启用\n- GitHub热榜推荐｜22:30｜已启用",
        )

    def test_render_final_reply_card_strips_visible_bullets_when_protocol_items_are_compacted(self) -> None:
        card = render_final_reply_card(
            "当前共有 **4 个定时任务**，均为 GitHub 热榜相关的每日推送：\n\n"
            "- **GitHub热榜推荐**｜每天 22:20｜已启用\n"
            "- **GitHub热榜推荐**｜每天 21:10｜已启用\n"
            "- **GitHub热榜推荐**｜每天 22:00｜已启用\n"
            "- **GitHub热榜推荐**｜每天 22:30｜已启用\n\n"
            '{"title":"定时任务概览","summary":"共 4 项","sections":[{"items":["GitHub热榜推荐｜22:20","GitHub热榜推荐｜21:10","GitHub热榜推荐｜22:00","GitHub热榜推荐｜22:30"]}]}'
        )

        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "当前共有 **4 个定时任务**，均为 GitHub 热榜相关的每日推送：")
        self.assertEqual(elements[1]["tag"], "hr")
        self.assertEqual(elements[2]["content"], "**📌 共 4 项**")
        self.assertEqual(elements[3]["content"], "**🗂️ 详情**")
        self.assertEqual(
            elements[4]["content"],
            "- GitHub热榜推荐｜22:20\n- GitHub热榜推荐｜21:10\n- GitHub热榜推荐｜22:00\n- GitHub热榜推荐｜22:30",
        )

    def test_render_final_reply_card_keeps_existing_ordered_markers_without_double_bullets(self) -> None:
        card = render_final_reply_card(
            "这里是今日 GitHub 热榜。\n\n"
            '{"title":"今日GitHub热榜","summary":"共 2 项","sections":[{"items":["1. owner-one/repo-one｜Python｜+321","2. owner-two/repo-two｜TypeScript｜+210"]}]}'
        )

        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "这里是今日 GitHub 热榜。")
        self.assertEqual(elements[2]["content"], "**📌 共 2 项**")
        self.assertEqual(elements[3]["content"], "**🗂️ 详情**")
        self.assertEqual(
            elements[4]["content"],
            "1. owner-one/repo-one｜Python｜+321\n2. owner-two/repo-two｜TypeScript｜+210",
        )

    def test_render_final_reply_card_derives_generic_structure_from_plain_bullets(self) -> None:
        card = render_final_reply_card(
            "当前共有 **2 个定时任务**，都是 GitHub 热榜推荐：\n\n"
            "- **GitHub热榜推荐**｜22:20｜每天｜已启用\n"
            "- **GitHub热榜推荐**｜22:30｜每天｜已启用\n\n"
            "两者都推送到同一个飞书会话。"
        )

        self.assertEqual(card["header"]["title"]["content"], "当前共有 2 个定时任务")
        self.assertEqual(card["header"]["template"], "indigo")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**📌 都是 GitHub 热榜推荐**")
        self.assertEqual(
            elements[1]["content"],
            "**🗂️ 详情**",
        )
        self.assertEqual(
            elements[2]["content"],
            "- **GitHub热榜推荐**｜22:20｜每天｜已启用\n- **GitHub热榜推荐**｜22:30｜每天｜已启用",
        )
        self.assertEqual(elements[3]["tag"], "hr")
        self.assertEqual(elements[4]["content"], "<font color='grey'>💬 两者都推送到同一个飞书会话。</font>")

    def test_render_final_reply_card_uses_runtime_heading_for_context_status_text(self) -> None:
        card = render_final_reply_card(
            "当前上下文使用详情\n"
            "- 当前会话下一次请求预计带入 3673 tokens（约 2% / 184000）。\n"
            "- 有效窗口：184000 tokens（原始窗口 200000）。\n"
            "- 压缩状态：稳定。"
        )

        self.assertEqual(card["header"]["title"]["content"], "当前上下文使用详情")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**🗂️ 当前上下文使用详情**")
        self.assertIn("当前会话下一次请求预计带入", elements[1]["content"])

    def test_render_final_reply_card_uses_runtime_heading_when_actual_peak_is_unavailable(self) -> None:
        card = render_final_reply_card(
            "当前上下文使用详情\n"
            "- 当前会话下一次请求预计带入 3838 tokens（约 2% / 184000）。\n"
            "- 有效窗口：184000 tokens（原始窗口 200000）。\n"
            "- 压缩状态：稳定。"
        )

        self.assertEqual(card["header"]["title"]["content"], "当前上下文使用详情")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**🗂️ 当前上下文使用详情**")
        self.assertIn("当前会话下一次请求预计带入", elements[1]["content"])

    def test_render_final_reply_card_derives_runtime_title_from_single_paragraph_summary(self) -> None:
        card = render_final_reply_card(
            "当前上下文使用详情：上下文窗口健康，下一次请求预计输入 1200 tokens。",
            usage_summary={
                "input_tokens": 4100,
                "output_tokens": 0,
                "peak_tokens": 4663,
            },
        )

        self.assertEqual(card["header"]["title"]["content"], "当前上下文使用详情")
        contents = [element.get("content", "") for element in card["body"]["elements"]]
        self.assertTrue(any("本轮模型 token" in content for content in contents))

    def test_render_final_reply_card_formats_session_catalog_plain_text_as_structured_sections(self) -> None:
        card = render_final_reply_card(
            "当前有 1 个可见会话。\n"
            "1. 标题：开启子代理查询github上…\n"
            "详情：开启子代理查询github上的GitHub - tiezhuli001/codex-skills 最近一次提交是什么时候。\n"
            "状态：running\n"
            "消息数：33\n"
            "创建时间：2026-04-19 23:30:41\n"
            "session_id：sess_dcce8f9c"
        )

        self.assertEqual(card["header"]["title"]["content"], "会话列表")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**📌 当前有 1 个可见会话。**")
        self.assertEqual(elements[1]["content"], "**🗂️ 会话详情**")
        self.assertIn("1. 标题：开启子代理查询github上…", elements[2]["content"])
        self.assertIn("\n- 详情：开启子代理查询github上的GitHub - tiezhuli001/codex-skills 最近一次提交是什么时候。", elements[2]["content"])
        self.assertIn("\n- 状态：running", elements[2]["content"])
        self.assertIn("\n- session_id：sess_dcce8f9c", elements[2]["content"])

    def test_render_final_reply_card_appends_usage_footer_for_session_catalog_card(self) -> None:
        card = render_final_reply_card(
            "当前有 1 个可见会话。\n"
            "1. 标题：开启子代理查询github上…\n"
            "详情：开启子代理查询github上的GitHub - tiezhuli001/codex-skills 最近一次提交是什么时候。\n"
            "状态：running\n"
            "消息数：33\n"
            "创建时间：2026-04-19 23:30:41\n"
            "session_id：sess_dcce8f9c",
            usage_summary={
                "input_tokens": 3198,
                "output_tokens": 82,
                "peak_tokens": 3280,
                "cumulative_input_tokens": 4510,
                "cumulative_output_tokens": 143,
                "cumulative_tokens": 4653,
            },
        )

        contents = [element.get("content", "") for element in card["body"]["elements"]]
        self.assertTrue(any("本轮模型 token" in content for content in contents))

    def test_render_final_reply_card_appends_usage_footer_for_runtime_context_card(self) -> None:
        card = render_final_reply_card(
            "当前上下文使用详情\n"
            "- 当前会话下一次请求预计带入 3838 tokens（约 2% / 184000）。\n"
            "- 有效窗口：184000 tokens（原始窗口 200000）。\n"
            "- 压缩状态：稳定。",
            usage_summary={
                "input_tokens": 3198,
                "output_tokens": 82,
                "peak_tokens": 3280,
                "cumulative_input_tokens": 4510,
                "cumulative_output_tokens": 143,
                "cumulative_tokens": 4653,
            },
        )

        contents = [element.get("content", "") for element in card["body"]["elements"]]
        self.assertTrue(any("本轮模型 token" in content for content in contents))

    def test_render_final_reply_card_splits_multisection_plain_text_and_keeps_note(self) -> None:
        card = render_final_reply_card(
            "现在是北京时间 2026年4月20日 10:20\n\n"
            "当前上下文使用详情\n"
            "- 当前会话下一次请求预计带入 5707 tokens（约 3% / 184000）。\n"
            "- 有效窗口：184000 tokens（原始窗口 200000）。\n"
            "- 压缩状态：稳定。\n\n"
            "当前可用 MCP 服务共 2 个。\n"
            "1. github（38 个工具，状态 discovered）\n"
            "2. github-trending（1 个工具，状态 configured）\n\n"
            "本次请求共发生 3 次模型请求和 3 次工具调用，属于多次模型/工具往返。"
        )

        self.assertEqual(card["header"]["title"]["content"], "链路结果")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "现在是北京时间 2026年4月20日 10:20")
        self.assertEqual(elements[1]["content"], "**🗂️ 当前上下文使用详情**")
        self.assertIn("当前会话下一次请求预计带入 5707 tokens", elements[2]["content"])
        self.assertEqual(elements[3]["content"], "**🗂️ 当前可用 MCP 服务共 2 个**")
        self.assertEqual(
            elements[4]["content"],
            "1. github（38 个工具，状态 discovered）\n2. github-trending（1 个工具，状态 configured）",
        )

    def test_render_final_reply_card_derives_session_catalog_title_from_markdown_table(self) -> None:
        card = render_final_reply_card(
            "当前有 2 个可见会话。\n\n"
            "| 序号 | 标题 | 状态 | 消息数 | 创建时间 | session_id |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 1 | 上下文窗口大小 | running | 24 | 2026-04-20 13:52:43 | sess_46500a92 |\n"
            "| 2 | 切换到 sess_dcce8f9c 会话 | running | 2 | 2026-04-21 01:52:31 | sess_f8793b28 |"
        )

        self.assertEqual(card["header"]["title"]["content"], "会话列表")
        elements = card["body"]["elements"]
        self.assertIn("| 序号 | 标题 | 状态 | 消息数 | 创建时间 | session_id |", elements[0]["content"])

    def test_render_final_reply_card_keeps_multisection_order_when_list_section_contains_continuation_lines(
        self,
    ) -> None:
        card = render_final_reply_card(
            "已按你要求的顺序完成 3 次工具调用，链路如下。\n\n"
            "1. 先调用 `time`\n"
            "- 时区：`Asia/Shanghai`\n"
            "- 当前时间：`2026-04-21T19:34:28.355765+08:00`\n\n"
            "2. 再调用 `runtime` 查看 `context_status`\n"
            "- 模型配置：`openai_gpt5`\n"
            "- 上下文窗口：`200000`\n"
            "- 有效窗口：`184000`\n\n"
            "3. 最后调用 `mcp` 列出 github server 可用工具\n"
            "- 发现了两个相关 server：\n"
            "  - `github`\n"
            "  - 状态：`discovered`\n"
            "  - 工具数：`38`\n"
            "  - 可用工具包括：\n"
            "    `add_comment_to_pending_review`, `add_issue_comment`\n"
            "  - `github_trending`\n"
            "  - 状态：`configured`\n"
            "  - 工具数：`1`\n"
            "  - 工具：`trending_repositories`\n\n"
            "中文总结\n"
            "- 这次链路是严格串行执行的。\n"
            "- 当前上下文状态稳定。"
        )

        self.assertEqual(card["header"]["title"]["content"], "已按你要求的顺序完成 3 次工具调用")
        elements = [element.get("content", "") for element in card["body"]["elements"]]
        self.assertEqual(elements[0], "**📌 链路如下**")
        self.assertIn("1. 先调用 `time`", elements[2])
        self.assertIn("2. 再调用 `runtime` 查看 `context_status`", elements[4])
        self.assertIn("3. 最后调用 `mcp` 列出 github server 可用工具", elements[6])
        self.assertEqual(elements[7], "**🗂️ 中文总结**")

    def test_render_final_reply_card_uses_session_switch_title_and_appends_footer(self) -> None:
        card = render_final_reply_card(
            "已切换到新会话。后续消息会在新会话中继续。",
            usage_summary={
                "input_tokens": 4989,
                "output_tokens": 0,
                "peak_tokens": 5277,
            },
        )

        self.assertEqual(card["header"]["title"]["content"], "已切换到新会话")
        contents = [element.get("content", "") for element in card["body"]["elements"]]
        self.assertTrue(any("本轮模型 token" in content for content in contents))

    def test_render_final_reply_card_derives_trending_title_from_plain_bullets(self) -> None:
        card = render_final_reply_card(
            "GitHub 今日热榜，按官方 Trending 排序（2026-04-08 16:42 抓取，共 2 个项目）\n"
            "- 1. google-ai-edge/gallery（Kotlin，+897★）\n"
            "- 2. google-ai-edge/LiteRT-LM（C++，+528★）"
        )

        self.assertEqual(card["header"]["title"]["content"], "GitHub 今日热榜")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**📌 按官方 Trending 排序（2026-04-08 16:42 抓取，共 2 个项目）**")
        self.assertEqual(elements[1]["content"], "**🗂️ 详情**")
        self.assertIn("1. google-ai-edge/gallery", elements[2]["content"])

    def test_render_final_reply_card_derives_plain_title_from_intro_line(self) -> None:
        card = render_final_reply_card(
            "查到了，仓库基本信息如下：\n\n"
            "| 项目 | 信息 |\n"
            "|------|------|\n"
            "| 默认分支 | main |"
        )

        self.assertEqual(card["header"]["title"]["content"], "仓库基本信息")

    def test_render_final_reply_card_uses_protocol_title_when_fenced_block_has_trailing_note(self) -> None:
        card = render_final_reply_card(
            "✅ 工具状态检查完成\n\n"
            "```feishu_card\n"
            '{"title":"工具状态","summary":"共 3 项","sections":[{"items":["普通对话正常","builtin 工具正常","mcp 工具正常"]}]}\n'
            "```\n\n"
            "接下来继续做 live 验证。"
        )

        self.assertEqual(card["header"]["title"]["content"], "工具状态")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "✅ 工具状态检查完成\n\n接下来继续做 live 验证。")
        self.assertEqual(elements[2]["content"], "**📌 共 3 项**")

    def test_render_final_reply_card_appends_usage_footer_when_summary_present(self) -> None:
        card = render_final_reply_card(
            "处理完成。",
            usage_summary={
                "input_tokens": 3198,
                "output_tokens": 82,
                "peak_tokens": 3280,
                "cumulative_input_tokens": 4510,
                "cumulative_output_tokens": 143,
                "cumulative_tokens": 4653,
                "llm_request_count": 2,
            },
        )

        elements = card["body"]["elements"]
        self.assertEqual(elements[-2]["tag"], "hr")
        self.assertEqual(
            elements[-1]["content"],
            "<font color='grey'>本轮模型 token（2 次请求合计）：输入 4510｜输出 143｜合计 4653｜单次峰值 3280（峰值轮输入 3198｜输出 82）</font>",
        )

    def test_render_final_reply_card_omits_usage_footer_when_summary_absent(self) -> None:
        card = render_final_reply_card("处理完成。")

        contents = [element.get("content", "") for element in card["body"]["elements"]]
        self.assertFalse(any("本轮模型 token：" in content for content in contents))

    def test_delivery_final_rendering_passes_usage_summary_to_renderer(self) -> None:
        captured: list[tuple[str, dict[str, str], dict]] = []

        def fake_post(url: str, headers: dict[str, str], body: dict) -> dict:
            captured.append((url, headers, body))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            return {"code": 0, "data": {"message_id": "om_message_usage"}}

        client = FeishuDeliveryClient(
            env={"FEISHU_APP_ID": "app-id", "FEISHU_APP_SECRET": "app-secret"},
            transport=fake_post,
        )
        payload = FeishuDeliveryPayload(
            chat_id="chat_usage_1",
            event_type="final",
            event_id="evt_usage_1",
            run_id="run_usage_1",
            trace_id="trace_usage_1",
            sequence=1,
            text="usage delegated",
            usage_summary={"input_tokens": 11, "output_tokens": 7, "peak_tokens": 18},
        )

        with patch(
            "marten_runtime.channels.feishu.delivery.feishu_rendering.render_final_reply_card",
            return_value={"config": {"wide_screen_mode": True}, "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "delegated"}}]},
        ) as render_mock:
            client.send(payload)

        render_mock.assert_called_once_with(
            "usage delegated",
            event_type="final",
            usage_summary={"input_tokens": 11, "output_tokens": 7, "peak_tokens": 18},
        )

    def test_render_final_reply_card_derives_time_title_for_current_time_reply(self) -> None:
        card = render_final_reply_card("当前北京时间是 2026年4月7日 23:27:56。")

        self.assertEqual(card["header"]["title"]["content"], "当前时间")

    def test_render_final_reply_card_derives_commit_title_without_repo_slug(self) -> None:
        card = render_final_reply_card(
            "最近一次提交于 **2026-04-05 13:48:45 UTC**，提交信息为 `release: v2.7.2`，提交者是 leemac。"
        )

        self.assertEqual(card["header"]["title"]["content"], "仓库最近提交")

    def test_render_final_reply_card_derives_commit_title_with_repo_slug(self) -> None:
        card = render_final_reply_card(
            "llt22/talkio 最近一次提交是 **2026-04-05 21:48:45**（北京时间），提交信息为 `release: v2.7.2`。"
        )

        self.assertEqual(card["header"]["title"]["content"], "llt22/talkio 最近提交")

    def test_render_final_reply_card_derives_background_task_completed_title(self) -> None:
        card = render_final_reply_card(
            "后台任务已完成：调研 codex-skills 仓库能力\n tiezhuli001/codex-skills 最近一次提交是 **2026-04-14 20:01:21**（北京时间）。"
        )

        self.assertEqual(card["header"]["title"]["content"], "后台任务完成")

    def test_render_final_reply_card_structures_background_task_completion_message(self) -> None:
        card = render_final_reply_card(
            "后台任务已完成：调研 codex-skills 仓库能力\n"
            "tiezhuli001/codex-skills 最近一次提交是 **2026-04-14 20:01:21**（北京时间）。"
        )

        self.assertEqual(card["header"]["title"]["content"], "后台任务完成")
        elements = card["body"]["elements"]
        self.assertEqual(
            elements[0]["content"],
            "tiezhuli001/codex-skills 最近一次提交是 **2026-04-14 20:01:21**（北京时间）。",
        )
        self.assertEqual(elements[2]["content"], "**📌 任务：调研 codex-skills 仓库能力**")
        joined = "\n".join(element["content"] for element in elements if element["tag"] == "markdown")
        self.assertNotIn("后台任务已完成：", joined)

    def test_render_final_reply_card_strips_background_task_followup_suggestions(self) -> None:
        card = render_final_reply_card(
            "后台任务已完成：调研 codex-skills 仓库能力\n"
            "tiezhuli001/codex-skills 最近一次提交是 **2026-04-17 17:55:00**（北京时间），"
            "commit 信息为 `Merge pull request #2`。\n\n"
            "如果你要，我也可以继续帮你：\n"
            "转成北京时间\n"
            "再列出最近 5 次提交\n"
            "或核对默认分支上的最新 commit 是否一致"
        )

        joined = "\n".join(element["content"] for element in card["body"]["elements"] if element["tag"] == "markdown")
        self.assertIn("最近一次提交是", joined)
        self.assertNotIn("如果你要", joined)
        self.assertNotIn("再列出最近 5 次提交", joined)

    def test_render_final_reply_card_structures_subagent_system_completion_message(self) -> None:
        card = render_final_reply_card(
            "subagent task completed: 查询 codex-skills 最近提交\n"
            "summary: tiezhuli001/codex-skills 最近一次提交是 **2026-04-17 17:55:00**（北京时间），"
            "commit 信息为 `Merge pull request #2 from tiezhuli001/docs/add-linuxdo-link docs: add linux do community link to readme`。"
        )

        self.assertEqual(card["header"]["title"]["content"], "子任务完成")
        elements = card["body"]["elements"]
        self.assertIn("tiezhuli001/codex-skills 最近一次提交是", elements[0]["content"])
        self.assertEqual(elements[2]["content"], "**📌 任务：查询 codex-skills 最近提交**")
        joined = "\n".join(element["content"] for element in elements if element["tag"] == "markdown")
        self.assertNotIn("subagent task completed:", joined)
        self.assertNotIn("summary:", joined)

    def test_render_final_reply_card_strips_subagent_completion_followup_suggestions(self) -> None:
        card = render_final_reply_card(
            "subagent task completed: 查询 codex-skills 最近提交\n"
            "summary: tiezhuli001/codex-skills 最近一次提交是 **2026-04-17 17:55:00**（北京时间），"
            "commit 信息为 `Merge pull request #2`。\n\n"
            "如果你要，我也可以继续帮你：\n"
            "转成北京时间\n"
            "再列出最近 5 次提交"
        )

        joined = "\n".join(element["content"] for element in card["body"]["elements"] if element["tag"] == "markdown")
        self.assertIn("最近一次提交是", joined)
        self.assertNotIn("如果你要", joined)
        self.assertNotIn("再列出最近 5 次提交", joined)

    def test_render_final_reply_card_structures_subagent_system_failure_message(self) -> None:
        card = render_final_reply_card(
            "subagent task failed: 查询 codex-skills 最近提交\n"
            "error: github mcp request timed out"
        )

        self.assertEqual(card["header"]["title"]["content"], "子任务失败")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "github mcp request timed out")
        self.assertEqual(elements[2]["content"], "**📌 任务：查询 codex-skills 最近提交**")

    def test_render_final_reply_card_structures_subagent_system_timeout_message(self) -> None:
        card = render_final_reply_card("subagent task timed out: 查询 codex-skills 最近提交")

        self.assertEqual(card["header"]["title"]["content"], "子任务超时")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**📌 任务：查询 codex-skills 最近提交**")

    def test_render_final_reply_card_structures_subagent_system_cancelled_message(self) -> None:
        card = render_final_reply_card("subagent task cancelled: 查询 codex-skills 最近提交")

        self.assertEqual(card["header"]["title"]["content"], "子任务已取消")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**📌 任务：查询 codex-skills 最近提交**")

    def test_render_final_reply_card_structures_background_task_failure_message(self) -> None:
        card = render_final_reply_card(
            "后台任务failed：调研 codex-skills 仓库能力\ngithub mcp request timed out"
        )

        self.assertEqual(card["header"]["title"]["content"], "后台任务失败")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "github mcp request timed out")
        self.assertEqual(elements[2]["content"], "**📌 任务：调研 codex-skills 仓库能力**")

    def test_render_final_reply_card_structures_background_task_timeout_message(self) -> None:
        card = render_final_reply_card("后台任务timed_out：调研 codex-skills 仓库能力")

        self.assertEqual(card["header"]["title"]["content"], "后台任务超时")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**📌 任务：调研 codex-skills 仓库能力**")

    def test_render_final_reply_card_structures_background_task_cancelled_message(self) -> None:
        card = render_final_reply_card("后台任务cancelled：调研 codex-skills 仓库能力")

        self.assertEqual(card["header"]["title"]["content"], "后台任务已取消")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**📌 任务：调研 codex-skills 仓库能力**")

    def test_render_final_reply_card_uses_default_title_for_short_literal_reply(self) -> None:
        card = render_final_reply_card("main")

        self.assertEqual(card["header"]["title"]["content"], "处理结果")
        self.assertEqual(card["body"]["elements"][0]["content"], "main")

    def test_render_final_reply_card_derives_time_title_for_timezone_prefixed_time_reply(self) -> None:
        card = render_final_reply_card("现在是Asia/Shanghai 2026年4月8日 14:07")

        self.assertEqual(card["header"]["title"]["content"], "当前时间")

    def test_delivery_final_rendering_delegates_to_generic_renderer(self) -> None:
        captured: list[tuple[str, dict[str, str], dict]] = []

        def fake_post(url: str, headers: dict[str, str], body: dict) -> dict:
            captured.append((url, headers, body))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
            return {"code": 0, "data": {"message_id": "om_message_delegate"}}

        client = FeishuDeliveryClient(
            env={"FEISHU_APP_ID": "app-id", "FEISHU_APP_SECRET": "app-secret"},
            transport=fake_post,
        )
        payload = FeishuDeliveryPayload(
            chat_id="chat_delegate_1",
            event_type="final",
            event_id="evt_delegate_1",
            run_id="run_delegate_1",
            trace_id="trace_delegate_1",
            sequence=1,
            text="委托测试",
        )

        with patch(
            "marten_runtime.channels.feishu.delivery.feishu_rendering.render_final_reply_card",
            return_value={"config": {"wide_screen_mode": True}, "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "delegated"}}]},
        ) as render_mock:
            client.send(payload)

        render_mock.assert_called_once_with("委托测试", event_type="final")
        card = json.loads(captured[1][2]["content"])
        self.assertEqual(card["elements"][0]["text"]["content"], "delegated")




if __name__ == "__main__":
    unittest.main()
