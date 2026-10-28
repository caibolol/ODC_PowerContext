"""seekdb 存储层：一个 collection 同时承担混合检索与复习状态存储。"""

from __future__ import annotations

import datetime as dt
import threading
import time
from pathlib import Path

import pyseekdb

from .embedding import LocalHashEmbedding
from .review import grade as grade_state

COLLECTION = "passages"
REVIEW_STATES = ("learning", "review")

# 嵌入式引擎在进程内重启时，客户端可能先于本地 socket 就绪而连接失败，
# 这类错误重试即可恢复；语法 / 配置类错误立即抛出。
TRANSIENT_HINTS = ("connect", "socket", "timed out", "timeout", "unavailable", "refused")


def _is_transient(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(hint in text for hint in TRANSIENT_HINTS)


def day_number(date: dt.date | None = None) -> int:
    return (date or dt.date.today()).toordinal()


def _blank_review() -> dict:
    return {
        "state": "new",
        "due_day": 0,
        "interval_days": 0,
        "ease": 250,
        "reps": 0,
        "lapses": 0,
    }


class Library:
    def __init__(self, path: str | Path = ".pagetrail/seekdb", database: str = "pagetrail"):
        self.path = Path(path)
        self.database = database
        self.last_request: dict | None = None
        self.last_elapsed_ms: float | None = None
        self._lock = threading.RLock()
        self._admin = None
        self._client = None
        self._collection = None

    # ---------- 生命周期 ----------

    def open(self, attempts: int = 10, delay: float = 0.6) -> "Library":
        self.path.mkdir(parents=True, exist_ok=True)
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._open_once()
            except Exception as exc:  # noqa: BLE001 - 仅对启动竞态重试
                if not _is_transient(exc) or attempt == attempts:
                    raise
                last_error = exc
                time.sleep(delay * attempt)
                continue
            return self
        raise RuntimeError(f"seekdb 启动失败：{last_error}")

    def _open_once(self) -> None:
        admin = pyseekdb.AdminClient(path=str(self.path))
        databases = [getattr(db, "name", str(db)) for db in admin.list_databases()]
        if self.database not in databases:
            admin.create_database(self.database)
        self._admin = admin
        self._client = pyseekdb.Client(path=str(self.path), database=self.database)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION, embedding_function=LocalHashEmbedding()
        )

    def close(self) -> None:
        self._collection = None
        self._client = None
        self._admin = None

    def __enter__(self) -> "Library":
        return self.open()

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _require_collection(self):
        if self._collection is None:
            raise RuntimeError("Library 尚未打开，请先调用 open()")
        return self._collection

    # ---------- 写入 ----------

    def ingest(self, records: list[dict], replace: bool = True) -> int:
        collection = self._require_collection()
        ids, texts, metadatas = [], [], []
        for record in records:
            ids.append(record["id"])
            texts.append(record["text"])
            metadatas.append(
                {
                    "doc_id": record["doc_id"],
                    "title": record["title"],
                    "source": record["source"],
                    "kind": record["kind"],
                    "page": int(record["page"]),
                    "topic": record["topic"],
                    "lang": record["lang"],
                    **_blank_review(),
                }
            )
        if replace:
            collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
        else:
            collection.add(ids=ids, documents=texts, metadatas=metadatas)
        collection.refresh_index()
        return len(ids)

    def reset(self) -> None:
        client = self._client
        if client is None:
            raise RuntimeError("Library 尚未打开")
        if client.has_collection(COLLECTION):
            client.delete_collection(COLLECTION)
        self._collection = client.get_or_create_collection(
            name=COLLECTION, embedding_function=LocalHashEmbedding()
        )

    # ---------- 检索 ----------

    @staticmethod
    def _where(doc_id: str | None, topic: str | None) -> dict | None:
        clauses = []
        if doc_id:
            clauses.append({"doc_id": {"$eq": doc_id}})
        if topic:
            clauses.append({"topic": {"$eq": topic}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    @staticmethod
    def _rows(result: dict) -> list[dict]:
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        distances = result.get("distances") or []
        # query/hybrid 返回按查询嵌套的列表，get 返回扁平列表
        if ids and isinstance(ids[0], list):
            ids = ids[0]
            documents = documents[0] if documents else []
            metadatas = metadatas[0] if metadatas else []
            distances = distances[0] if distances else []
        rows = []
        for index, passage_id in enumerate(ids):
            rows.append(
                {
                    "id": passage_id,
                    "text": documents[index] if documents else "",
                    "meta": metadatas[index] if metadatas else {},
                    "distance": distances[index] if distances else None,
                }
            )
        return rows

    def fulltext(self, query: str, limit: int = 5, doc_id: str | None = None, topic: str | None = None) -> list[dict]:
        collection = self._require_collection()
        branch: dict = {"where_document": {"$contains": query}, "n_results": limit}
        where = self._where(doc_id, topic)
        if where:
            branch["where"] = where
        with self._lock:
            result = collection.hybrid_search(
                query=branch, n_results=limit, include=["documents", "metadatas"]
            )
        return self._rows(result)

    def vector(self, query: str, limit: int = 5, doc_id: str | None = None, topic: str | None = None) -> list[dict]:
        collection = self._require_collection()
        kwargs: dict = {"query_texts": [query], "n_results": limit, "include": ["documents", "metadatas"]}
        where = self._where(doc_id, topic)
        if where:
            kwargs["where"] = where
        with self._lock:
            result = collection.query(**kwargs)
        return self._rows(result)

    def search(self, query: str, limit: int = 5, doc_id: str | None = None, topic: str | None = None) -> list[dict]:
        collection = self._require_collection()
        fulltext_branch: dict = {"where_document": {"$contains": query}, "n_results": limit}
        knn_branch: dict = {"query_texts": [query], "n_results": limit}
        where = self._where(doc_id, topic)
        if where:
            fulltext_branch["where"] = where
            knn_branch["where"] = where
        request = {
            "query": fulltext_branch,
            "knn": knn_branch,
            "rank": {"rrf": {}},
            "n_results": limit,
        }
        started = time.perf_counter()
        with self._lock:
            result = collection.hybrid_search(
                query=fulltext_branch,
                knn=knn_branch,
                rank={"rrf": {}},
                n_results=limit,
                include=["documents", "metadatas"],
            )
        self.last_request = request
        self.last_elapsed_ms = (time.perf_counter() - started) * 1000
        return self._rows(result)

    def compare(self, query: str, limit: int = 3, doc_id: str | None = None, topic: str | None = None) -> dict:
        return {
            "fulltext": self.fulltext(query, limit, doc_id, topic),
            "vector": self.vector(query, limit, doc_id, topic),
            "hybrid": self.search(query, limit, doc_id, topic),
        }

    # ---------- 复习状态 ----------

    def get(self, passage_id: str) -> dict | None:
        collection = self._require_collection()
        with self._lock:
            result = collection.get(ids=passage_id, include=["documents", "metadatas"])
        rows = self._rows(result)
        return rows[0] if rows else None

    def rate(self, passage_id: str, result: str, today: int) -> dict:
        collection = self._require_collection()
        current = self.get(passage_id)
        if current is None:
            raise KeyError(f"摘录不存在：{passage_id}")
        merged = {**current["meta"], **grade_state(current["meta"], result, today)}
        with self._lock:
            collection.update(ids=passage_id, metadatas=merged)
        return merged

    def due(self, today: int, limit: int = 20) -> list[dict]:
        collection = self._require_collection()
        where = {
            "$and": [
                {"state": {"$in": list(REVIEW_STATES)}},
                {"due_day": {"$lte": today}},
            ]
        }
        with self._lock:
            result = collection.get(where=where, limit=limit, include=["documents", "metadatas"])
        rows = self._rows(result)
        rows.sort(key=lambda row: (row["meta"].get("due_day", 0), row["id"]))
        return rows

    # ---------- 统计与证据 ----------

    def stats(self) -> dict:
        collection = self._require_collection()
        with self._lock:
            total = collection.count()
            result = collection.get(limit=1000, include=["metadatas"])
        by_state: dict[str, int] = {}
        by_doc: dict[str, int] = {}
        for meta in result.get("metadatas") or []:
            by_state[meta.get("state", "?")] = by_state.get(meta.get("state", "?"), 0) + 1
            by_doc[meta.get("doc_id", "?")] = by_doc.get(meta.get("doc_id", "?"), 0) + 1
        return {"total": total, "by_state": by_state, "by_doc": by_doc}

    def describe(self) -> dict:
        collection = self._require_collection()
        return {
            "engine": "seekdb (embedded)",
            "client": getattr(pyseekdb, "__version__", "unknown"),
            "data_path": str(self.path.resolve()),
            "database": self.database,
            "collection": COLLECTION,
            "count": collection.count(),
            "embedding": LocalHashEmbedding.name(),
            "channels": ["fulltext($contains)", "vector(cosine)", "hybrid(RRF)"],
        }
