import { MySqlClient, bindString, bindInt, type SocketLike } from "./mysqlc.ts";

export interface DbOpts {
  hostname: string;
  port: number;
  user: string;
  password: string;
  database: string;
}

export function parseDsn(dsn: string): DbOpts {
  const u = new URL(dsn);
  return {
    hostname: u.hostname,
    port: u.port ? Number(u.port) : 2881,
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    database: u.pathname.replace(/^\//, ""),
  };
}

export const SAMPLE_DATA = [
  { title: "OceanBase 分布式数据库架构设计", source_url: "https://example.com/synthetic/oceanbase-arch", source_page: "12-15", body_text: "OceanBase 采用 shared-nothing 架构，每个节点运行完整的数据库引擎副本。数据通过多副本 Paxos 协议保持一致性，支持强同步和异步复制模式。Zone 是物理隔离单元，Region 用于跨地域容灾。", tags: "数据库,分布式,OceanBase,架构" },
  { title: "Introduction to Full-Text Search in MySQL", source_url: "https://example.com/synthetic/mysql-ft", source_page: "45-48", body_text: "MySQL full-text search uses inverted indexes to efficiently locate documents containing specific terms. The MATCH() function with AGAINST() clause supports natural language mode and boolean mode. Relevance ranking is computed using term frequency and inverse document frequency.", tags: "MySQL,fulltext,search,index" },
  { title: "Paxos 共识算法原理与实践", source_url: "https://example.com/synthetic/paxos", source_page: "23-30", body_text: "Paxos 算法分为 Proposer、Acceptor 和 Learner 三种角色。Prepare 阶段获取提案编号承诺，Accept 阶段确认实际提案。Multi-Paxos 通过固定 Leader 减少通信轮次，是分布式数据库一致性的基础协议。", tags: "分布式,共识,Paxos,算法" },
  { title: "Research Methods for Literature Review", source_url: "https://example.com/synthetic/lit-review", source_page: "8-11", body_text: "Systematic literature review requires clear research questions, inclusion/exclusion criteria, and reproducible search strategies. Evidence synthesis involves coding themes across studies, assessing quality, and identifying gaps. Tools like Zotero and NVivo help organize sources and annotations.", tags: "research,methodology,literature,review" },
  { title: "SQL 注入攻击与防御技术", source_url: "https://example.com/synthetic/sql-injection", source_page: "67-72", body_text: "SQL 注入通过在用户输入中嵌入恶意 SQL 片段来操纵数据库查询。防御手段包括参数化查询（预编译语句）、输入验证白名单、最小权限原则和 WAF 规则。参数绑定是最根本的防御方式，它将数据与指令分离。", tags: "安全,SQL注入,防御,参数化" },
  { title: "LSM-Tree 存储引擎详解", source_url: "https://example.com/synthetic/lsm-tree", source_page: "34-40", body_text: "LSM-Tree 将随机写转换为顺序写，通过 MemTable、SSTable 和 Compaction 三层结构实现高吞吐写入。读取时需合并多层数据，可能产生读放大。Leveled Compaction 和 Tiered Compaction 是两种主流策略，分别优化读性能和写性能。", tags: "存储引擎,LSM-Tree,数据库,性能" },
  { title: "Academic Writing and Citation Practices", source_url: "https://example.com/synthetic/academic-writing", source_page: "15-18", body_text: "Proper citation avoids plagiarism and strengthens academic arguments. APA, MLA, and Chicago styles each have specific rules for in-text citations and reference lists. When quoting directly, include page numbers. Paraphrasing still requires attribution to the original source.", tags: "academic,writing,citation,ethics" },
  { title: "OceanBase 事务处理与 MVCC 机制", source_url: "https://example.com/synthetic/oceanbase-txn", source_page: "56-63", body_text: "OceanBase 支持行级锁和乐观锁两种并发控制模式。MVCC 通过多版本数据实现读写不冲突，每个事务看到一致性快照。事务日志持久化到 Clog 中，通过 Paxos 协议在副本间同步，确保 RPO=0 的金融级数据可靠性。", tags: "OceanBase,事务,MVCC,并发控制" },
  { title: "Information Retrieval Evaluation Metrics", source_url: "https://example.com/synthetic/ir-metrics", source_page: "92-98", body_text: "Precision measures the fraction of retrieved documents that are relevant, while recall measures the fraction of relevant documents that are retrieved. F1 score balances both. Mean Average Precision (MAP) and Normalized Discounted Cumulative Gain (NDCG) account for ranking quality.", tags: "IR,evaluation,metrics,precision,recall" },
  { title: "数据库索引设计最佳实践", source_url: "https://example.com/synthetic/index-design", source_page: "78-85", body_text: "B+Tree 索引适合等值查询和范围扫描，哈希索引仅支持等值查询。联合索引遵循最左前缀原则。覆盖索引可以避免回表查询。全文索引使用倒排结构，支持自然语言和布尔模式搜索。索引选择需权衡查询性能与写入开销。", tags: "数据库,索引,B+Tree,性能优化" },
];

export class Store {
  private client: MySqlClient;
  constructor(client: MySqlClient) { this.client = client; }

  static async open(opts: DbOpts, connect: (host: string, port: number) => Promise<SocketLike>, subtle: SubtleCrypto): Promise<Store> {
    const sock = await connect(opts.hostname, opts.port);
    const client = new MySqlClient(sock, subtle);
    await client.connect(opts);
    return new Store(client);
  }

  async ensureSchema(): Promise<void> {
    await this.client.query(`
      CREATE TABLE IF NOT EXISTS odc_qoder_excerpts (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(500) NOT NULL,
        source_url VARCHAR(1000),
        source_page VARCHAR(100),
        body_text TEXT NOT NULL,
        tags VARCHAR(1000),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FULLTEXT KEY ft_body (body_text) WITH PARSER ik,
        FULLTEXT KEY ft_title (title) WITH PARSER ik
      ) DEFAULT CHARSET=utf8mb4
    `);
    await this.client.query(`
      CREATE TABLE IF NOT EXISTS odc_qoder_review_states (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        excerpt_id BIGINT NOT NULL,
        state VARCHAR(16) DEFAULT 'unread',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_excerpt (excerpt_id)
      ) DEFAULT CHARSET=utf8mb4
    `);
  }

  async count(): Promise<number> {
    const r = await this.client.query("SELECT COUNT(*) AS n FROM odc_qoder_excerpts");
    return Number(r.rows[0].n || 0);
  }

  async seedIfEmpty(): Promise<number> {
    if (await this.count() > 0) return 0;
    let added = 0;
    for (const s of SAMPLE_DATA) {
      await this.client.query(
        `INSERT INTO odc_qoder_excerpts (title, source_url, source_page, body_text, tags)
         VALUES (${bindString(s.title)}, ${bindString(s.source_url)}, ${bindString(s.source_page)}, ${bindString(s.body_text)}, ${bindString(s.tags)})`
      );
      added++;
    }
    return added;
  }

  private filters(tag?: string | null, state?: string | null): string {
    const conds: string[] = [];
    if (tag) conds.push(`FIND_IN_SET(${bindString(tag)}, e.tags)`);
    if (state) conds.push(`COALESCE(r.state, 'unread') = ${bindString(state)}`);
    return conds.length ? " WHERE " + conds.join(" AND ") : "";
  }

  private readonly selectBase = `SELECT e.id, e.title, e.source_url, e.source_page, e.body_text, e.tags, e.created_at,
             COALESCE(r.state, 'unread') AS state, r.notes AS review_notes
             FROM odc_qoder_excerpts e LEFT JOIN odc_qoder_review_states r ON e.id = r.excerpt_id`;

  async list(tag?: string | null, state?: string | null, limit = 50): Promise<Record<string, any>[]> {
    const r = await this.client.query(`${this.selectBase}${this.filters(tag, state)} ORDER BY e.id DESC LIMIT ${bindInt(limit)}`);
    return r.rows;
  }

  async search(q: string, tag?: string | null, state?: string | null, limit = 50): Promise<Record<string, any>[]> {
    const qb = bindString(q);
    const r = await this.client.query(
      `SELECT e.id, e.title, e.source_url, e.source_page, e.body_text, e.tags, e.created_at,
              COALESCE(rr.state, 'unread') AS state, rr.notes AS review_notes,
              MATCH(e.body_text) AGAINST(${qb} IN NATURAL LANGUAGE MODE) AS body_score,
              MATCH(e.title) AGAINST(${qb} IN NATURAL LANGUAGE MODE) AS title_score
       FROM odc_qoder_excerpts e LEFT JOIN odc_qoder_review_states rr ON e.id = rr.excerpt_id
       WHERE (MATCH(e.body_text) AGAINST(${qb} IN NATURAL LANGUAGE MODE)
              OR MATCH(e.title) AGAINST(${qb} IN NATURAL LANGUAGE MODE))${this.filters(tag, state).replace(/ WHERE/, " AND")}
       ORDER BY (title_score * 2 + body_score) DESC LIMIT ${bindInt(limit)}`
    );
    return r.rows.map(row => ({
      ...row,
      relevance_score: Number(row.body_score || 0) + 2 * Number(row.title_score || 0),
    }));
  }

  async create(f: { title: string; source_url?: string | null; source_page?: string | null; body_text: string; tags?: string | null }): Promise<number> {
    const r = await this.client.query(
      `INSERT INTO odc_qoder_excerpts (title, source_url, source_page, body_text, tags)
       VALUES (${bindString(f.title)}, ${bindString(f.source_url)}, ${bindString(f.source_page)}, ${bindString(f.body_text)}, ${bindString(f.tags)})`
    );
    return r.insertId;
  }

  async get(id: number): Promise<Record<string, any> | null> {
    const r = await this.client.query(`${this.selectBase} WHERE e.id = ${bindInt(id)}`);
    return r.rows[0] || null;
  }

  async remove(id: number): Promise<boolean> {
    await this.client.query(`DELETE FROM odc_qoder_review_states WHERE excerpt_id = ${bindInt(id)}`);
    const r = await this.client.query(`DELETE FROM odc_qoder_excerpts WHERE id = ${bindInt(id)}`);
    return r.affectedRows > 0;
  }

  async setReview(id: number, state: string, notes: string | null): Promise<void> {
    await this.client.query(
      `INSERT INTO odc_qoder_review_states (excerpt_id, state, notes)
       VALUES (${bindInt(id)}, ${bindString(state)}, ${bindString(notes)})
       ON DUPLICATE KEY UPDATE state = ${bindString(state)}, notes = ${bindString(notes)}`
    );
  }

  async getReview(id: number): Promise<Record<string, any> | null> {
    const r = await this.client.query(`SELECT excerpt_id, state, notes FROM odc_qoder_review_states WHERE excerpt_id = ${bindInt(id)}`);
    return r.rows[0] || null;
  }

  async stats(): Promise<Record<string, number>> {
    const r = await this.client.query(`
      SELECT COUNT(*) AS total,
        COALESCE(SUM(CASE WHEN COALESCE(r.state,'unread')='unread' THEN 1 ELSE 0 END),0) AS unread_count,
        COALESCE(SUM(CASE WHEN r.state='read' THEN 1 ELSE 0 END),0) AS read_count,
        COALESCE(SUM(CASE WHEN r.state='review' THEN 1 ELSE 0 END),0) AS review_count,
        COALESCE(SUM(CASE WHEN r.state='mastered' THEN 1 ELSE 0 END),0) AS mastered_count
      FROM odc_qoder_excerpts e LEFT JOIN odc_qoder_review_states r ON e.id = r.excerpt_id`);
    const row = r.rows[0];
    return { excerpts: Number(row.total), unread: Number(row.unread_count), read: Number(row.read_count), review: Number(row.review_count), mastered: Number(row.mastered_count) };
  }

  async version(): Promise<string> {
    const r = await this.client.query("SELECT VERSION() AS v");
    return String(r.rows[0].v || "");
  }

  close(): void { this.client.close(); }
}
