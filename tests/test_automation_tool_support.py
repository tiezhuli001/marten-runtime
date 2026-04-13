import unittest

from marten_runtime.tools.builtins.automation_tool_support import (
    build_list_filters,
    build_registration_values,
    extract_update_values,
    normalize_registration_payload,
    normalize_schedule_input,
)


class AutomationToolSupportTests(unittest.TestCase):
    def test_normalize_schedule_input_is_owned_by_registration_boundary(self) -> None:
        self.assertEqual(normalize_schedule_input("cron", "0 10 21 * * *"), ("daily", "21:10"))
        self.assertEqual(normalize_schedule_input("", "", trigger_time="9:05"), ("daily", "09:05"))

    def test_normalize_registration_payload_resolves_aliases_and_defaults(self) -> None:
        normalized = normalize_registration_payload(
            {
                "task_name": "GitHub热榜推荐",
                "skill": "github_trending_digest",
                "app_id": "current_app",
                "agent_id": "current_agent",
                "schedule_kind": "cron",
                "schedule_expr": "0 10 21 * * *",
                "timezone": "Asia/Shanghai",
                "delivery_channel": "same_channel",
                "delivery_target": "current_conversation",
            },
            {
                "app_id": "example_assistant",
                "agent_id": "assistant",
                "channel_id": "feishu",
                "conversation_id": "oc_test_chat",
            },
        )

        self.assertEqual(normalized["name"], "GitHub热榜推荐")
        self.assertEqual(normalized["skill_id"], "github_trending_digest")
        self.assertEqual(normalized["app_id"], "example_assistant")
        self.assertEqual(normalized["agent_id"], "assistant")
        self.assertEqual(normalized["delivery_channel"], "feishu")
        self.assertEqual(normalized["delivery_target"], "oc_test_chat")
        self.assertEqual(normalized["schedule_kind"], "daily")
        self.assertEqual(normalized["schedule_expr"], "21:10")
        self.assertEqual(normalized["automation_id"], "github_trending_digest_2110")

    def test_build_registration_values_preserves_defaults_and_raw_skill_input(self) -> None:
        values = build_registration_values(
            {
                "automation_id": "daily_hot",
                "app_id": "example_assistant",
                "agent_id": "assistant",
                "schedule_kind": "daily",
                "schedule_expr": "09:30",
                "timezone": "Asia/Shanghai",
                "delivery_channel": "feishu",
                "delivery_target": "oc_test_chat",
                "skill_id": "  github_trending_digest  ",
            }
        )

        self.assertEqual(values["name"], "daily_hot")
        self.assertEqual(values["session_target"], "isolated")
        self.assertEqual(values["skill_id"], "  github_trending_digest  ")
        self.assertTrue(values["enabled"])

    def test_extract_update_values_and_list_filters_only_keep_supported_fields(self) -> None:
        updates = extract_update_values(
            {
                "name": "Daily GitHub Hot Repos",
                "skill_id": "  github_trending_digest  ",
                "enabled": False,
                "automation_id": "ignored",
            }
        )
        filters = build_list_filters(
            {
                "delivery_channel": "feishu",
                "delivery_target": "oc_test_chat",
                "include_disabled": True,
                "enabled": True,
            }
        )

        self.assertEqual(
            updates,
            {
                "name": "Daily GitHub Hot Repos",
                "skill_id": "  github_trending_digest  ",
            },
        )
        self.assertEqual(
            filters,
            {
                "delivery_channel": "feishu",
                "delivery_target": "oc_test_chat",
                "include_disabled": True,
                "enabled": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
