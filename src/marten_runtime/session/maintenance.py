from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from marten_runtime.session.sqlite_store import SQLiteSessionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or delete persisted Marten sessions.")
    parser.add_argument("--database", default="data/sessions.sqlite3")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--session-id")
    action.add_argument("--prune-older-than-days", type=int)
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SQLiteSessionStore(Path(args.database))
    if args.session_id:
        if not args.apply:
            result = {
                "ok": True,
                "applied": False,
                "session_id": args.session_id,
                "message": "repeat with --apply to delete this session and its descendants",
            }
        else:
            try:
                result = {**store.delete_session(args.session_id), "applied": True}
            except KeyError:
                result = {
                    "ok": False,
                    "applied": False,
                    "error_code": "SESSION_NOT_FOUND",
                    "session_id": args.session_id,
                }
    else:
        days = args.prune_older_than_days
        if days is None or days < 1:
            build_parser().error("--prune-older-than-days must be at least 1")
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = store.prune_sessions(inactive_before=cutoff, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
