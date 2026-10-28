"""本地 Web 界面，仅用标准库，默认 http://127.0.0.1:8765。"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import corpus
from .library import Library, day_number

STATIC = Path(__file__).with_name("static")


def _json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def make_handler(library: Library):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PageTrail/1.0"

        def log_message(self, fmt, *args):  # 保持终端输出干净
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            self._send(status, _json(payload), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            try:
                if parsed.path == "/api/meta":
                    self._handle_meta()
                elif parsed.path == "/api/search":
                    self._handle_search(query)
                elif parsed.path == "/api/compare":
                    self._handle_compare(query)
                elif parsed.path == "/api/queue":
                    self._handle_queue()
                elif parsed.path in ("/", "/index.html"):
                    self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                elif parsed.path == "/favicon.svg":
                    self._send(200, (STATIC / "favicon.svg").read_bytes(), "image/svg+xml")
                else:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
            except Exception as error:  # 界面需要看到真实错误，不做静默降级
                self._send_json({"error": f"{type(error).__name__}: {error}"}, 500)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if parsed.path == "/api/review":
                    updated = library.rate(payload["id"], payload["result"], day_number())
                    self._send_json({"id": payload["id"], "meta": updated, "queue": _queue_payload(library)})
                else:
                    self._send_json({"error": "unknown endpoint"}, 404)
            except Exception as error:
                self._send_json({"error": f"{type(error).__name__}: {error}"}, 400)

        def _handle_meta(self) -> None:
            self._send_json(
                {
                    "documents": corpus.documents(),
                    "topics": sorted({record["topic"] for record in corpus.passages()}),
                    "stats": library.stats(),
                    "engine": library.describe(),
                    "queue": _queue_payload(library),
                }
            )

        def _handle_search(self, query: dict) -> None:
            text = (query.get("q") or "").strip()
            channel = query.get("channel") or "hybrid"
            doc_id = query.get("doc") or None
            topic = query.get("topic") or None
            if not text:
                self._send_json({"query": "", "channel": channel, "results": []})
                return
            if channel == "fulltext":
                results = library.fulltext(text, limit=4, doc_id=doc_id, topic=topic)
            elif channel == "vector":
                results = library.vector(text, limit=4, doc_id=doc_id, topic=topic)
            else:
                results = library.search(text, limit=4, doc_id=doc_id, topic=topic)
            self._send_json({"query": text, "channel": channel, "results": results})

        def _handle_compare(self, query: dict) -> None:
            text = (query.get("q") or "").strip()
            if not text:
                self._send_json({"query": "", "channels": {"fulltext": [], "vector": [], "hybrid": []}})
                return
            self._send_json({"query": text, "channels": library.compare(text, limit=3)})

        def _handle_queue(self) -> None:
            self._send_json(_queue_payload(library))

    return Handler


def _queue_payload(library: Library) -> dict:
    today = day_number()
    due_now = library.due(today)
    due_next = library.due(today + 1)
    return {
        "today": today,
        "due_today": due_now,
        "due_tomorrow": [row for row in due_next if row["id"] not in {r["id"] for r in due_now}],
        "stats": library.stats(),
    }


def serve(path: str, host: str = "127.0.0.1", port: int = 8765) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    library = Library(path).open()
    if library.describe()["count"] == 0:
        library.ingest(corpus.passages())
    server = ThreadingHTTPServer((host, port), make_handler(library))
    print(f"页迹 PageTrail 已启动：http://{host}:{port}")
    print(f"seekdb 数据目录：{Path(path).resolve()}")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
        library.close()
    return 0
