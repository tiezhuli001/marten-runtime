import unittest

from marten_runtime.tools.builtins.automation_view import (
    present_automation,
    sort_presented_automations,
)


class AutomationViewTests(unittest.TestCase):
    def test_present_automation_normalizes_legacy_skill_named_job_for_display(self) -> None:
        presented = present_automation(
            {
                "automation_id": "github_trending_digest_0102",
                "name": "github_trending_digest_0102",
                "schedule_kind": "daily",
                "schedule_expr": "0 10 21 * * *",
                "timezone": "Asia/Shanghai",
                "skill_id": "github_trending_digest",
                "enabled": True,
            }
        )

        self.assertEqual(presented["automation_id"], "github_trending_digest_0102")
        self.assertEqual(presented["name"], "GitHub热榜推荐")
        self.assertEqual(presented["schedule_expr"], "21:10")
        self.assertEqual(presented["schedule_text"], "每天 21:10")

    def test_present_automation_normalizes_canonical_and_default_github_names(self) -> None:
        canonical = present_automation(
            {
                "automation_id": "github_trending_digest_0102",
                "name": "github_trending_digest_0102",
                "schedule_kind": "daily",
                "schedule_expr": "09:30",
                "timezone": "Asia/Shanghai",
                "skill_id": "github_trending_digest",
                "enabled": True,
            }
        )
        legacy_default = present_automation(
            {
                "automation_id": "github_digest_daily",
                "name": "GitHub热榜推荐",
                "schedule_kind": "daily",
                "schedule_expr": "23:30",
                "timezone": "Asia/Shanghai",
                "skill_id": "github_trending_digest",
                "enabled": False,
            }
        )

        self.assertEqual(canonical["name"], "GitHub热榜推荐")
        self.assertEqual(legacy_default["automation_id"], "github_digest_daily")
        self.assertEqual(legacy_default["name"], "GitHub热榜推荐")
        self.assertFalse(legacy_default["enabled"])

    def test_sort_presented_automations_sorts_by_normalized_schedule_time(self) -> None:
        items = sort_presented_automations(
            [
                present_automation(
                    {
                        "automation_id": "job_2330",
                        "name": "GitHub热榜推荐",
                        "schedule_kind": "daily",
                        "schedule_expr": "23:30",
                        "timezone": "Asia/Shanghai",
                        "skill_id": "github_trending_digest",
                        "enabled": False,
                    }
                ),
                present_automation(
                    {
                        "automation_id": "job_2220",
                        "name": "github_trending_digest",
                        "schedule_kind": "daily",
                        "schedule_expr": "22:20",
                        "timezone": "Asia/Shanghai",
                        "skill_id": "github_trending_digest",
                        "enabled": True,
                    }
                ),
            ]
        )

        self.assertEqual([item["automation_id"] for item in items], ["job_2220", "job_2330"])
        self.assertEqual(items[0]["name"], "GitHub热榜推荐")
        self.assertEqual(items[0]["schedule_text"], "每天 22:20")


if __name__ == "__main__":
    unittest.main()
