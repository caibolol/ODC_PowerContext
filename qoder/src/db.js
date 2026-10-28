let pool = null;
let connectionStatus = { connected: false, error: null, lastCheck: null };

function backendMode() {
  return process.env.DB_MODE || 'embedded';
}

async function getPool() {
  if (pool) return pool;
  if (backendMode() === 'server') {
    const mysql = require('mysql2/promise');
    pool = mysql.createPool({
      host: process.env.DB_HOST || '127.0.0.1',
      port: parseInt(process.env.DB_PORT || '2881', 10),
      database: process.env.DB_NAME || 'test',
      user: process.env.DB_USER || 'root',
      password: process.env.DB_PASSWORD || '',
      waitForConnections: true,
      connectionLimit: 10,
      queueLimit: 0,
      connectTimeout: 10000,
      charset: 'utf8mb4'
    });
  } else {
    pool = await require('./embedded').getDriver();
  }
  return pool;
}

async function checkConnection() {
  try {
    const p = await getPool();
    const conn = await p.getConnection();
    await conn.ping();
    conn.release();
    connectionStatus = { connected: true, error: null, lastCheck: new Date().toISOString() };
    return true;
  } catch (err) {
    connectionStatus = { connected: false, error: err.message, lastCheck: new Date().toISOString() };
    return false;
  }
}

function getConnectionStatus() {
  return {
    ...connectionStatus,
    mode: backendMode(),
    config: backendMode() === 'server' ? {
      host: process.env.DB_HOST || '127.0.0.1',
      port: parseInt(process.env.DB_PORT || '2881', 10),
      database: process.env.DB_NAME || 'test',
      user: process.env.DB_USER || 'root'
    } : {
      engine: 'seekdb embedded (in-process SQL engine)',
      dir: process.env.EMBEDDED_DB_DIR || '.evidencedesk-seekdb',
      database: process.env.DB_NAME || 'test'
    }
  };
}

const FULLTEXT_PARSERS = ['ik', 'beng'];

function parseFulltextIndexes(ddl) {
  const indexes = {};
  const regex = /FULLTEXT KEY `([^`]+)` \(([^)]+)\)(?: WITH PARSER (\w+))?/gi;
  let match;
  while ((match = regex.exec(ddl)) !== null) {
    indexes[match[1]] = {
      column: match[2].replace(/`/g, '').trim(),
      parser: match[3] ? match[3].toLowerCase() : null
    };
  }
  return indexes;
}

async function ensureFulltextIndex(conn, indexName, column) {
  const [ddlRows] = await conn.query('SHOW CREATE TABLE odc_qoder_excerpts');
  const indexes = parseFulltextIndexes(ddlRows[0]['Create Table']);
  const existing = indexes[indexName];

  if (existing && FULLTEXT_PARSERS.includes(existing.parser) && existing.column === column) {
    console.log(`[DB] FULLTEXT index ${indexName} on ${column} uses parser ${existing.parser}`);
    return existing.parser;
  }

  if (existing) {
    console.log(`[DB] Rebuilding FULLTEXT index ${indexName} (previous parser: ${existing.parser || 'default'})`);
    await conn.query(`ALTER TABLE odc_qoder_excerpts DROP INDEX \`${indexName}\``);
  }

  let lastError = null;
  for (const parser of FULLTEXT_PARSERS) {
    try {
      await conn.query(
        `ALTER TABLE odc_qoder_excerpts ADD FULLTEXT INDEX \`${indexName}\` (${column}) WITH PARSER ${parser}`
      );
      console.log(`[DB] Created FULLTEXT index ${indexName} on ${column} with parser ${parser}`);
      return parser;
    } catch (err) {
      lastError = err;
      console.warn(`[DB] FULLTEXT parser ${parser} unavailable for ${indexName}: ${err.message}`);
    }
  }

  throw new Error(
    `无法为 ${column} 创建 FULLTEXT 索引 ${indexName}：seekdb 未提供可用的 IK/BENG 解析器（${lastError?.message || 'unknown error'}）`
  );
}

async function initDatabase() {
  const p = await getPool();
  const conn = await p.getConnection();

  try {
    await conn.execute(`
      CREATE TABLE IF NOT EXISTS odc_qoder_excerpts (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(500) NOT NULL,
        source_url VARCHAR(1000),
        source_page VARCHAR(100),
        body_text TEXT NOT NULL,
        tags VARCHAR(1000),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_tags (tags(255)),
        INDEX idx_created (created_at)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    `);

    await conn.execute(`
      CREATE TABLE IF NOT EXISTS odc_qoder_review_states (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        excerpt_id BIGINT NOT NULL,
        state ENUM('unread', 'read', 'review', 'mastered') DEFAULT 'unread',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_excerpt (excerpt_id),
        CONSTRAINT fk_review_excerpt FOREIGN KEY (excerpt_id)
          REFERENCES odc_qoder_excerpts(id) ON DELETE CASCADE
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    `);

    await ensureFulltextIndex(conn, 'ft_body', 'body_text');
    await ensureFulltextIndex(conn, 'ft_title', 'title');

    console.log('[DB] Database schema initialized');
  } finally {
    conn.release();
  }
}

async function createExcerpt({ title, source_url, source_page, body_text, tags }) {
  const p = await getPool();
  const [result] = await p.execute(
    `INSERT INTO odc_qoder_excerpts (title, source_url, source_page, body_text, tags)
     VALUES (?, ?, ?, ?, ?)`,
    [title, source_url || null, source_page || null, body_text, tags || null]
  );
  return result.insertId;
}

async function getExcerpt(id) {
  const p = await getPool();
  const [rows] = await p.execute(
    `SELECT e.*, COALESCE(r.state, 'unread') AS state, r.notes as review_notes
     FROM odc_qoder_excerpts e
     LEFT JOIN odc_qoder_review_states r ON e.id = r.excerpt_id
     WHERE e.id = ?`,
    [id]
  );
  return rows[0] || null;
}

async function listExcerpts({ limit = 50, offset = 0, tag, state } = {}) {
  const p = await getPool();
  let sql = `SELECT e.*, COALESCE(r.state, 'unread') AS state, r.notes as review_notes
             FROM odc_qoder_excerpts e
             LEFT JOIN odc_qoder_review_states r ON e.id = r.excerpt_id`;
  const params = [];
  const conditions = [];

  if (tag) {
    conditions.push('FIND_IN_SET(?, e.tags)');
    params.push(tag);
  }
  if (state) {
    conditions.push("COALESCE(r.state, 'unread') = ?");
    params.push(state);
  }

  if (conditions.length > 0) {
    sql += ' WHERE ' + conditions.join(' AND ');
  }

  sql += ' ORDER BY e.created_at DESC LIMIT ? OFFSET ?';
  params.push(limit, offset);

  const [rows] = await p.execute(sql, params);
  return rows;
}

async function searchExcerpts(query, { limit = 50, tag, state } = {}) {
  const p = await getPool();

  let sql = `SELECT e.*,
             MATCH(e.body_text) AGAINST(? IN NATURAL LANGUAGE MODE) as body_score,
             MATCH(e.title) AGAINST(? IN NATURAL LANGUAGE MODE) as title_score,
             COALESCE(r.state, 'unread') AS state, r.notes as review_notes
             FROM odc_qoder_excerpts e
             LEFT JOIN odc_qoder_review_states r ON e.id = r.excerpt_id
             WHERE (MATCH(e.body_text) AGAINST(? IN NATURAL LANGUAGE MODE)
                    OR MATCH(e.title) AGAINST(? IN NATURAL LANGUAGE MODE))`;

  const params = [query, query, query, query];
  const conditions = [];

  if (tag) {
    conditions.push('FIND_IN_SET(?, e.tags)');
    params.push(tag);
  }
  if (state) {
    conditions.push("COALESCE(r.state, 'unread') = ?");
    params.push(state);
  }

  if (conditions.length > 0) {
    sql += ' AND ' + conditions.join(' AND ');
  }

  sql += ' ORDER BY (title_score * 2 + body_score) DESC LIMIT ?';
  params.push(limit);

  const [rows] = await p.execute(sql, params);
  // 页面、导出与数据库排序使用相同的标题权重。
  return rows.map(row => ({
    ...row,
    relevance_score: Number(row.body_score || 0) + 2 * Number(row.title_score || 0)
  }));
}

async function updateReviewState(excerptId, state, notes) {
  const p = await getPool();
  await p.execute(
    `INSERT INTO odc_qoder_review_states (excerpt_id, state, notes)
     VALUES (?, ?, ?)
     ON DUPLICATE KEY UPDATE state = VALUES(state), notes = VALUES(notes)`,
    [excerptId, state, notes || null]
  );
  return true;
}

async function getReviewState(excerptId) {
  const p = await getPool();
  const [rows] = await p.execute(
    `SELECT * FROM odc_qoder_review_states WHERE excerpt_id = ?`,
    [excerptId]
  );
  return rows[0] || null;
}

async function getStats() {
  const p = await getPool();
  const [rows] = await p.execute(`
    SELECT
      COUNT(*) as total,
      COALESCE(SUM(CASE WHEN COALESCE(r.state, 'unread') = 'unread' THEN 1 ELSE 0 END), 0) as unread_count,
      COALESCE(SUM(CASE WHEN r.state = 'read' THEN 1 ELSE 0 END), 0) as read_count,
      COALESCE(SUM(CASE WHEN r.state = 'review' THEN 1 ELSE 0 END), 0) as review_count,
      COALESCE(SUM(CASE WHEN r.state = 'mastered' THEN 1 ELSE 0 END), 0) as mastered_count
    FROM odc_qoder_excerpts e
    LEFT JOIN odc_qoder_review_states r ON e.id = r.excerpt_id
  `);

  return {
    excerpts: Number(rows[0].total),
    reviews: {
      total: Number(rows[0].total),
      unread: Number(rows[0].unread_count),
      read: Number(rows[0].read_count),
      review: Number(rows[0].review_count),
      mastered: Number(rows[0].mastered_count)
    }
  };
}

async function deleteExcerpt(id) {
  const p = await getPool();
  const [result] = await p.execute('DELETE FROM odc_qoder_excerpts WHERE id = ?', [id]);
  return result.affectedRows > 0;
}

async function closePool() {
  if (pool) {
    await pool.end();
    pool = null;
  }
}

module.exports = {
  getPool,
  backendMode,
  checkConnection,
  getConnectionStatus,
  initDatabase,
  createExcerpt,
  getExcerpt,
  listExcerpts,
  searchExcerpts,
  updateReviewState,
  getReviewState,
  getStats,
  deleteExcerpt,
  closePool
};
