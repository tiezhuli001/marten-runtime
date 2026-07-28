from __future__ import annotations

import json
import os
from pathlib import Path

from marten_runtime.interfaces.http.container_self_check import run_container_self_check
from marten_runtime.interfaces.http.serve import main as serve_main


def main() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    result = run_container_self_check(repo_root=repo_root, env=dict(os.environ))
    print(json.dumps({"container_self_check": result}, ensure_ascii=True, sort_keys=True))
    serve_main()


if __name__ == "__main__":
    main()
