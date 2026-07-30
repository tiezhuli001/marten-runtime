from __future__ import annotations

import argparse
import json
from pathlib import Path

from marten_runtime.bazi_cases.book_extraction import BookProfile, extract_book_cases, extraction_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract structured Bazi case candidates from a book.")
    parser.add_argument("path")
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="")
    parser.add_argument("--output")
    args = parser.parse_args()
    candidates = extract_book_cases(args.path, BookProfile(title=args.title, author=args.author))
    payload = {
        "report": extraction_report(candidates),
        "accepted_items": [item.as_import_item() for item in candidates if item.grade in {"A", "B"}],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
