import unittest

from marten_runtime.runtime.query_hardening import (
    extract_github_repo_query,
    is_github_repo_commit_query,
    is_github_repo_metadata_query,
    is_runtime_context_query,
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
