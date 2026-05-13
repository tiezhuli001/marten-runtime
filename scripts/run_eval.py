from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from marten_runtime.config.env_loader import load_repo_env

from marten_runtime.evals.run_metadata import REPO_ROOT
from marten_runtime.evals.service import (
    EvalRunRequest,
    list_suite_paths,
    resolve_suite_dependency_block,
    run_eval_suite,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run marten-runtime offline eval suites.")
    parser.add_argument("--suite", help="suite id to run")
    parser.add_argument("--mode", choices=["live", "scripted"], help="execution mode")
    parser.add_argument("--profile", help="profile name")
    parser.add_argument("--baseline")
    parser.add_argument("--baseline-run")
    parser.add_argument("--write-baseline")
    parser.add_argument("--db-path", default="data/evals.sqlite3")
    parser.add_argument("--report-root", default="reports/evals")
    parser.add_argument("--list-suites", action="store_true")
    parser.add_argument("--case-timeout-seconds", type=float, default=120.0, help="live eval per-case timeout; default 120 seconds, <=0 disables")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(os.environ.get("MARTEN_EVAL_REPO_ROOT") or REPO_ROOT)
    load_repo_env(repo_root)
    if args.list_suites:
        for path in list_suite_paths(repo_root):
            print(path.stem)
        return 0
    if not args.suite or not args.mode or not args.profile:
        parser.print_usage(sys.stderr)
        return 2
    try:
        result = run_eval_suite(
            EvalRunRequest(
                suite_id=args.suite,
                mode=args.mode,
                profile_name=args.profile,
                baseline=args.baseline,
                baseline_run_id=args.baseline_run,
                write_baseline=args.write_baseline,
                db_path=args.db_path,
                report_root=args.report_root,
                env=dict(os.environ),
                case_timeout_seconds=args.case_timeout_seconds,
                progress_printer=(lambda message: print(message, flush=True)),
            ),
            repo_root=repo_root,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"eval_run_id={result.summary.eval_run_id}")
    print(f"suite_id={result.summary.suite_id}")
    print(f"status={result.summary.status}")
    if result.blocked_reason is not None:
        print(f"blocked_reason={result.blocked_reason}")
    else:
        print(f"total_score={result.summary.total_score}")
        print(f"pass_rate={result.summary.pass_rate}")
    print(f"artifact_root={result.artifact_root}")
    if result.blocked_reason is not None:
        return 2
    return 0 if result.summary.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
