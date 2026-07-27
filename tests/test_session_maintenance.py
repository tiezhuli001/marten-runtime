from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.session.maintenance import main
from marten_runtime.session.sqlite_store import SQLiteSessionStore


class SessionMaintenanceTests(unittest.TestCase):
    def test_cli_requires_apply_before_exact_deletion(self) -> None:
        with TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(database)
            store.create(session_id="sess_cli", conversation_id="conv-cli")

            preview_output = io.StringIO()
            with redirect_stdout(preview_output):
                preview_code = main(["--database", str(database), "--session-id", "sess_cli"])
            apply_output = io.StringIO()
            with redirect_stdout(apply_output):
                apply_code = main(
                    ["--database", str(database), "--session-id", "sess_cli", "--apply"]
                )

            self.assertEqual(preview_code, 0)
            self.assertFalse(json.loads(preview_output.getvalue())["applied"])
            self.assertEqual(apply_code, 0)
            self.assertTrue(json.loads(apply_output.getvalue())["applied"])
            self.assertEqual(SQLiteSessionStore(database).count(), 0)


if __name__ == "__main__":
    unittest.main()
