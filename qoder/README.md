# 页迹 PageTrail

**在你的资料里，找到那一页，并记得住。**

作品介绍网站：https://pagetrail-ul4zn1269im.qoder.zone （Qoder Sites 发布，无需登录即可访问）

页迹是一个面向学生和科研新手的本地资料检索与复习助手。它把课程笔记、实验记录、阅读卡片切成带出处的段落存进 seekdb，用**全文 + 向量 + 结构化过滤的混合检索**帮你找到原文那一页，再把检索结果直接排进**间隔重复复习队列**——找得到，也记得住。

## 解决的问题

复习和写论文时最常见的浪费不是"没学过"，而是：

1. 记得看过某句话，却翻不到它出现在哪份资料的第几页；
2. 关键词记得不准，纯全文检索搜不到，纯向量检索又会召回不相干的段落；
3. 找到了也保存不下来，下次还得重新找一遍。

页迹把"检索"和"记住"接在一条链上：检索结果可以直接评分进入复习队列，状态存在 seekdb 里，重启和换进程都还在。

## 核心功能

- **带出处的混合检索**：每条结果都带资料标题、来源、页码，原文段落高亮显示命中的词。
- **三通道可切换、可对比**：同一个查询可以分别走全文（`$contains`）、向量（余弦）和混合（RRF 融合），并直接看到三路排序的差异。
- **结构化过滤**：检索可以限定在某一份资料、或某个主题内进行。
- **间隔重复复习**：对检索结果评分（熟练 / 一般 / 吃力），按简化 SM-2 计算下次复习日期与间隔。
- **到期队列**：按"今天 / 明天到期"列出该复习的段落。
- **持久化**：检索结果、复习状态、到期时间都写在同一个 seekdb collection 里。
- **可分享的检索链接**：`/?q=关键词&channel=fulltext` 形式的深链接。
- **零外部服务**：seekdb 以嵌入式方式随进程启动，不需要 Docker、不需要数据库服务器、不需要任何 API Key。

## seekdb 如何发挥作用

项目没有"假数据库"或内存兜底：所有数据都在 seekdb 里，检索真的由 seekdb 执行。

| 用途 | 实现 |
| --- | --- |
| 向量检索 | collection 内的向量索引 + 余弦距离 |
| 全文检索 | `where_document: {"$contains": ...}` |
| 混合检索 | `hybrid_search(query=..., knn=..., rank={"rrf": {}})`，由 seekdb 做 RRF 融合 |
| 结构化过滤 | 元数据 `doc_id` / `topic` 的 `$eq`、`$and` 过滤 |
| 复习状态 | 同一条记录的元数据（`state` / `due_day` / `interval_days` / `ease` / `reps` / `lapses`），更新后重新检索即可读回 |

`demo.py` 会把最近一次发给 seekdb 的混合检索请求原样打印出来（`query` / `knn` / `rank` 三部分），并给出在库内耗时，评审可以直接核对。

嵌入向量由项目内置的 `pagetrail-local-hash-v1` 生成：字符 2/3-gram 与英文词元的带符号哈希向量（512 维，L2 归一化）。选择它是因为它**离线、确定性、无需下载模型**，中英文都能召回词形相近的段落，评审在任何机器上都能复现同一结果。它是词形级向量，不宣称是语义大模型；如果需要语义嵌入，`pagetrail/embedding.py` 里替换 `EmbeddingFunction` 即可。

## 快速开始

环境要求：Python 3.11+（在 3.12 上验证），无需 Docker、无需 seekdb 服务端。

```bash
# 1. 进入项目目录
cd qoder

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. 一键跑通演示与自检（会自动建库、写入样例、执行检索、评分并校验）
python demo.py
```

`python demo.py` 会在 `./.pagetrail/seekdb` 建一个嵌入式 seekdb 实例，末尾打印 12 项自检结果，全部通过时退出码为 0。

```bash
# 4. 图形界面（可选）
python -m pagetrail serve
# 浏览器打开 http://127.0.0.1:8765
```

## 验证样例

`demo.py` 就是可执行的验证样例，固定使用 4 份合成资料、16 段摘录，步骤固定、结果确定：

```text
[1/6] 初始化 seekdb 并写入资料          4 份资料 / 16 段摘录
[2/6] 混合检索 4 个查询                 每条结果带标题、来源、页码
[3/6] 三通道对比「学习率震荡」          全文 Top-1 = p-ml-1，向量 Top-1 = p-ml-4，混合 Top-1 = p-ml-1
[4/6] 结构化过滤                        限定《机器学习实验记录》/ 限定 doc-db + 共识算法
[5/6] 复习排程                          对 Top-3 评分，得到状态、间隔与下次复习日期
[6/6] 跨进程持久化                      另起一个 Python 进程读回同一份状态
```

自检项（完整输出见 [evidence/demo-run.txt](evidence/demo-run.txt)）：

| # | 检查 |
| --- | --- |
| 1 | seekdb 嵌入式实例就绪，16 段摘录入库 |
| 2 | 查询「Paxos 两阶段投票」Top-1 命中 p-db-1 |
| 3 | 每条结果都带标题/来源/页码 |
| 4 | 查询「验证集过拟合」Top-1 命中 p-ml-2 |
| 5 | 全文与向量通道 Top-1 不同（两路确实互补） |
| 6 | 混合通道 Top-1 命中 p-ml-1 |
| 7 | 混合 Top-3 全部来自两路候选 |
| 8 | 过滤结果全部落在目标资料内 |
| 9 | 资料 + 主题双重过滤同时生效 |
| 10 | 评分写入正确的状态与间隔 |
| 11 | 到期队列按日期过滤正确（今天 0 / 明天 3） |
| 12 | 另一个进程读到相同的复习状态 |

单元测试：

```bash
python -m unittest discover -s tests -v      # 20 个用例
```

## 目录结构

```text
qoder/
├── demo.py                  # 一键演示与验证样例（评审入口）
├── pagetrail/
│   ├── library.py           # seekdb 封装：入库、混合检索、过滤、复习状态、证据
│   ├── embedding.py         # 离线确定性嵌入 + pyseekdb 注册
│   ├── review.py            # 简化 SM-2 复习排程
│   ├── corpus.py            # 4 份合成资料 / 16 段摘录
│   ├── web.py               # 标准库 HTTP 服务 + JSON API
│   ├── state_probe.py       # 子进程读状态，用于跨进程持久化验证
│   ├── __main__.py          # python -m pagetrail serve
│   └── static/index.html    # 单页前端
├── tests/test_pagetrail.py  # 20 个单元测试
├── evidence/                # 运行日志与界面截图
├── site/                    # 已发布的介绍网站源码（Qoder Sites 静态包）
├── requirements.txt
├── DEVELOPMENT.md           # Qoder 开发记录
└── README.md
```

## 数据说明与已知限制

- 资料库中的 4 份文档、16 段摘录全部是为演示编写的**合成教学样例**，其中的数值、实验结论和引用关系均为虚构，不代表真实文献。
- 离线嵌入是词形级向量，不是语义模型：同义词（如"副本"与"replica"）不会被向量通道召回，此时依赖全文通道。
- 续跑 `demo.py` 会重建 collection（这是为了结果可复现）；`python -m pagetrail serve` 不会覆盖已有数据。
- pyseekdb 嵌入式引擎在一个进程内绑定首个数据目录，因此同一个 Python 进程只用 `--path` 指向一个数据目录；换目录请另起进程。
- 目前是单机本地应用，没有多用户和权限体系。

## Qoder 开发记录

开发过程、账号信息与关键迭代记录见 [DEVELOPMENT.md](DEVELOPMENT.md)。
