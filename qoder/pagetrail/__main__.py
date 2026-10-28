"""python -m pagetrail serve —— 启动本地 Web 界面。"""

from __future__ import annotations

import argparse
from pathlib import Path

from .web import serve


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(prog="pagetrail", description="页迹 PageTrail")
    parser.add_argument("command", choices=["serve"], help="目前支持 serve")
    parser.add_argument("--path", default=str(root / ".pagetrail" / "seekdb"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve":
        return serve(args.path, args.host, args.port)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
