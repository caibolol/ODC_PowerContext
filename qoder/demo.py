#!/usr/bin/env python3
"""页迹 PageTrail 一键演示与验证样例。

用法：
    python demo.py                 # 在 ./.pagetrail/seekdb 上完整跑一遍
    python demo.py --path /tmp/x   # 指定数据目录
    python demo.py --keep          # 保留已有数据（默认每次重建）

评审只需要这一个命令，输出末尾会给出 10 项自检结果并以退出码表示成败。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pagetrail import corpus
from pagetrail.library import Library, day_number

QUERIES = [
    ("Paxos 两阶段投票", "p-db-1"),
    ("验证集过拟合", "p-ml-2"),
    ("学习率震荡", "p-ml-1"),
    ("RRF 融合排序", "p-rag-3"),
]

WIDTH = 84
CHECKS: list[tuple[str, bool, str]] = []


def width(text: str) -> int:
    return sum(2 if ord(char) > 0x2E7F else 1 for char in text)


def pad(text: str, size: int) -> str:
    return text + " " * max(0, size - width(text))


def line(char: str = "-") -> None:
    print(char * WIDTH)


def section(step: str, title: str) -> None:
    print()
    print(f"[{step}] {title}")
    line("-")


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def clip(text: str, size: int = 46) -> str:
    return text if width(text) <= size else text[: size // 2] + "…"


def day_to_date(day: int) -> str:
    return dt.date.fromordinal(day).isoformat() if day else "-"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="页迹 PageTrail 演示")
    parser.add_argument("--path", default=str(ROOT / ".pagetrail" / "seekdb"))
    parser.add_argument("--keep", action="store_true", help="沿用已有数据，不重建集合")
    args = parser.parse_args()

    today = day_number()
    tomorrow = today + 1
    print("页迹 PageTrail · 本地资料混合检索与复习助手")
    print(f"今天：{day_to_date(today)}（第 {today} 天）")

    with Library(args.path) as lib:
        # ---------- 1. 初始化 ----------
        section("1/6", "初始化 seekdb 并写入资料")
        if not args.keep:
            lib.reset()
        ingested = lib.ingest(corpus.passages())
        info = lib.describe()
        print(f"  数据目录  {info['data_path']}")
        print(f"  集合      {info['collection']}（向量索引 + 全文索引 + 元数据）")
        print(f"  入库      {len(corpus.documents())} 份资料，{ingested} 段摘录")
        print(f"  记录数    {info['count']}")
        check("seekdb 嵌入式实例就绪，16 段摘录入库", info["count"] == 16, f"count={info['count']}")

        # ---------- 2. 混合检索 ----------
        section("2/6", "混合检索：全文 + 向量 + RRF，每条结果带出处")
        for query, expected in QUERIES:
            rows = lib.search(query, limit=3)
            elapsed = lib.last_elapsed_ms or 0
            print(f"  查询「{query}」  用时 {elapsed:.1f} ms")
            for rank, row in enumerate(rows, start=1):
                meta = row["meta"]
                distance = f"{row['distance']:.4f}" if row["distance"] is not None else "-"
                print(
                    f"    {rank}. [{meta['title']} · 第 {meta['page']} 页] "
                    f"{clip(row['text'])}  (rrf distance {distance})"
                )
            if query == QUERIES[0][0]:
                check("查询「Paxos 两阶段投票」Top-1 命中 p-db-1", rows[0]["id"] == expected, rows[0]["id"])
                check(
                    "每条结果都带标题/来源/页码",
                    all(row["meta"].get("title") and row["meta"].get("source") and row["meta"].get("page") for row in rows),
                )
            if query == QUERIES[1][0]:
                check("查询「验证集过拟合」Top-1 命中 p-ml-2", rows[0]["id"] == expected, rows[0]["id"])
            print()

        # ---------- 3. 三通道对比 ----------
        section("3/6", "三通道对比：单路各有偏差，混合后排序稳定")
        probe = "学习率震荡"
        channels = lib.compare(probe, limit=3)
        labels = {"fulltext": "全文", "vector": "向量", "hybrid": "混合"}
        for channel in ("fulltext", "vector", "hybrid"):
            rows = channels[channel]
            top = rows[0] if rows else None
            print(f"  {labels[channel]}  " + (" | ".join(row["id"] for row in rows)))
            if top:
                print(f"        Top-1 来源：{top['meta']['title']} 第 {top['meta']['page']} 页 · {clip(top['text'], 40)}")
        fulltext_top = channels["fulltext"][0]["id"] if channels["fulltext"] else None
        vector_top = channels["vector"][0]["id"] if channels["vector"] else None
        hybrid_top = channels["hybrid"][0]["id"] if channels["hybrid"] else None
        check("全文与向量通道 Top-1 不同（两路确实互补）", fulltext_top != vector_top, f"{fulltext_top} vs {vector_top}")
        check("混合通道 Top-1 命中 p-ml-1", hybrid_top == "p-ml-1", str(hybrid_top))
        union = {row["id"] for row in channels["fulltext"] + channels["vector"]}
        check("混合 Top-3 全部来自两路候选", {row["id"] for row in channels["hybrid"]} <= union)

        # ---------- 4. 结构化过滤 ----------
        section("4/6", "结构化过滤：把检索限定在某一份资料 / 某个主题")
        scoped = lib.search("一致性", doc_id="doc-ml")
        wanted = lib.search("Paxos", doc_id="doc-db", topic="共识算法")
        print(f"  查询「一致性」限定《机器学习实验记录》→ {[row['id'] for row in scoped]}")
        print(f"  查询「Paxos」限定 doc-db + 主题「共识算法」→ {[row['id'] for row in wanted]}")
        check("过滤结果全部落在目标资料内", all(row["meta"]["doc_id"] == "doc-ml" for row in scoped), str([row["id"] for row in scoped]))
        check("资料 + 主题双重过滤同时生效", all(row["meta"]["doc_id"] == "doc-db" and row["meta"]["topic"] == "共识算法" for row in wanted))

        # ---------- 5. 复习排程 ----------
        section("5/6", "复习排程：对检索结果评分，按间隔重复安排下次复习")
        top3 = lib.search("Paxos 两阶段投票", limit=3)
        grades = ["good", "hard", "again"]
        for row, result in zip(top3, grades):
            updated = lib.rate(row["id"], result, today)
            print(
                f"  {row['id']:<8} 评分 {result:<5} → 状态 {updated['state']:<8} "
                f"间隔 {updated['interval_days']} 天，下次 {day_to_date(updated['due_day'])}"
            )
        due_today = lib.due(today)
        due_tomorrow = lib.due(tomorrow)
        print(f"  今日到期 {len(due_today)} 条；明日到期 {len(due_tomorrow)} 条")
        check(
            "评分写入正确的状态与间隔",
            lib.get("p-db-1")["meta"]["state"] == "review"
            and lib.get("p-db-3")["meta"]["state"] == "learning"
            and lib.get("p-db-3")["meta"]["lapses"] == 1,
        )
        check("到期队列按日期过滤正确（今天 0 / 明天 3）", len(due_today) == 0 and len(due_tomorrow) == 3, f"{len(due_today)}/{len(due_tomorrow)}")

        evidence = lib.describe()
        stats = lib.stats()
        request = lib.last_request
        elapsed = lib.last_elapsed_ms or 0.0

    # ---------- 6. 跨进程持久化 ----------
    section("6/6", "跨进程持久化：另起一个进程读取同一份 seekdb 数据")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    completed = subprocess.run(
        [sys.executable, "-m", "pagetrail.state_probe", "--path", args.path, "--id", "p-db-1"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    child = {}
    if completed.returncode == 0:
        child = json.loads(completed.stdout)
    child_meta = child.get("meta", {})
    print(f"  子进程读回 p-db-1：state={child_meta.get('state')} reps={child_meta.get('reps')} due={day_to_date(child_meta.get('due_day', 0))}")
    check(
        "另一个进程读到相同的复习状态",
        child_meta.get("state") == "review" and child_meta.get("reps") == 1,
        completed.stderr.strip()[:80],
    )

    # ---------- 证据 ----------
    print()
    line("=")
    print("seekdb 使用证据（评审可核对）")
    line("=")
    print(f"  引擎        seekdb 嵌入式实例（pyseekdb {evidence['client']}）")
    print(f"  数据目录    {evidence['data_path']}")
    print(f"  集合        {evidence['collection']} · {evidence['count']} 条")
    print(f"  嵌入        {evidence['embedding']}（512 维，离线确定性，无需网络）")
    print(f"  检索通道    {' + '.join(evidence['channels'])}")
    print(f"  状态分布    {stats['by_state']}")
    print("  最近一次混合检索请求：")
    print("    " + json.dumps(request, ensure_ascii=False))
    print(f"  该请求在 seekdb 内耗时 {elapsed:.1f} ms")

    print()
    line("=")
    print("验证结果")
    line("=")
    passed = 0
    for index, (name, ok, detail) in enumerate(CHECKS, start=1):
        status = "PASS" if ok else "FAIL"
        passed += 1 if ok else 0
        suffix = f"  ({detail})" if detail and not ok else ""
        print(f"  {status}  {index:>2}. {name}{suffix}")
    line("=")
    total = len(CHECKS)
    print(f"  {passed}/{total} 项通过")
    if passed == total:
        print("  全部通过：按 README 的命令即可在干净环境复现。")
        print("  图形界面：python -m pagetrail serve")
        return 0
    print("  存在未通过项，请检查上面的输出。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
