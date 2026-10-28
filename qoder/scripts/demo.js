// 零外部服务自检：嵌入式 seekdb（npm 原生包）跑通主要功能 + PowerContext 记忆读写。
// 用法：npm run demo（PowerContext 需先按 README 启动；确需跳过记忆层自检用 SKIP_CONTEXT=1）
process.env.DB_MODE = process.env.DB_MODE || 'embedded';

const db = require('../src/db');
const context = require('../src/context');
const { SAMPLE_DATA } = require('../src/sample-data');

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail || '' });
  console.log(`${ok ? 'PASS' : 'FAIL'} | ${name}${detail ? ' | ' + detail : ''}`);
}

(async () => {
  console.log(`[demo] backend=${db.backendMode()}（嵌入式 seekdb，数据目录 .evidencedesk-seekdb）`);

  await db.initDatabase();
  check('schema 初始化（含 IK FULLTEXT 索引）', true);

  const before = await db.listExcerpts({ limit: 100000 });
  const keys = new Set(before.map(e => `${e.title}|${e.source_url || ''}`));
  let added = 0;
  for (const s of SAMPLE_DATA) {
    if (keys.has(`${s.title}|${s.source_url}`)) continue;
    await db.createExcerpt(s);
    added++;
  }
  check('合成样例导入（幂等）', true, `新增 ${added} 条，原有 ${before.length} 条`);

  const cn = await db.searchExcerpts('分布式数据库', { limit: 10 });
  check('中文全文检索命中', cn.length > 0 && /OceanBase/.test(cn[0].title), `命中 ${cn.length} 条，首位「${cn[0] && cn[0].title}」相关度 ${(cn[0] && cn[0].relevance_score || 0).toFixed(4)}`);

  const en = await db.searchExcerpts('full-text search', { limit: 10 });
  check('英文全文检索命中', en.length > 0, `命中 ${en.length} 条`);

  const ordered = cn.every((r, i) => i === 0 || cn[i - 1].relevance_score >= r.relevance_score);
  check('相关度排序（标题权重×2 + 正文）', ordered);

  const id = await db.createExcerpt({ title: '自检临时记录', body_text: '用于自检的临时摘录 HttpApiKeyword', source_url: 'https://example.com/selftest', tags: '自检' });
  const hit = await db.searchExcerpts('HttpApiKeyword', { limit: 5 });
  check('新增立即可检索', hit.some(r => r.id === id));

  await db.updateReviewState(id, 'mastered', '自检备注');
  const rv = await db.getReviewState(id);
  check('复习状态与备注持久化', rv && rv.state === 'mastered' && rv.notes === '自检备注');

  const stats = await db.getStats();
  check('统计接口', stats.excerpts >= 10, `资料 ${stats.excerpts} 条`);

  check('删除自检记录', await db.deleteExcerpt(id));

  if (process.env.SKIP_CONTEXT === '1') {
    check('PowerContext 记忆层（SKIP_CONTEXT=1 跳过）', true, 'skipped');
  } else {
    const st = await context.status();
    check('PowerContext 连接', st.connected, st.connected ? `scope ${st.scope_id}` : st.error);
    if (st.connected) {
      const payload = { demo: true, stats, at: new Date().toISOString() };
      await context.rememberProgress(payload);
      const latest = await context.latestProgress();
      check('记忆写入并读回（跨会话复用）', latest && latest.entry && latest.entry.demo === true, latest ? `saved_at ${latest.saved_at}` : 'no entry');
    }
  }

  await db.closePool();
  const failed = results.filter(r => !r.ok);
  console.log(`\n[demo] Total: ${results.length} | Passed: ${results.length - failed.length} | Failed: ${failed.length}`);
  process.exit(failed.length ? 1 : 0);
})().catch(err => {
  console.error('[demo] 自检异常:', err.message);
  process.exit(1);
});
