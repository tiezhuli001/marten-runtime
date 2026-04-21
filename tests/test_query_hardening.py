import unittest

from marten_runtime.runtime.query_hardening import (
    extract_github_repo_query,
    is_automation_list_query,
    is_github_repo_commit_query,
    is_github_repo_metadata_query,
    is_explicit_multi_step_tool_request,
    is_runtime_context_query,
    is_session_catalog_query,
    is_session_switch_query,
    is_time_query,
)


class QueryHardeningTests(unittest.TestCase):
    def test_runtime_context_query_detects_natural_language_detail_request(self) -> None:
        self.assertTrue(is_runtime_context_query("当前上下文的具体使用详情是什么？"))

    def test_extract_github_repo_query_from_repo_url(self) -> None:
        message = "请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？"
        self.assertEqual(extract_github_repo_query(message), "CloudWide851/easy-agent")

    def test_commit_query_is_not_treated_as_metadata_query(self) -> None:
        message = "请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库最近一次提交是什么时候？"
        self.assertTrue(is_github_repo_commit_query(message))
        self.assertFalse(is_github_repo_metadata_query(message))

    def test_metadata_query_detects_repo_metadata_request(self) -> None:
        message = "请用 github mcp 查看 https://github.com/CloudWide851/easy-agent 这个仓库的默认分支和描述。"
        self.assertFalse(is_github_repo_commit_query(message))
        self.assertTrue(is_github_repo_metadata_query(message))

    def test_time_query_detects_realtime_time_prompt(self) -> None:
        self.assertTrue(is_time_query("请告诉我现在几点了？"))

    def test_multi_step_tool_request_detects_natural_language_runtime_then_mcp_sequence(
        self,
    ) -> None:
        self.assertTrue(
            is_explicit_multi_step_tool_request(
                "先看当前时间，再检查上下文占用，最后列出可用 MCP 服务。"
            )
        )

    def test_multi_step_tool_request_does_not_mistake_runtime_then_summary_as_cross_tool_sequence(
        self,
    ) -> None:
        self.assertFalse(
            is_explicit_multi_step_tool_request(
                "先看当前上下文占用，再总结这次工具调用情况。"
            )
        )

    def test_multi_step_tool_request_does_not_mistake_runtime_then_repo_explanation_as_cross_tool_sequence(
        self,
    ) -> None:
        self.assertFalse(
            is_explicit_multi_step_tool_request(
                "先看当前上下文占用，再说明这个仓库上下文是否需要压缩。"
            )
        )

    def test_session_catalog_query_detects_active_list_wording(self) -> None:
        self.assertTrue(is_session_catalog_query("当前有哪些活跃列表？"))
        self.assertTrue(is_session_catalog_query("当前有哪些会话列表？"))

    def test_automation_list_query_requires_automation_wording(self) -> None:
        self.assertTrue(is_automation_list_query("当前有哪些定时任务？"))
        self.assertFalse(is_automation_list_query("当前有哪些活跃列表？"))

    def test_session_switch_query_detects_new_session_wording(self) -> None:
        self.assertTrue(is_session_switch_query("切换到新会话"))
        self.assertTrue(is_session_switch_query("新开一个会话"))
        self.assertTrue(is_session_switch_query("start a new session"))

    def test_session_switch_query_detects_resume_wording(self) -> None:
        self.assertTrue(is_session_switch_query("恢复之前的会话"))
        self.assertTrue(is_session_switch_query("resume session sess_123"))
