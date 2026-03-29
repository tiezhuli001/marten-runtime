import subprocess
import tempfile
import unittest
from pathlib import Path

from marten_runtime.domains.coding.models import CodingRequest
from marten_runtime.domains.coding.validation import ValidationRunner
from marten_runtime.domains.coding.service import CodingService


class CodingRuntimeTests(unittest.TestCase):
    def test_coding_service_returns_artifact_with_validation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("v1\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            tracked.write_text("v2\n", encoding="utf-8")

            service = CodingService()
            request = CodingRequest(
                title="Add test coverage",
                body="touch one file and run validation",
                repo=str(repo),
                acceptance=["python -c \"print('validation ok')\""],
                constraints=["keep runtime boundary"],
            )

            artifact = service.run(request, run_id="run_coding_1", trace_id="trace_coding_1")

        self.assertEqual(artifact.run_id, "run_coding_1")
        self.assertTrue(artifact.validation_run_id.startswith("run_validation"))
        self.assertTrue(artifact.validation_ok)
        self.assertIn("tracked.txt", artifact.changed_files)
        self.assertEqual(artifact.trace_id, "trace_coding_1")
        self.assertEqual(artifact.backend_id, "subprocess")
        self.assertEqual(artifact.validation_commands, ["python -c \"print('validation ok')\""])

    def test_validation_runner_returns_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ValidationRunner().run(
                ["python -c \"import sys; sys.exit(4)\""],
                trace_id="trace_validation_1",
                cwd=tmpdir,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.trace_id, "trace_validation_1")
        self.assertEqual(result.error_code, "command_failed")
        self.assertEqual(result.backend_id, "subprocess")


if __name__ == "__main__":
    unittest.main()
