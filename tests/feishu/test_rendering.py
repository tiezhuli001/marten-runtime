import json
import unittest
from unittest.mock import patch

from marten_runtime.channels.feishu.delivery import FeishuDeliveryClient, FeishuDeliveryPayload
from marten_runtime.channels.feishu.rendering import (
    FeishuCardProtocol,
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
            "- 下一次请求预计输入：3673 tokens（tokenizer）\n"
            "- 本轮首发请求：3604 tokens；本轮 actual-peak：3280 tokens（输入 3198 + 输出 82，峰值主要来自工具结果注入后的 follow-up 模型调用）\n"
            "- 上一轮模型调用：模型输入：3198｜模型输出：82｜总计：3280"
        )

        self.assertEqual(card["header"]["title"]["content"], "当前上下文使用详情")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**🗂️ 详情**")
        self.assertIn("下一次请求预计输入", elements[1]["content"])

    def test_render_final_reply_card_uses_runtime_heading_when_actual_peak_is_unavailable(self) -> None:
        card = render_final_reply_card(
            "当前上下文使用详情\n"
            "- 下一次请求预计输入：3838 tokens（tokenizer）\n"
            "- 本轮 actual-peak：无（本轮未发生模型调用）\n"
            "- 本轮首发请求：3838 tokens；本轮峰值输入上下文：3838 tokens"
        )

        self.assertEqual(card["header"]["title"]["content"], "当前上下文使用详情")
        elements = card["body"]["elements"]
        self.assertEqual(elements[0]["content"], "**🗂️ 详情**")
        self.assertIn("本轮 actual-peak：无", elements[1]["content"])

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
            usage_summary={"input_tokens": 3198, "output_tokens": 82, "peak_tokens": 3280},
        )

        elements = card["body"]["elements"]
        self.assertEqual(elements[-2]["tag"], "hr")
        self.assertEqual(
            elements[-1]["content"],
            "<font color='grey'>本轮模型 token：输入 3198｜输出 82｜峰值 3280</font>",
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
