require('dotenv').config();
const express = require('express');
const path = require('path');
const db = require('./db');
const { SAMPLE_DATA } = require('./sample-data');

const app = express();
const PORT = parseInt(process.env.PORT || '18748');
const HOST = process.env.HOST || '127.0.0.1';

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, '..', 'public')));

app.use((err, req, res, next) => {
  console.error('[Error]', err.message);
  res.status(500).json({ error: '服务器内部错误', detail: err.message });
});

app.get('/api/health', async (req, res) => {
  const connected = await db.checkConnection();
  const status = db.getConnectionStatus();
  res.json({
    status: connected ? 'ok' : 'error',
    database: status,
    timestamp: new Date().toISOString()
  });
});

app.get('/api/stats', async (req, res) => {
  try {
    const connected = await db.checkConnection();
    if (!connected) {
      return res.status(503).json({ error: '数据库连接失败', detail: db.getConnectionStatus().error });
    }
    const stats = await db.getStats();
    res.json({ connected: true, ...stats });
  } catch (err) {
    res.status(500).json({ error: '获取统计失败', detail: err.message });
  }
});

app.post('/api/excerpts', async (req, res) => {
  try {
    const { title, source_url, source_page, body_text, tags } = req.body;

    if (!title || typeof title !== 'string' || title.trim().length === 0) {
      return res.status(400).json({ error: '标题不能为空' });
    }
    if (title.length > 500) {
      return res.status(400).json({ error: '标题不能超过500字' });
    }
    if (!body_text || typeof body_text !== 'string' || body_text.trim().length === 0) {
      return res.status(400).json({ error: '正文摘录不能为空' });
    }
    if (body_text.length > 20000) {
      return res.status(400).json({ error: '正文摘录不能超过20000字' });
    }
    if (source_url !== undefined && source_url !== null && typeof source_url !== 'string') {
      return res.status(400).json({ error: '来源URL类型不正确' });
    }
    if (source_url && source_url.length > 1000) {
      return res.status(400).json({ error: '来源URL不能超过1000字符' });
    }
    if (source_url && !/^https?:\/\/.+/i.test(source_url) && source_url.trim().length > 0) {
      return res.status(400).json({ error: '来源URL格式不正确' });
    }
    if (source_page !== undefined && source_page !== null && typeof source_page !== 'string') {
      return res.status(400).json({ error: '页码类型不正确' });
    }
    if (source_page && source_page.length > 100) {
      return res.status(400).json({ error: '页码不能超过100字符' });
    }
    if (tags !== undefined && tags !== null && typeof tags !== 'string') {
      return res.status(400).json({ error: '标签类型不正确' });
    }
    if (tags && tags.length > 1000) {
      return res.status(400).json({ error: '标签不能超过1000字符' });
    }

    const id = await db.createExcerpt({
      title: title.trim(),
      source_url: source_url?.trim() || null,
      source_page: source_page?.trim() || null,
      body_text: body_text.trim(),
      tags: tags?.trim() || null
    });

    res.status(201).json({ id, message: '创建成功' });
  } catch (err) {
    res.status(500).json({ error: '创建失败', detail: err.message });
  }
});

app.get('/api/excerpts', async (req, res) => {
  try {
    const { limit = 50, offset = 0, tag, state } = req.query;
    const excerpts = await db.listExcerpts({
      limit: Math.min(parseInt(limit) || 50, 200),
      offset: parseInt(offset) || 0,
      tag: tag || null,
      state: state || null
    });
    res.json({ data: excerpts });
  } catch (err) {
    res.status(500).json({ error: '获取列表失败', detail: err.message });
  }
});

app.get('/api/excerpts/:id', async (req, res) => {
  try {
    const excerpt = await db.getExcerpt(parseInt(req.params.id));
    if (!excerpt) {
      return res.status(404).json({ error: '未找到该记录' });
    }
    res.json(excerpt);
  } catch (err) {
    res.status(500).json({ error: '获取详情失败', detail: err.message });
  }
});

app.delete('/api/excerpts/:id', async (req, res) => {
  try {
    const deleted = await db.deleteExcerpt(parseInt(req.params.id));
    if (!deleted) {
      return res.status(404).json({ error: '未找到该记录' });
    }
    res.json({ message: '删除成功' });
  } catch (err) {
    res.status(500).json({ error: '删除失败', detail: err.message });
  }
});

app.get('/api/search', async (req, res) => {
  try {
    const { q, limit = 50, tag, state } = req.query;

    if (!q || typeof q !== 'string' || q.trim().length === 0) {
      return res.status(400).json({ error: '搜索关键词不能为空' });
    }
    if (q.length > 200) {
      return res.status(400).json({ error: '搜索关键词不能超过200字' });
    }

    const results = await db.searchExcerpts(q.trim(), {
      limit: Math.min(parseInt(limit) || 50, 200),
      tag: tag || null,
      state: state || null
    });

    res.json({
      query: q.trim(),
      count: results.length,
      data: results
    });
  } catch (err) {
    res.status(500).json({ error: '搜索失败', detail: err.message });
  }
});

app.put('/api/excerpts/:id/review', async (req, res) => {
  try {
    const { state, notes } = req.body;
    const validStates = ['unread', 'read', 'review', 'mastered'];

    if (!state || !validStates.includes(state)) {
      return res.status(400).json({ error: '无效的复习状态', valid: validStates });
    }
    if (notes !== undefined && notes !== null && typeof notes !== 'string') {
      return res.status(400).json({ error: '备注类型不正确' });
    }
    if (notes && notes.length > 5000) {
      return res.status(400).json({ error: '备注不能超过5000字' });
    }

    const excerpt = await db.getExcerpt(parseInt(req.params.id));
    if (!excerpt) {
      return res.status(404).json({ error: '未找到该记录' });
    }

    await db.updateReviewState(parseInt(req.params.id), state, notes?.trim() || null);
    res.json({ message: '更新成功' });
  } catch (err) {
    res.status(500).json({ error: '更新失败', detail: err.message });
  }
});

app.get('/api/excerpts/:id/review', async (req, res) => {
  try {
    const review = await db.getReviewState(parseInt(req.params.id));
    res.json(review || { state: 'unread', notes: null });
  } catch (err) {
    res.status(500).json({ error: '获取复习状态失败', detail: err.message });
  }
});

app.post('/api/import-sample', async (req, res) => {
  try {
    const connected = await db.checkConnection();
    if (!connected) {
      return res.status(503).json({ error: '数据库连接失败', detail: db.getConnectionStatus().error });
    }

    let imported = 0;
    for (const item of SAMPLE_DATA) {
      try {
        const tags = item.tags ? `${item.tags},合成教学样例` : '合成教学样例';
        await db.createExcerpt({ ...item, tags });
        imported++;
      } catch (err) {
        console.warn('[Import] Failed to import:', item.title, err.message);
      }
    }

    res.json({
      message: `成功导入 ${imported}/${SAMPLE_DATA.length} 条合成教学样例`,
      imported,
      total: SAMPLE_DATA.length,
      disclaimer: '所有数据均为合成教学样例，example.com 为占位来源，不是真实文献或真实用户数据'
    });
  } catch (err) {
    res.status(500).json({ error: '导入失败', detail: err.message });
  }
});

function isSyntheticExcerpt(item) {
  const haystack = `${item.source_url || ''} ${item.tags || ''}`.toLowerCase();
  return haystack.includes('example.com') || haystack.includes('synthetic') || haystack.includes('合成教学样例');
}

app.get('/api/export', async (req, res) => {
  try {
    const { q, tag, state } = req.query;
    let results = [];

    if (q && q.trim().length > 0) {
      results = await db.searchExcerpts(q.trim(), {
        limit: 200,
        tag: tag || null,
        state: state || null
      });
    } else {
      results = await db.listExcerpts({
        limit: 200,
        tag: tag || null,
        state: state || null
      });
    }

    const hasSynthetic = results.some(isSyntheticExcerpt);

    let markdown = '# 研读档案证据清单\n\n';
    markdown += `导出时间: ${new Date().toLocaleString('zh-CN')}\n`;
    markdown += `记录数: ${results.length}\n\n`;

    if (hasSynthetic) {
      markdown += '> **数据性质说明**：本清单包含合成教学样例，example.com 为占位来源，不是真实文献或真实用户数据。带“合成教学样例 · 占位来源 · 非真实文献”标记的条目仅用于演示。\n\n';
    }

    if (q) {
      markdown += `搜索关键词: ${q.trim()}\n\n`;
    }

    markdown += '---\n\n';

    results.forEach((item, idx) => {
      markdown += `## ${idx + 1}. ${item.title}\n\n`;
      if (isSyntheticExcerpt(item)) {
        markdown += '- **数据性质**: 合成教学样例 · example.com 为占位来源 · 非真实文献\n';
      }
      if (item.source_url) {
        markdown += `- **来源**: [${item.source_url}](${item.source_url})\n`;
      }
      if (item.source_page) {
        markdown += `- **页码**: ${item.source_page}\n`;
      }
      if (item.tags) {
        markdown += `- **标签**: ${item.tags}\n`;
      }
      if (item.state) {
        const stateMap = { unread: '未读', read: '已读', review: '待复习', mastered: '已掌握' };
        markdown += `- **状态**: ${stateMap[item.state] || item.state}\n`;
      }
      if (item.review_notes) {
        markdown += `- **备注**: ${item.review_notes}\n`;
      }
      markdown += `\n### 摘录内容\n\n${item.body_text}\n\n`;
      if (item.body_score !== undefined) {
        markdown += `*相关度: ${(item.body_score + (item.title_score || 0)).toFixed(4)}*\n\n`;
      }
      markdown += '---\n\n';
    });

    res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
    res.setHeader('Content-Disposition', `attachment; filename="evidence-${Date.now()}.md"`);
    res.send(markdown);
  } catch (err) {
    res.status(500).json({ error: '导出失败', detail: err.message });
  }
});

async function start() {
  console.log('[EvidenceDesk] Starting server...');

  const connected = await db.checkConnection();
  if (!connected) {
    console.error('[EvidenceDesk] Database connection failed:', db.getConnectionStatus().error);
    console.error('[EvidenceDesk] Please check your database configuration in .env file');
    process.exit(1);
  }

  console.log('[EvidenceDesk] Database connected successfully');

  await db.initDatabase();
  console.log('[EvidenceDesk] Database schema initialized');

  app.listen(PORT, HOST, () => {
    console.log(`[EvidenceDesk] Server running at http://${HOST}:${PORT}`);
    console.log('[EvidenceDesk] Press Ctrl+C to stop');
  });
}

if (require.main === module) {
  start().catch(err => {
    console.error('[EvidenceDesk] Failed to start:', err);
    process.exit(1);
  });
}

module.exports = app;
