import unittest
from pathlib import Path

from marten_runtime.subagents.repo_context import (
    repository_context_env,
    render_repository_context_note,
    resolve_repository_context,
)


class RepositoryContextTests(unittest.TestCase):
    def test_resolve_repository_context_normalizes_ssh_remote_from_env(self) -> None:
        context = resolve_repository_context(
            None,
            env={
                "MARTEN_REPO_URL": "git@github.com:tiezhuli001/marten-runtime.git",
                "MARTEN_REPO_BRANCH": "main",
            },
        )

        self.assertIsNotNone(context)
        self.assertEqual(
            context.url if context is not None else None,
            "https://github.com/tiezhuli001/marten-runtime",
        )
        self.assertEqual(
            context.slug if context is not None else None,
            "tiezhuli001/marten-runtime",
        )
        self.assertEqual(context.branch if context is not None else None, "main")

    def test_repository_context_env_reads_current_repo_identity(self) -> None:
        values = repository_context_env(Path(__file__).resolve().parents[1])

        self.assertEqual(values.get("MARTEN_REPO_SLUG"), "tiezhuli001/marten-runtime")
        self.assertEqual(
            values.get("MARTEN_REPO_URL"),
            "https://github.com/tiezhuli001/marten-runtime",
        )
        self.assertTrue(values.get("MARTEN_REPO_BRANCH"))

    def test_render_repository_context_note_mentions_slug_and_url(self) -> None:
        note = render_repository_context_note(
            resolve_repository_context(
                None,
                env={
                    "MARTEN_REPO_SLUG": "tiezhuli001/marten-runtime",
                    "MARTEN_REPO_URL": "https://github.com/tiezhuli001/marten-runtime",
                    "MARTEN_REPO_BRANCH": "main",
                },
            )
        )

        self.assertIsNotNone(note)
        self.assertIn("tiezhuli001/marten-runtime", note or "")
        self.assertIn("https://github.com/tiezhuli001/marten-runtime", note or "")
        self.assertNotIn("当前分支", note or "")


if __name__ == "__main__":
    unittest.main()
