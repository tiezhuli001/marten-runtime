import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from marten_runtime.evals.run_metadata import git_state
from marten_runtime.evals.run_metadata import build_eval_run_id


class RunMetadataTests(unittest.TestCase):
    def test_build_eval_run_id_stays_unique_when_timestamp_repeats(self) -> None:
        fixed = datetime(2026, 5, 2, 12, 34, 56, 123456, tzinfo=timezone.utc)
        with patch("marten_runtime.evals.run_metadata.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed
            first = build_eval_run_id("suite", "abcdef123456")
            second = build_eval_run_id("suite", "abcdef123456")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("eval_suite_20260502123456123456_abcdef12_"))
        self.assertTrue(second.startswith("eval_suite_20260502123456123456_abcdef12_"))

    def test_git_state_marks_untracked_files_as_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "config", "user.email", "eval-tests@example.com"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Eval Tests"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            (repo_root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            (repo_root / "untracked.txt").write_text("pending\n", encoding="utf-8")

            _, _, dirty = git_state(repo_root)

        self.assertTrue(dirty)


if __name__ == "__main__":
    unittest.main()
