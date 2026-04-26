import unittest

from marten_runtime.channels.feishu.rendering import FeishuCardProtocol, FeishuCardSection
from marten_runtime.channels.feishu.rendering_support import (
    dedupe_visible_text_against_protocol,
    derive_plain_title,
    render_section_item,
    strip_protocol_shell_residue,
    strip_visible_markdown_table_blocks,
)


class FeishuRenderingSupportTests(unittest.TestCase):
    def test_derive_plain_title_detects_commit_title(self) -> None:
        self.assertEqual(
            derive_plain_title('owner/repo 最近提交如下：', event_type='final'),
            'owner/repo 最近提交',
        )

    def test_derive_plain_title_detects_same_session_resume_noop_heading(self) -> None:
        self.assertEqual(
            derive_plain_title('当前已在会话 `sess_dcce8f9c`', event_type='final'),
            '当前已在会话 `sess_dcce8f9c`',
        )

    def test_strip_visible_markdown_table_blocks_removes_table_only(self) -> None:
        text = '今日 GitHub 热榜：\n\n| 排名 | 仓库 |\n| --- | --- |\n| 1 | foo/bar |\n\n继续关注。'
        self.assertEqual(strip_visible_markdown_table_blocks(text), '今日 GitHub 热榜：\n\n继续关注。')

    def test_dedupe_visible_text_against_protocol_removes_duplicate_bullets(self) -> None:
        protocol = FeishuCardProtocol(sections=[FeishuCardSection(items=['A', 'B'])])
        text = '当前结果：\n- A\n- B\n\n已完成。'
        self.assertEqual(dedupe_visible_text_against_protocol(text, protocol), '当前结果：\n\n已完成。')

    def test_render_section_item_preserves_existing_marker(self) -> None:
        self.assertEqual(render_section_item('1. first'), '1. first')
        self.assertEqual(render_section_item('foo'), '- foo')

    def test_strip_protocol_shell_residue_removes_trailing_shell_lines_only(self) -> None:
        text = '处理完成。\n\n```\n</invoke>\n</minimax:tool_call>'
        self.assertEqual(
            strip_protocol_shell_residue(text, protocol_context=True),
            '处理完成。',
        )

    def test_strip_protocol_shell_residue_keeps_regular_markdown_code_block(self) -> None:
        text = '示例：\n```python\nprint("hello")\n```'
        self.assertEqual(
            strip_protocol_shell_residue(text, protocol_context=True),
            text,
        )

    def test_strip_protocol_shell_residue_keeps_plain_xml_like_trailing_line_without_protocol_context(
        self,
    ) -> None:
        text = 'XML 示例：\n</invoke>'
        self.assertEqual(strip_protocol_shell_residue(text), text)


if __name__ == '__main__':
    unittest.main()
