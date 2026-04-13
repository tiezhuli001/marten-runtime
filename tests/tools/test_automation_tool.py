import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.tools.builtins.automation_tool import (
    render_automation_tool_text,
    run_automation_tool,
    run_delete_automation_tool,
    run_get_automation_detail_tool,
    run_list_automations_tool,
    run_pause_automation_tool,
    run_register_automation_tool,
    run_resume_automation_tool,
    run_update_automation_tool,
)
from marten_runtime.tools.registry import ToolRegistry
from tests.support.domain_builders import build_automation_adapter


class AutomationToolTests(unittest.TestCase):

    def _build_adapter(
        self, tmpdir: str
    ) -> tuple[DomainDataAdapter, SQLiteAutomationStore]:
        return build_automation_adapter(Path(tmpdir))

    def test_render_automation_tool_text_formats_list_result(self) -> None:
        text = render_automation_tool_text(
            {
                "action": "list",
                "count": 2,
                "items": [
                    {
                        "automation_id": "job_1",
                        "name": "早报",
                        "schedule_expr": "08:00",
                        "enabled": True,
                    },
                    {
                        "automation_id": "job_2",
                        "name": "晚报",
                        "schedule_expr": "20:00",
                        "enabled": False,
                    },
                ],
            }
        )

        self.assertIn("当前共有 2 个定时任务", text)
        self.assertNotIn("📌 共", text)
        self.assertNotIn("📁 详情", text)
        self.assertIn("- 早报｜已启用｜08:00", text)
        self.assertIn("- 晚报｜已暂停｜20:00", text)

    def test_render_automation_tool_text_formats_detail_result(self) -> None:
        text = render_automation_tool_text(
            {
                "action": "detail",
                "automation": {
                    "automation_id": "github_trending_digest_2230",
                    "name": "GitHub热榜推荐",
                    "schedule_kind": "daily",
                    "schedule_expr": "22:30",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                    "delivery_channel": "feishu",
                    "delivery_target": "chat_1",
                    "skill_id": "github_trending_digest",
                },
            }
        )

        self.assertIn("定时任务 GitHub热榜推荐 的当前配置如下", text)
        self.assertIn("automation_id：github_trending_digest_2230", text)
        self.assertIn("状态：已启用", text)
        self.assertIn("调度：daily 22:30", text)
        self.assertIn("时区：Asia/Shanghai", text)

    def test_render_automation_tool_text_formats_register_result(self) -> None:
        text = render_automation_tool_text(
            {
                "action": "register",
                "ok": True,
                "automation_id": "daily_hot",
                "name": "Daily GitHub Hot Repos",
                "schedule_kind": "daily",
                "schedule_expr": "09:30",
                "timezone": "Asia/Shanghai",
                "enabled": True,
                "skill_id": "github_trending_digest",
            }
        )

        self.assertIn("已创建定时任务 Daily GitHub Hot Repos", text)
        self.assertIn("automation_id：daily_hot", text)
        self.assertIn("调度：daily 09:30", text)
        self.assertIn("状态：已启用", text)

    def test_render_automation_tool_text_formats_pause_resume_update_delete_results(self) -> None:
        pause_text = render_automation_tool_text(
            {
                "action": "pause",
                "ok": True,
                "automation": {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "enabled": False,
                },
            }
        )
        resume_text = render_automation_tool_text(
            {
                "action": "resume",
                "ok": True,
                "automation": {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                },
            }
        )
        update_text = render_automation_tool_text(
            {
                "action": "update",
                "ok": True,
                "automation": {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "schedule_kind": "daily",
                    "schedule_expr": "10:00",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                },
            }
        )
        delete_text = render_automation_tool_text(
            {
                "action": "delete",
                "ok": True,
                "automation_id": "daily_hot",
            }
        )

        self.assertIn("已暂停定时任务 Daily GitHub Hot Repos", pause_text)
        self.assertIn("状态：已暂停", pause_text)
        self.assertIn("已恢复定时任务 Daily GitHub Hot Repos", resume_text)
        self.assertIn("状态：已启用", resume_text)
        self.assertIn("已更新定时任务 Daily GitHub Hot Repos", update_text)
        self.assertIn("调度：daily 10:00", update_text)
        self.assertIn("已删除定时任务 daily_hot", delete_text)

    def test_register_automation_tool_saves_daily_job(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            registry = ToolRegistry()
            registry.register(
                "register_automation",
                lambda payload: run_register_automation_tool(payload, store, adapter),
            )

            result = registry.call(
                "register_automation",
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
            )

            enabled = store.list_enabled()

            self.assertTrue(result["ok"])
            self.assertEqual(result["automation_id"], "daily_hot")
            self.assertEqual(result["name"], "Daily GitHub Hot Repos")
            self.assertEqual(result["schedule_text"], "每天 09:30")
            self.assertIn("semantic_fingerprint", result)
            self.assertEqual(len(enabled), 1)
            self.assertEqual(enabled[0].schedule_expr, "09:30")
            self.assertEqual(enabled[0].delivery_target, "oc_test_chat")

    def test_list_automations_tool_returns_public_jobs_via_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.save(
                AutomationJob(
                    automation_id="self_improve_internal",
                    name="Internal Self Improve",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize failures.",
                    schedule_kind="daily",
                    schedule_expr="03:00",
                    timezone="UTC",
                    session_target="isolated",
                    delivery_channel="http",
                    delivery_target="internal",
                    skill_id="self_improve",
                    enabled=True,
                    internal=True,
                )
            )

            result = run_list_automations_tool({"delivery_channel": "feishu"}, adapter)

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["automation_id"], "daily_hot")
        self.assertEqual(result["items"][0]["name"], "Daily GitHub Hot Repos")
        self.assertEqual(result["items"][0]["schedule_text"], "每天 09:30")
        self.assertNotIn("delivery_target", result["items"][0])

    def test_automation_family_tool_defaults_empty_payload_to_list_for_read_queries(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )

            result = run_automation_tool({}, store, adapter)

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "list")
        self.assertEqual(result["count"], 1)
        self.assertNotIn("delivery_channel", result["items"][0])

    def test_list_automations_tool_can_include_disabled_public_jobs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.set_enabled("daily_hot", False)

            default_result = run_list_automations_tool({}, adapter)
            disabled_result = run_list_automations_tool(
                {"include_disabled": True}, adapter
            )

        self.assertEqual(default_result["count"], 0)
        self.assertEqual(disabled_result["count"], 1)
        self.assertFalse(disabled_result["items"][0]["enabled"])

    def test_get_automation_detail_tool_returns_public_job_and_hides_internal(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.save(
                AutomationJob(
                    automation_id="self_improve_internal",
                    name="Internal Self Improve",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize failures.",
                    schedule_kind="daily",
                    schedule_expr="03:00",
                    timezone="UTC",
                    session_target="isolated",
                    delivery_channel="http",
                    delivery_target="internal",
                    skill_id="self_improve",
                    enabled=True,
                    internal=True,
                )
            )

            detail = run_get_automation_detail_tool(
                {"automation_id": "daily_hot"}, adapter
            )

            with self.assertRaises(KeyError):
                run_get_automation_detail_tool(
                    {"automation_id": "self_improve_internal"}, adapter
                )
            with self.assertRaises(KeyError):
                run_get_automation_detail_tool({"automation_id": "missing"}, adapter)

        self.assertTrue(detail["ok"])
        self.assertEqual(detail["automation"]["automation_id"], "daily_hot")

    def test_delete_automation_tool_returns_not_found_for_internal_jobs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            store.save(
                AutomationJob(
                    automation_id="self_improve_internal",
                    name="Internal Self Improve",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize failures.",
                    schedule_kind="daily",
                    schedule_expr="03:00",
                    timezone="UTC",
                    session_target="isolated",
                    delivery_channel="http",
                    delivery_target="internal",
                    skill_id="self_improve",
                    enabled=True,
                    internal=True,
                )
            )

            deleted = run_delete_automation_tool(
                {"automation_id": "self_improve_internal"}, adapter
            )

        self.assertEqual(deleted, {"ok": False, "automation_id": "self_improve_internal"})

    def test_update_pause_resume_and_delete_automation_tools(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )

            updated = run_update_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "GitHub每日热榜Top10",
                    "schedule_expr": "23:50",
                },
                adapter,
            )
            paused = run_pause_automation_tool({"automation_id": "daily_hot"}, adapter)
            listed = run_list_automations_tool({"include_disabled": True}, adapter)
            resumed = run_resume_automation_tool(
                {"automation_id": "daily_hot"}, adapter
            )
            deleted = run_delete_automation_tool(
                {"automation_id": "daily_hot"}, adapter
            )

            self.assertTrue(updated["ok"])
            self.assertEqual(updated["automation"]["schedule_expr"], "23:50")
            self.assertFalse(paused["automation"]["enabled"])
            self.assertEqual(listed["count"], 1)
            self.assertFalse(listed["items"][0]["enabled"])
            self.assertTrue(resumed["automation"]["enabled"])
            self.assertTrue(deleted["ok"])
            self.assertEqual(store.list_all(), [])

    def test_automation_family_tool_list_includes_paused_jobs_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.set_enabled("daily_hot", False)

            listed = run_automation_tool({"action": "list"}, store, adapter)

        self.assertEqual(listed["action"], "list")
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["count"], 1)
        self.assertFalse(listed["items"][0]["enabled"])
