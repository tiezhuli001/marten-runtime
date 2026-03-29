import tempfile
import unittest
from pathlib import Path

from marten_runtime.config.platform_loader import load_platform_config
from marten_runtime.interfaces.http.serve import build_server_options


class PlatformConfigTests(unittest.TestCase):
    def test_loader_reads_platform_defaults_and_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "platform.toml"
            path.write_text(
                """
                [runtime]
                mode = "rewrite-first"

                [server]
                host = "0.0.0.0"
                port = 8000
                public_base_url = "http://127.0.0.1:8000"
                """,
                encoding="utf-8",
            )

            config = load_platform_config(
                str(path),
                env={
                    "SERVER_HOST": "127.0.0.1",
                    "SERVER_PORT": "9000",
                    "SERVER_PUBLIC_BASE_URL": "https://runtime.example.com",
                },
            )

            self.assertEqual(config.runtime.mode, "rewrite-first")
            self.assertEqual(config.server.host, "127.0.0.1")
            self.assertEqual(config.server.port, 9000)
            self.assertEqual(config.server.public_base_url, "https://runtime.example.com")

    def test_http_serve_builds_uvicorn_options_from_platform_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "platform.toml"
            path.write_text(
                """
                [runtime]
                mode = "rewrite-first"

                [server]
                host = "127.0.0.1"
                port = 8100
                public_base_url = "https://runtime.example.com"
                """,
                encoding="utf-8",
            )
            config = load_platform_config(str(path))

            options = build_server_options(config)

            self.assertEqual(options, {"host": "127.0.0.1", "port": 8100})

    def test_loader_falls_back_to_example_when_platform_toml_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "platform.toml"
            example = base / "platform.example.toml"
            example.write_text(
                """
                [runtime]
                mode = "rewrite-first"

                [server]
                host = "0.0.0.0"
                port = 8000
                public_base_url = "http://127.0.0.1:8000"
                """,
                encoding="utf-8",
            )

            config = load_platform_config(str(path))

            self.assertFalse(path.exists())
            self.assertEqual(config.runtime.mode, "rewrite-first")
            self.assertEqual(config.server.port, 8000)


if __name__ == "__main__":
    unittest.main()
