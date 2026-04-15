import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class InitScriptTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.init_script_source = self.repo_root / "init.sh"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.temp_dir.name)
        self.init_script = self.workdir / "init.sh"
        self.log_path = self.workdir / "commands.log"
        self.server_script = self.workdir / "fake_runtime_server.py"
        self._write_workspace_files()
        self._write_fake_server()
        self._write_fake_python_launcher()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_init_bootstraps_templates_prints_start_command_and_runs_smoke(self) -> None:
        result = self._run_init(
            extra_env={
                "OPENAI_API_KEY": "test-openai-key",
                "INIT_TEST_SERVER_SCRIPT": str(self.server_script),
            }
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue((self.workdir / ".env").exists())
        self.assertTrue((self.workdir / "mcps.json").exists())
        self.assertIn("source .venv/bin/activate", result.stdout)
        self.assertIn("PYTHONPATH=src python -m marten_runtime.interfaces.http.serve", result.stdout)
        self.assertIn("OK  /healthz", result.stdout)
        self.assertIn("OK  /readyz", result.stdout)
        self.assertIn("OK  /diagnostics/runtime", result.stdout)
        log_text = self.log_path.read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements.txt", log_text)
        self.assertIn("pip install -e .", log_text)

    def test_init_preserves_existing_files_and_blocks_when_provider_missing(self) -> None:
        env_path = self.workdir / ".env"
        env_path.write_text("DATABASE_URL=sqlite:///./data/runtime.db\n", encoding="utf-8")
        mcps_path = self.workdir / "mcps.json"
        mcps_path.write_text('{"servers": {}}\n', encoding="utf-8")

        result = self._run_init(extra_env={"OPENAI_API_KEY": "", "MINIMAX_API_KEY": ""})

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(env_path.read_text(encoding="utf-8"), "DATABASE_URL=sqlite:///./data/runtime.db\n")
        self.assertEqual(mcps_path.read_text(encoding="utf-8"), '{"servers": {}}\n')
        self.assertIn("BLOCKED", result.stdout)
        self.assertIn("provider", result.stdout.lower())
        self.assertNotIn("/healthz", result.stdout)

    def test_init_fails_when_smoke_endpoint_check_fails(self) -> None:
        result = self._run_init(
            extra_env={
                "OPENAI_API_KEY": "test-openai-key",
                "INIT_TEST_SERVER_SCRIPT": str(self.server_script),
                "INIT_TEST_SERVER_MODE": "broken_readyz",
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED", result.stdout)
        self.assertIn("/readyz", result.stdout)

    def test_init_skip_install_skips_pip_but_still_runs_smoke(self) -> None:
        result = self._run_init(
            args=["--skip-install"],
            extra_env={
                "OPENAI_API_KEY": "test-openai-key",
                "INIT_TEST_SERVER_SCRIPT": str(self.server_script),
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("OK  skipped dependency installation", result.stdout)
        self.assertIn("OK  /diagnostics/runtime", result.stdout)
        log_text = self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""
        self.assertNotIn("pip install --upgrade pip", log_text)
        self.assertNotIn("pip install -r requirements.txt", log_text)
        self.assertNotIn("pip install -e .", log_text)

    def test_init_smoke_only_reuses_existing_workspace_without_install_or_copy(self) -> None:
        self._create_fake_venv()
        env_path = self.workdir / ".env"
        env_path.write_text("OPENAI_API_KEY=from-env-file\n", encoding="utf-8")
        mcps_path = self.workdir / "mcps.json"
        mcps_path.write_text('{"servers": {}}\n', encoding="utf-8")

        result = self._run_init(
            args=["--smoke-only"],
            extra_env={
                "OPENAI_API_KEY": "",
                "MINIMAX_API_KEY": "",
                "INIT_TEST_SERVER_SCRIPT": str(self.server_script),
            },
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("OK  smoke-only mode: skipped bootstrap and install steps", result.stdout)
        self.assertIn("OK  /healthz", result.stdout)
        self.assertEqual(env_path.read_text(encoding="utf-8"), "OPENAI_API_KEY=from-env-file\n")
        self.assertEqual(mcps_path.read_text(encoding="utf-8"), '{"servers": {}}\n')
        log_text = self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""
        self.assertEqual(log_text, "")

    def test_init_smoke_only_blocks_when_venv_missing(self) -> None:
        result = self._run_init(
            args=["--smoke-only"],
            extra_env={
                "OPENAI_API_KEY": "test-openai-key",
                "INIT_TEST_SERVER_SCRIPT": str(self.server_script),
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED", result.stdout)
        self.assertIn(".venv", result.stdout)

    def _run_init(
        self, *, extra_env: dict[str, str], args: list[str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.workdir / 'fake-bin'}:{env.get('PATH', '')}",
                "HOME": str(self.workdir),
                "INIT_TEST_LOG": str(self.log_path),
                "INIT_SMOKE_PORT": str(self._find_free_port()),
            }
        )
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(self.init_script), *(args or [])],
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
        )

    def _write_workspace_files(self) -> None:
        shutil.copy2(self.repo_root / ".env.example", self.workdir / ".env.example")
        shutil.copy2(self.repo_root / "mcps.example.json", self.workdir / "mcps.example.json")
        shutil.copy2(self.repo_root / "requirements.txt", self.workdir / "requirements.txt")
        shutil.copy2(self.repo_root / "pyproject.toml", self.workdir / "pyproject.toml")
        if self.init_script_source.exists():
            shutil.copy2(self.init_script_source, self.init_script)
            self.init_script.chmod(self.init_script.stat().st_mode | stat.S_IEXEC)
        (self.workdir / "src").mkdir()

    def _create_fake_venv(self) -> None:
        subprocess.run(
            ["python3", "-m", "venv", str(self.workdir / ".venv")],
            cwd=self.workdir,
            env={
                **os.environ,
                "PATH": f"{self.workdir / 'fake-bin'}:{os.environ.get('PATH', '')}",
                "INIT_TEST_LOG": str(self.log_path),
                "INIT_TEST_SERVER_SCRIPT": str(self.server_script),
            },
            check=True,
            capture_output=True,
            text=True,
        )

    def _write_fake_server(self) -> None:
        self.server_script.write_text(
            textwrap.dedent(
                """
                import json
                import os
                from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

                port = int(os.environ["SERVER_PORT"])
                mode = os.environ.get("INIT_TEST_SERVER_MODE", "ok")

                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        if self.path == "/healthz":
                            self._json(200, {"status": "ok"})
                            return
                        if self.path == "/readyz":
                            payload = {"status": "ready" if mode != "broken_readyz" else "blocked"}
                            code = 200 if mode != "broken_readyz" else 503
                            self._json(code, payload)
                            return
                        if self.path == "/diagnostics/runtime":
                            self._json(200, {"app_id": "main_agent", "llm_profile": "default"})
                            return
                        self._json(404, {"detail": "not found"})

                    def log_message(self, format, *args):
                        return

                    def _json(self, code, payload):
                        body = json.dumps(payload).encode("utf-8")
                        self.send_response(code)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

    def _write_fake_python_launcher(self) -> None:
        fake_bin = self.workdir / "fake-bin"
        fake_bin.mkdir()
        real_python = sys.executable
        python3_path = fake_bin / "python3"
        python3_path.write_text(
            (
                f"""#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ge 3 && "$1" == "-m" && "$2" == "venv" ]]; then
  target="$3"
  mkdir -p "$target/bin"
  cat > "$target/bin/python" <<'PYEOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$#" -ge 2 && "$1" == "-m" && "$2" == "pip" ]]; then
  echo "pip ${{*:3}}" >> "${{INIT_TEST_LOG:?}}"
  exit 0
fi
if [[ "$#" -ge 2 && "$1" == "-m" && "$2" == "marten_runtime.interfaces.http.serve" ]]; then
  exec "{real_python}" "${{INIT_TEST_SERVER_SCRIPT:?}}"
fi
exec "{real_python}" "$@"
PYEOF
  chmod +x "$target/bin/python"
  exit 0
fi
exec "{real_python}" "$@"
"""
            ),
            encoding="utf-8",
        )
        python3_path.chmod(python3_path.stat().st_mode | stat.S_IEXEC)

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
