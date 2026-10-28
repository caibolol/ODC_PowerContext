const SAMPLE_DATA = [
  {
    title: "OceanBase 分布式数据库架构设计",
    source_url: "https://example.com/synthetic/oceanbase-arch",
    source_page: "12-15",
    body_text: "OceanBase 采用 shared-nothing 架构，每个节点运行完整的数据库引擎副本。数据通过多副本 Paxos 协议保持一致性，支持强同步和异步复制模式。Zone 是物理隔离单元，Region 用于跨地域容灾。",
    tags: "数据库,分布式,OceanBase,架构"
  },
  {
    title: "Introduction to Full-Text Search in MySQL",
    source_url: "https://example.com/synthetic/mysql-ft",
    source_page: "45-48",
    body_text: "MySQL full-text search uses inverted indexes to efficiently locate documents containing specific terms. The MATCH() function with AGAINST() clause supports natural language mode and boolean mode. Relevance ranking is computed using term frequency and inverse document frequency.",
    tags: "MySQL,fulltext,search,index"
  },
  {
    title: "Paxos 共识算法原理与实践",
    source_url: "https://example.com/synthetic/paxos",
    source_page: "23-30",
    body_text: "Paxos 算法分为 Proposer、Acceptor 和 Learner 三种角色。Prepare 阶段获取提案编号承诺，Accept 阶段确认实际提案。Multi-Paxos 通过固定 Leader 减少通信轮次，是分布式数据库一致性的基础协议。",
    tags: "分布式,共识,Paxos,算法"
  },
  {
    title: "Research Methods for Literature Review",
    source_url: "https://example.com/synthetic/lit-review",
    source_page: "8-11",
    body_text: "Systematic literature review requires clear research questions, inclusion/exclusion criteria, and reproducible search strategies. Evidence synthesis involves coding themes across studies, assessing quality, and identifying gaps. Tools like Zotero and NVivo help organize sources and annotations.",
    tags: "research,methodology,literature,review"
  },
  {
    title: "SQL 注入攻击与防御技术",
    source_url: "https://example.com/synthetic/sql-injection",
    source_page: "67-72",
    body_text: "SQL 注入通过在用户输入中嵌入恶意 SQL 片段来操纵数据库查询。防御手段包括参数化查询（预编译语句）、输入验证白名单、最小权限原则和 WAF 规则。参数绑定是最根本的防御方式，它将数据与指令分离。",
    tags: "安全,SQL注入,防御,参数化"
  },
  {
    title: "LSM-Tree 存储引擎详解",
    source_url: "https://example.com/synthetic/lsm-tree",
    source_page: "34-40",
    body_text: "LSM-Tree 将随机写转换为顺序写，通过 MemTable、SSTable 和 Compaction 三层结构实现高吞吐写入。读取时需合并多层数据，可能产生读放大。Leveled Compaction 和 Tiered Compaction 是两种主流策略，分别优化读性能和写性能。",
    tags: "存储引擎,LSM-Tree,数据库,性能"
  },
  {
    title: "Academic Writing and Citation Practices",
    source_url: "https://example.com/synthetic/academic-writing",
    source_page: "15-18",
    body_text: "Proper citation avoids plagiarism and strengthens academic arguments. APA, MLA, and Chicago styles each have specific rules for in-text citations and reference lists. When quoting directly, include page numbers. Paraphrasing still requires attribution to the original source.",
    tags: "academic,writing,citation,ethics"
  },
  {
    title: "OceanBase 事务处理与 MVCC 机制",
    source_url: "https://example.com/synthetic/oceanbase-txn",
    source_page: "56-63",
    body_text: "OceanBase 支持行级锁和乐观锁两种并发控制模式。MVCC 通过多版本数据实现读写不冲突，每个事务看到一致性快照。事务日志持久化到 Clog 中，通过 Paxos 协议在副本间同步，确保 RPO=0 的金融级数据可靠性。",
    tags: "OceanBase,事务,MVCC,并发控制"
  },
  {
    title: "Information Retrieval Evaluation Metrics",
    source_url: "https://example.com/synthetic/ir-metrics",
    source_page: "92-98",
    body_text: "Precision measures the fraction of retrieved documents that are relevant, while recall measures the fraction of relevant documents that are retrieved. F1 score balances both. Mean Average Precision (MAP) and Normalized Discounted Cumulative Gain (NDCG) account for ranking quality.",
    tags: "IR,evaluation,metrics,precision,recall"
  },
  {
    title: "数据库索引设计最佳实践",
    source_url: "https://example.com/synthetic/index-design",
    source_page: "78-85",
    body_text: "B+Tree 索引适合等值查询和范围扫描，哈希索引仅支持等值查询。联合索引遵循最左前缀原则。覆盖索引可以避免回表查询。全文索引使用倒排结构，支持自然语言和布尔模式搜索。索引选择需权衡查询性能与写入开销。",
    tags: "数据库,索引,B+Tree,性能优化"
  }
];

module.exports = { SAMPLE_DATA };
