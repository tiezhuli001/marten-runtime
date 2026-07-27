from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore
from marten_runtime.runtime.bazi_bridge import BaziBridgeManager, ENGINE


def run_container_self_check(
    *,
    repo_root: str | Path,
    env: dict[str, str] | None = None,
    knowledge_db_path: str | Path | None = None,
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    resolved_env = dict(os.environ if env is None else env)
    manager = BaziBridgeManager(repo_root=root, env=resolved_env)
    diagnostics = manager.diagnostics_summary()
    if not diagnostics["bridge"]["configured"]:
        raise RuntimeError("container self-check: Bazi bridge is unavailable")
    node_version = str(diagnostics["bridge"].get("node_version") or "")
    if not node_version.startswith("v22."):
        raise RuntimeError(f"container self-check: expected Node 22, got {node_version}")

    chart = manager.invoke(
        "chart",
        {
            "gender": "male",
            "birthYear": 1988,
            "birthMonth": 2,
            "birthDay": 15,
            "birthHour": 23,
            "birthMinute": 30,
            "calendarType": "solar",
            "isLeapMonth": False,
            "timeBasis": "clock",
            "timezone": "Asia/Shanghai",
            "sourceTimeStandard": "beijing_standard",
        },
        request_id="container_self_check",
    )
    if not chart.get("ok") or chart.get("engine") != ENGINE:
        raise RuntimeError("container self-check: Bazi engine contract failed")
    normalized_time = chart.get("normalizedTime") or {}
    if normalized_time.get("dayBoundaryPolicy") != "lunar_javascript_sect1":
        raise RuntimeError("container self-check: day-boundary policy mismatch")
    if normalized_time.get("qiyunMethod") != "lunar_javascript_yun_sect1":
        raise RuntimeError("container self-check: qiyun policy mismatch")

    historical_offset = datetime(
        1941, 6, 1, 12, tzinfo=ZoneInfo("Asia/Shanghai")
    ).utcoffset()
    if historical_offset != timedelta(hours=9):
        raise RuntimeError("container self-check: historical timezone data mismatch")

    if knowledge_db_path is None:
        temporary = TemporaryDirectory(prefix="marten-container-self-check-")
        db_path = Path(temporary.name) / "knowledge.sqlite3"
    else:
        temporary = None
        db_path = Path(knowledge_db_path)
    try:
        store = SQLiteKnowledgeStore(db_path)
        with sqlite3.connect(store.db_path) as conn:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(knowledge_ingest_jobs)")
            }
        required_columns = {"error_code", "retryable", "staged_file_path"}
        if not required_columns <= columns:
            raise RuntimeError("container self-check: Knowledge schema is incomplete")
    finally:
        if temporary is not None:
            temporary.cleanup()

    return {
        "ok": True,
        "node_major": 22,
        "bridge_protocol": diagnostics["bridge"]["protocol_version"],
        "engine": dict(ENGINE),
        "historical_timezone": "available",
        "knowledge_schema": "available",
        "amap": {
            "configured": diagnostics["place_resolution"]["configured"],
            "reason": diagnostics["place_resolution"]["reason"],
        },
        "knowledge_operator": {
            "configured": bool(
                str(resolved_env.get("KNOWLEDGE_OPERATOR_TOKEN") or "").strip()
            )
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[4]
    result = run_container_self_check(repo_root=repo_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    else:
        print("container self-check passed")


if __name__ == "__main__":
    main()
