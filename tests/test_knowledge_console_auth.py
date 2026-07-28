from __future__ import annotations

import re
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.knowledge_console import _ConsoleSessionCodec
from tests.http_app_support import build_test_app


TOKEN = "operator-test-token"


class KnowledgeConsoleAuthTests(unittest.TestCase):
    def test_console_is_absent_without_operator_token(self) -> None:
        response = TestClient(build_test_app()).get("/knowledge/console")

        self.assertEqual(response.status_code, 404)

    def test_invalid_login_never_calls_knowledge_service(self) -> None:
        app = build_test_app(env_overrides={"KNOWLEDGE_OPERATOR_TOKEN": TOKEN})
        app.state.runtime.knowledge_service.store.list_namespace_summaries = Mock(
            side_effect=AssertionError("service called")
        )

        response = TestClient(app).post(
            "/knowledge/console/login",
            data={"token": "wrong"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("Operator token 无效", response.text)
        self.assertNotIn(TOKEN, response.text)
        app.state.runtime.knowledge_service.store.list_namespace_summaries.assert_not_called()

    def test_valid_login_uses_short_lived_http_only_cookie_and_csrf(self) -> None:
        app = build_test_app(env_overrides={"KNOWLEDGE_OPERATOR_TOKEN": TOKEN})
        client = TestClient(app)

        login = client.post(
            "/knowledge/console/login",
            data={"token": TOKEN},
            follow_redirects=False,
        )
        home = client.get("/knowledge/console")

        self.assertEqual(login.status_code, 303)
        cookie = login.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Max-Age=1800", cookie)
        self.assertNotIn(TOKEN, cookie)
        self.assertEqual(home.status_code, 200, home.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', home.text)
        self.assertIsNotNone(csrf)
        rejected = client.post("/knowledge/console/logout", data={"csrf_token": "wrong"})
        self.assertEqual(rejected.status_code, 403)
        self.assertIn("KNOWLEDGE_CONSOLE_CSRF_INVALID", rejected.text)

    def test_signed_session_rejects_tampering_and_expiry(self) -> None:
        codec = _ConsoleSessionCodec(TOKEN, ttl_seconds=60)
        with patch("marten_runtime.interfaces.http.knowledge_console.time.time", return_value=1_000):
            value, session = codec.create()
        self.assertEqual(codec.read(f"{value}x"), None)
        with patch("marten_runtime.interfaces.http.knowledge_console.time.time", return_value=1_061):
            self.assertIsNone(codec.read(value))
        self.assertTrue(session.csrf_token)


if __name__ == "__main__":
    unittest.main()
