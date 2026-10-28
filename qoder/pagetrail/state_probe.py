"""子进程读取指定摘录的状态，用于跨进程持久化验证。"""

from __future__ import annotations

import argparse
import json
import sys

from .library import Library


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    with Library(args.path) as lib:
        row = lib.get(args.id)
    if row is None:
        print(json.dumps({"error": "not found", "id": args.id}, ensure_ascii=False))
        return 1
    print(json.dumps({"id": row["id"], "meta": row["meta"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
