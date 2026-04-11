import unittest
from unittest.mock import Mock

from tests.http_app_support import build_test_app
from marten_runtime.interfaces.http.runtime_diagnostics import (
    resolve_runtime_server_surface,
    serialize_runtime_diagnostics,
)


class HTTPRuntimeDiagnosticsTests(unittest.TestCase):
    def test_resolve_runtime_server_surface_prefers_request_base_url(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        request = Mock()
        request.base_url = "https://example.com/runtime/"

        surface = resolve_runtime_server_surface(runtime, request)

        self.assertEqual(surface["host"], "example.com")
        self.assertEqual(surface["port"], 443)
        self.assertEqual(surface["public_base_url"], "https://example.com/runtime")
        self.assertEqual(surface["configured_host"], runtime.platform_config.server.host)

    def test_serialize_runtime_diagnostics_preserves_server_and_channel_fields(self) -> None:
        app = build_test_app()
        runtime = app.state.runtime
        request = Mock()
        request.base_url = "http://127.0.0.1:9000/"

        body = serialize_runtime_diagnostics(runtime, request)

        self.assertEqual(body["app_id"], runtime.app_manifest.app_id)
        self.assertEqual(body["server"]["host"], "127.0.0.1")
        self.assertEqual(body["server"]["port"], 9000)
        self.assertIn("feishu", body["channels"])
        self.assertIn("provider_retry_policy", body)
        self.assertEqual(body["tool_count"], len(runtime.tool_registry.list()))


if __name__ == "__main__":
    unittest.main()
