import unittest

from fastapi.testclient import TestClient

from tests.http_app_support import build_test_app


class GoldenRuntimeTests(unittest.TestCase):
    def test_golden_message_sequences_cover_chat_and_mcp(self) -> None:
        with TestClient(build_test_app()) as client:
            chat = client.post(
                "/messages",
                json={"channel_id": "http", "user_id": "demo", "conversation_id": "golden-chat", "message_id": "1", "body": "hello"},
            ).json()
            mcp = client.post(
                "/messages",
                json={"channel_id": "http", "user_id": "demo", "conversation_id": "golden-mcp", "message_id": "2", "body": "search docs"},
            ).json()

        self.assertEqual([item["event_type"] for item in chat["events"]], ["progress", "final"])
        self.assertEqual([item["event_type"] for item in mcp["events"]], ["progress", "final"])


if __name__ == "__main__":
    unittest.main()
