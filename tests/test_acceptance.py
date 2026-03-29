import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.bootstrap import build_http_runtime
from tests.http_app_support import build_test_app


class AcceptanceTests(unittest.TestCase):
    def test_repo_default_channel_template_keeps_feishu_disabled(self) -> None:
        runtime = build_http_runtime(env={}, load_env_file=False, use_compat_json=False)

        self.assertFalse(runtime.channels_config.feishu.enabled)
        self.assertFalse(runtime.channels_config.feishu.auto_start)

    def test_feishu_websocket_service_starts_with_app_when_channel_enabled(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        enabled_channels_config = runtime.channels_config.model_copy(
            update={
                "feishu": runtime.channels_config.feishu.model_copy(
                    update={"enabled": True, "connection_mode": "websocket", "auto_start": True}
                )
            }
        )

        runtime.channels_config = enabled_channels_config
        with patch.object(runtime.feishu_socket_service, "start_background", new=AsyncMock()) as start_mock:
            with patch.object(runtime.feishu_socket_service, "stop_background", new=AsyncMock()) as stop_mock:
                    with TestClient(app) as client:
                        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        start_mock.assert_awaited_once()
        stop_mock.assert_awaited_once()

    def test_chat_skill_mcp_memory_and_coding_paths_exist(self) -> None:
        with TestClient(build_test_app()) as client:
            chat = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-chat",
                    "message_id": "1",
                    "body": "hello",
                },
            )
            mcp = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-mcp",
                    "message_id": "2",
                    "body": "search release notes",
                },
            )
            coding = client.post(
                "/messages",
                json={
                    "channel_id": "http",
                    "user_id": "demo",
                    "conversation_id": "acc-coding",
                    "message_id": "3",
                    "body": "please fix bug in repo",
                },
            )

        self.assertEqual(chat.status_code, 200)
        self.assertEqual(mcp.status_code, 200)
        self.assertEqual(coding.status_code, 200)
        self.assertEqual(chat.json()["events"][-1]["event_type"], "final")
        self.assertIn("mock_search", mcp.json()["events"][-1]["payload"]["text"])
        self.assertEqual(coding.json()["events"][0]["event_type"], "progress")


if __name__ == "__main__":
    unittest.main()
