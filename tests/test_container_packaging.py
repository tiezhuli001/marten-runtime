from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.interfaces.http.container_self_check import run_container_self_check


REPO_ROOT = Path(__file__).resolve().parents[1]


class ContainerPackagingTests(unittest.TestCase):
    def test_container_self_check_verifies_bridge_timezone_and_knowledge_schema(self) -> None:
        with TemporaryDirectory() as tmpdir:
            result = run_container_self_check(
                repo_root=REPO_ROOT,
                env={},
                knowledge_db_path=Path(tmpdir) / "knowledge.sqlite3",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["node_major"], 22)
        self.assertEqual(result["engine"]["patchId"], "sect1-v1")
        self.assertEqual(result["historical_timezone"], "available")
        self.assertEqual(result["knowledge_schema"], "available")
        self.assertEqual(result["amap"]["reason"], "credential_missing")
        self.assertFalse(result["knowledge_operator"]["configured"])
        self.assertNotIn("AMAP_WEB_SERVICE_KEY", json.dumps(result))

    def test_docker_contract_pins_bases_and_bundles_supply_chain_artifacts(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        for marker in (
            "node:22-bookworm-slim@sha256:",
            "python:3.12-slim-bookworm@sha256:",
            "npm ci --omit=dev",
            "npm run verify:upstream",
            "npm run prepare:engine",
            "COPY tests/fixtures/bazi /tests/fixtures/bazi",
            "npm sbom --omit=dev --sbom-format cyclonedx",
            "node scripts/annotate-sbom.mjs",
            "torch==2.12.0",
            "sentence-transformers==5.5.0",
            "sqlite-vec==0.1.9",
            "cyclonedx-py environment",
            "THIRD_PARTY_LICENSES.md",
            "container_self_check --json",
            "container_entrypoint",
        ):
            self.assertIn(marker, dockerfile)

        annotation_script = (
            REPO_ROOT / "third_party" / "taibu_bridge" / "scripts" / "annotate-sbom.mjs"
        ).read_text(encoding="utf-8")
        for marker in (
            "marten:patched-version",
            "marten:patch-id",
            "marten:patch-sha256",
            "marten:patched-file-sha256:",
        ):
            self.assertIn(marker, annotation_script)

    def test_docker_context_excludes_machine_specific_runtime_config(self) -> None:
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        for path in (
            "config/platform.toml",
            "config/providers.toml",
            "config/models.toml",
            "config/channels.toml",
            "config/mcp.toml",
            "config/ops.toml",
            "config/skills.toml",
            "config/knowledge.toml",
        ):
            self.assertIn(path, dockerignore.splitlines())

    def test_compose_keeps_secrets_in_runtime_env_and_data_persistent(self) -> None:
        compose = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("env_file:", compose)
        self.assertIn("/app/data", compose)
        self.assertNotIn("AMAP_WEB_SERVICE_KEY:", compose)
        self.assertNotIn("KNOWLEDGE_OPERATOR_TOKEN:", compose)


if __name__ == "__main__":
    unittest.main()
