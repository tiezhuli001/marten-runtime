import unittest

from marten_runtime.automation.store import AutomationStore
from marten_runtime.tools.builtins.list_automations_tool import run_list_automations_tool
from marten_runtime.tools.builtins.pause_automation_tool import run_pause_automation_tool
from marten_runtime.tools.builtins.resume_automation_tool import run_resume_automation_tool
from marten_runtime.tools.builtins.register_automation_tool import run_register_automation_tool
from marten_runtime.tools.builtins.time_tool import run_time_tool
from marten_runtime.tools.builtins.delete_automation_tool import run_delete_automation_tool
from marten_runtime.tools.builtins.update_automation_tool import run_update_automation_tool
from marten_runtime.tools.registry import ToolRegistry


class ToolTests(unittest.TestCase):
    def test_registry_lists_and_calls_time_tool(self) -> None:
        registry = ToolRegistry()
        registry.register("time", run_time_tool)

        result = registry.call("time", {"timezone": "UTC"})

        self.assertEqual(registry.list(), ["time"])
        self.assertEqual(result["timezone"], "UTC")
        self.assertIn("iso_time", result)

    def test_register_automation_tool_saves_daily_job(self) -> None:
        store = AutomationStore()
        registry = ToolRegistry()
        registry.register(
            "register_automation",
            lambda payload: run_register_automation_tool(payload, store),
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
                "skill_id": "github_hot_repos_digest",
            },
        )

        enabled = store.list_enabled()

        self.assertTrue(result["ok"])
        self.assertEqual(result["automation_id"], "daily_hot")
        self.assertIn("semantic_fingerprint", result)
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].schedule_expr, "09:30")
        self.assertEqual(enabled[0].delivery_target, "oc_test_chat")

    def test_list_automations_tool_returns_enabled_jobs(self) -> None:
        store = AutomationStore()
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
                "skill_id": "github_hot_repos_digest",
            },
            store,
        )

        result = run_list_automations_tool({"delivery_channel": "feishu"}, store)

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["automation_id"], "daily_hot")

    def test_update_pause_resume_and_delete_automation_tools(self) -> None:
        store = AutomationStore()
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
                "skill_id": "github_hot_repos_digest",
            },
            store,
        )

        updated = run_update_automation_tool(
            {
                "automation_id": "daily_hot",
                "name": "GitHub每日热榜Top10",
                "schedule_expr": "23:50",
            },
            store,
        )
        paused = run_pause_automation_tool({"automation_id": "daily_hot"}, store)
        listed = run_list_automations_tool({"include_disabled": True}, store)
        resumed = run_resume_automation_tool({"automation_id": "daily_hot"}, store)
        deleted = run_delete_automation_tool({"automation_id": "daily_hot"}, store)

        self.assertTrue(updated["ok"])
        self.assertEqual(updated["automation"]["schedule_expr"], "23:50")
        self.assertFalse(paused["automation"]["enabled"])
        self.assertEqual(listed["count"], 1)
        self.assertFalse(listed["items"][0]["enabled"])
        self.assertTrue(resumed["automation"]["enabled"])
        self.assertTrue(deleted["ok"])
        self.assertEqual(store.list_all(), [])


if __name__ == "__main__":
    unittest.main()
