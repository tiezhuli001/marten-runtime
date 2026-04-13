import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.automation.store import AutomationStore
from marten_runtime.interfaces.http.bootstrap_runtime_support import (
    ensure_self_improve_automation,
    has_feishu_credentials,
)


class BootstrapRuntimeSupportTests(unittest.TestCase):
    def test_ensure_self_improve_automation_is_present_and_idempotent(self) -> None:
        store = AutomationStore()

        ensure_self_improve_automation(store)
        first = store.get("self_improve_internal")
        ensure_self_improve_automation(store)
        second = store.get("self_improve_internal")

        self.assertEqual(first.automation_id, "self_improve_internal")
        self.assertTrue(first.internal)
        self.assertEqual(second.semantic_fingerprint, first.semantic_fingerprint)
        self.assertEqual(len(store.list_all()), 1)

    def test_has_feishu_credentials_requires_both_app_id_and_secret(self) -> None:
        self.assertFalse(has_feishu_credentials({}))
        self.assertFalse(has_feishu_credentials({"FEISHU_APP_ID": "app_only"}))
        self.assertTrue(
            has_feishu_credentials(
                {
                    "FEISHU_APP_ID": "app_id",
                    "FEISHU_APP_SECRET": "app_secret",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
