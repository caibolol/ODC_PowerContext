"""演示语料：4 份合成学习资料，共 16 段。全部为教学虚构内容，不是真实文献。"""

from __future__ import annotations

DOCUMENTS = [
    {
        "doc_id": "doc-db",
        "title": "分布式数据库课程笔记",
        "source": "课程笔记 · 第 4 讲",
        "kind": "课程笔记",
        "passages": [
            ("p-db-1", 1, "共识算法", "Paxos 协议通过两阶段投票让多个副本对同一个提案达成一致：prepare 阶段收集承诺，accept 阶段提交提案。"),
            ("p-db-2", 1, "复制与一致性", "多副本之间保持一致的关键是日志复制：leader 把日志条目复制到 follower，多数派落盘之后才提交。"),
            ("p-db-3", 2, "共识算法", "Raft 把共识拆成 leader 选举、日志复制和安全性三部分，比 Paxos 更容易理解。"),
            ("p-db-4", 3, "分布式事务", "两阶段提交（2PC）解决跨节点事务的原子性，但协调者故障时会阻塞参与者。"),
            ("p-db-5", 4, "共识算法", "OceanBase 使用 Paxos 协议提交日志，副本分布在多台机器上，少数派故障不影响可用性。"),
        ],
    },
    {
        "doc_id": "doc-ml",
        "title": "机器学习实验记录",
        "source": "实验记录 · exp-07",
        "kind": "实验记录",
        "passages": [
            ("p-ml-1", 1, "调参", "学习率设为 0.1 时损失震荡，降到 0.01 后收敛平稳。"),
            ("p-ml-2", 2, "过拟合", "训练集准确率 0.98、验证集 0.71，判断为过拟合，加入 L2 正则后验证集升到 0.79。"),
            ("p-ml-3", 2, "调参", "batch size 从 32 调到 128 后单轮训练时间下降 40%，但收敛轮数增加。"),
            ("p-ml-4", 3, "优化器", "梯度下降的步长由学习率控制，动量项可以缓解震荡。"),
        ],
    },
    {
        "doc_id": "doc-rag",
        "title": "文献阅读卡片：检索增强生成",
        "source": "阅读卡片 · 预印本整理",
        "kind": "阅读卡片",
        "passages": [
            ("p-rag-1", 1, "RAG", "检索增强生成（RAG）先检索相关段落，再把段落拼进提示词交给生成模型，减少幻觉。"),
            ("p-rag-2", 1, "检索", "向量检索把文本编码成向量，用余弦相似度找近邻；全文检索依赖词项匹配，对专有名词更稳。"),
            ("p-rag-3", 2, "检索", "混合检索同时跑向量和全文两路，再用 RRF 融合排序，通常比单路更稳。"),
            ("p-rag-4", 3, "重排序", "重排序（rerank）用交叉编码器对候选段落重新打分，代价是延迟更高。"),
        ],
    },
    {
        "doc_id": "doc-thesis",
        "title": "毕业论文写作提纲",
        "source": "写作提纲 · v3",
        "kind": "写作提纲",
        "passages": [
            ("p-thesis-1", 1, "写作", "引言部分要说明研究问题和现有方法的不足，控制在 800 字以内。"),
            ("p-thesis-2", 2, "写作", "相关工作按时间线和方法类别两条线索组织，避免简单罗列。"),
            ("p-thesis-3", 3, "写作", "实验设计需要给出数据集、基线方法和评价指标，并说明复现步骤。"),
        ],
    },
]


def passages() -> list[dict]:
    records = []
    for document in DOCUMENTS:
        for passage_id, page, topic, text in document["passages"]:
            records.append(
                {
                    "id": passage_id,
                    "text": text,
                    "doc_id": document["doc_id"],
                    "title": document["title"],
                    "source": document["source"],
                    "kind": document["kind"],
                    "page": page,
                    "topic": topic,
                    "lang": "en" if text.isascii() else "zh",
                }
            )
    return records


def documents() -> list[dict]:
    return [
        {
            "doc_id": document["doc_id"],
            "title": document["title"],
            "source": document["source"],
            "kind": document["kind"],
            "passages": len(document["passages"]),
        }
        for document in DOCUMENTS
    ]
