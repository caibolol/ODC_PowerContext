require('dotenv').config();
const { once } = require('events');
const db = require('../src/db');

let passed = 0;
let failed = 0;
let initialCount = 0;
const results = [];

function assert(condition, message) {
  if (condition) {
    passed++;
    results.push({ test: message, status: 'PASS' });
    console.log(`  ✓ ${message}`);
  } else {
    failed++;
    results.push({ test: message, status: 'FAIL' });
    console.log(`  ✗ ${message}`);
  }
}

async function run(createdIds) {
  const createTracked = async (data) => {
    const id = await db.createExcerpt(data);
    createdIds.push(id);
    return id;
  };

  console.log('[1] Database Connection');
  const connected = await db.checkConnection();
  assert(connected, 'Database connection established');

  const status = db.getConnectionStatus();
  assert(status.connected === true, 'Connection status reports connected');
  assert(status.config.host === (process.env.DB_HOST || '127.0.0.1'), 'Config host matches');

  console.log('\n[2] Schema and Real FULLTEXT Parser');
  await db.initDatabase();
  assert(true, 'Schema initialized without errors');

  const p = await db.getPool();
  const [ddlRows] = await p.query('SHOW CREATE TABLE odc_qoder_excerpts');
  const ddlText = ddlRows[0]['Create Table'];
  assert(
    /FULLTEXT KEY `ft_body` \(`body_text`\) WITH PARSER (ik|beng)/i.test(ddlText),
    'ft_body is a single-column FULLTEXT index using seekdb IK/BENG parser'
  );
  assert(
    /FULLTEXT KEY `ft_title` \(`title`\) WITH PARSER (ik|beng)/i.test(ddlText),
    'ft_title is a single-column FULLTEXT index using seekdb IK/BENG parser'
  );
  assert(!/WITH PARSER ngram/i.test(ddlText), 'FULLTEXT indexes are not using MySQL ngram parser');

  initialCount = (await db.getStats()).excerpts;
  console.log(`  (existing excerpts preserved: ${initialCount})`);

  console.log('\n[3] CRUD and Default Unread State');
  const stamp = Date.now();
  const englishTitle = 'Integration Test Excerpt ' + stamp;
  const englishBody = 'OceanBase fulltext relevance integration verification with a unique English marker.';
  const englishId = await createTracked({
    title: englishTitle,
    source_url: 'https://example.org/integration-test',
    source_page: '1-5',
    body_text: englishBody,
    tags: 'test,integration'
  });
  assert(englishId > 0, `Created excerpt with id ${englishId}`);

  const retrieved = await db.getExcerpt(englishId);
  assert(retrieved !== null, 'Retrieved excerpt by id');
  assert(retrieved.title === englishTitle, 'Title matches');
  assert(retrieved.body_text === englishBody, 'Body text matches');
  assert(retrieved.source_url === 'https://example.org/integration-test', 'Source URL matches');
  assert(retrieved.state === 'unread', 'New excerpt without review row is treated as unread');

  const unreadList = await db.listExcerpts({ state: 'unread', limit: 200 });
  assert(unreadList.some(e => e.id === englishId), 'Unread filter includes excerpt without review row');

  const list = await db.listExcerpts({ limit: 200 });
  assert(list.some(e => e.id === englishId), 'New excerpt appears in list');

  console.log('\n[4] English Full-Text Search');
  const englishHits = await db.searchExcerpts('relevance');
  const englishHit = englishHits.find(r => r.id === englishId);
  assert(englishHit !== undefined, 'English FULLTEXT search found the exact test ID');
  assert(englishHit && englishHit.body_score > 0, 'English hit has positive body relevance score');

  console.log('\n[5] Chinese Full-Text Search');
  const chineseText = '分布式数据库的一致性依赖 Paxos 共识协议，中文全文检索应当命中该条目。';
  const chineseId = await createTracked({
    title: '中文检索验证条目 ' + stamp,
    source_url: 'https://example.org/zh-check',
    source_page: '7',
    body_text: chineseText,
    tags: '中文检索,测试'
  });
  const chineseHits = await db.searchExcerpts('分布式数据库');
  const chineseHit = chineseHits.find(r => r.id === chineseId);
  assert(chineseHit !== undefined, 'Chinese FULLTEXT search found the exact inserted Chinese ID');
  assert(
    chineseHit && (chineseHit.body_score > 0 || chineseHit.title_score > 0),
    'Chinese hit has positive relevance score'
  );

  const paxosHits = await db.searchExcerpts('Paxos');
  assert(paxosHits.some(r => r.id === chineseId), 'Mixed Chinese/English term Paxos found the Chinese excerpt');

  console.log('\n[6] Title Index Search');
  const titleOnlyId = await createTracked({
    title: 'ZetaKeyword TitleOnly ' + stamp,
    source_url: 'https://example.org/title-check',
    body_text: 'This body deliberately omits the special search marker.',
    tags: 'title-check,测试'
  });
  const titleHits = await db.searchExcerpts('ZetaKeyword');
  const titleHit = titleHits.find(r => r.id === titleOnlyId);
  assert(titleHit !== undefined, 'Title-only keyword found through title FULLTEXT index');
  assert(titleHit && titleHit.title_score > 0, 'Title hit has positive title relevance score');

  console.log('\n[7] Review State and Reconnect Persistence');
  await db.updateReviewState(englishId, 'read', '第一轮复习备注');
  const reviewState = await db.getReviewState(englishId);
  assert(reviewState !== null && reviewState.state === 'read', 'State saved as read');
  assert(reviewState.notes === '第一轮复习备注', 'Review notes saved');

  await db.closePool();
  const afterReconnect = await db.getExcerpt(englishId);
  assert(
    afterReconnect && afterReconnect.state === 'read' && afterReconnect.review_notes === '第一轮复习备注',
    'State and notes persist after closing and reopening the connection pool'
  );

  await db.updateReviewState(englishId, 'mastered', '已掌握备注');
  const mastered = await db.getExcerpt(englishId);
  assert(mastered.state === 'mastered', 'State updated to mastered');
  assert(mastered.review_notes === '已掌握备注', 'Notes updated to mastered note');

  console.log('\n[8] Filters and Unread Statistics');
  const masteredList = await db.listExcerpts({ state: 'mastered', limit: 200 });
  assert(masteredList.some(e => e.id === englishId), 'Mastered filter includes reviewed excerpt');

  const unreadAfter = await db.listExcerpts({ state: 'unread', limit: 200 });
  assert(unreadAfter.some(e => e.id === chineseId), 'Unread filter includes Chinese excerpt without review row');
  assert(unreadAfter.some(e => e.id === titleOnlyId), 'Unread filter includes title-only excerpt without review row');
  assert(!unreadAfter.some(e => e.id === englishId), 'Unread filter excludes mastered excerpt');

  const tagList = await db.listExcerpts({ tag: '中文检索', limit: 200 });
  assert(tagList.some(e => e.id === chineseId), 'Tag filter found Chinese excerpt');

  const taggedSearch = await db.searchExcerpts('分布式数据库', { tag: '中文检索' });
  assert(taggedSearch.some(r => r.id === chineseId), 'FULLTEXT search with tag filter found Chinese excerpt');

  const stats = await db.getStats();
  assert(stats.reviews.total === stats.excerpts, 'Stats total equals excerpt count');
  assert(stats.reviews.unread >= 2, `Stats unread includes rows without review state (${stats.reviews.unread})`);
  assert(stats.reviews.mastered >= 1, `Stats mastered count is at least 1 (${stats.reviews.mastered})`);

  console.log('\n[9] SQL Injection Safety');
  const injectionTitle = "Test'; DROP TABLE odc_qoder_excerpts; --";
  const injectionId = await createTracked({
    title: injectionTitle,
    body_text: "Injection body ' OR '1'='1",
    tags: 'test'
  });
  assert(injectionId > 0, 'Injection text safely stored as data');
  const injectionRetrieved = await db.getExcerpt(injectionId);
  assert(injectionRetrieved.title === injectionTitle, 'Injection text preserved verbatim, not executed');

  const injectionSearch = await db.searchExcerpts("' OR '1'='1");
  assert(Array.isArray(injectionSearch), 'Injection search query handled safely');
  assert((await db.getExcerpt(englishId)) !== null, 'Original table and data intact after injection attempt');

  console.log('\n[10] HTTP API Input Validation');
  const app = require('../src/server');
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const baseUrl = `http://127.0.0.1:${server.address().port}`;

  const httpJson = async (path, options = {}) => {
    const response = await fetch(baseUrl + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options
    });
    let json = null;
    try {
      json = await response.json();
    } catch (_) {
      json = null;
    }
    return { response, json };
  };

  try {
    const health = await httpJson('/api/health');
    assert(health.response.status === 200 && health.json.status === 'ok', 'HTTP health endpoint reports database ok');

    const invalidCases = [
      { name: '空标题', payload: { title: '', body_text: 'valid body' } },
      { name: '空白标题', payload: { title: '   ', body_text: 'valid body' } },
      { name: '空正文', payload: { title: 'Valid title', body_text: '' } },
      { name: '缺失正文', payload: { title: 'Valid title' } },
      { name: '非法URL', payload: { title: 'Valid title', body_text: 'valid body', source_url: 'not-a-url' } },
      { name: '非HTTP协议URL', payload: { title: 'Valid title', body_text: 'valid body', source_url: 'ftp://example.org/a' } },
      { name: '标题类型错误', payload: { title: 123, body_text: 'valid body' } },
      { name: '正文类型错误', payload: { title: 'Valid title', body_text: ['array'] } },
      { name: 'URL类型错误', payload: { title: 'Valid title', body_text: 'valid body', source_url: 123 } },
      { name: '页码类型错误', payload: { title: 'Valid title', body_text: 'valid body', source_page: 12 } },
      { name: '标签类型错误', payload: { title: 'Valid title', body_text: 'valid body', tags: 123 } },
      { name: '标题超长', payload: { title: 'x'.repeat(501), body_text: 'valid body' } },
      { name: '正文超长', payload: { title: 'Valid title', body_text: 'x'.repeat(20001) } },
      { name: 'URL超长', payload: { title: 'Valid title', body_text: 'valid body', source_url: 'https://example.org/' + 'a'.repeat(1000) } },
      { name: '页码超长', payload: { title: 'Valid title', body_text: 'valid body', source_page: 'x'.repeat(101) } },
      { name: '标签超长', payload: { title: 'Valid title', body_text: 'valid body', tags: 'x'.repeat(1001) } }
    ];

    for (const testCase of invalidCases) {
      const { response, json } = await httpJson('/api/excerpts', {
        method: 'POST',
        body: JSON.stringify(testCase.payload)
      });
      assert(
        response.status === 400 && json && typeof json.error === 'string',
        `HTTP 400 rejected ${testCase.name} (got ${response.status})`
      );
    }

    const validPayload = {
      title: 'HTTP 验收条目 ' + stamp,
      source_url: 'https://example.org/http-check',
      source_page: '3',
      body_text: 'HTTP 验收条目包含唯一英文标记 HttpApiKeyword 与中文检索词。',
      tags: 'HTTP验收,测试'
    };
    const created = await httpJson('/api/excerpts', {
      method: 'POST',
      body: JSON.stringify(validPayload)
    });
    assert(created.response.status === 201 && created.json.id > 0, 'HTTP valid excerpt saved with 201');
    const httpId = created.json.id;
    createdIds.push(httpId);

    const detail = await httpJson(`/api/excerpts/${httpId}`);
    assert(detail.response.status === 200 && detail.json.title === validPayload.title, 'HTTP detail returns saved record');
    assert(detail.json.state === 'unread', 'HTTP saved record defaults to unread');

    const apiSearch = await httpJson('/api/search?q=' + encodeURIComponent('HttpApiKeyword'));
    assert(
      apiSearch.response.status === 200 && apiSearch.json.data.some(r => r.id === httpId),
      'HTTP FULLTEXT search finds the newly saved record'
    );

    const missingQuery = await httpJson('/api/search');
    assert(missingQuery.response.status === 400, 'HTTP search rejects missing query with 400');
    const longQuery = await httpJson('/api/search?q=' + encodeURIComponent('x'.repeat(201)));
    assert(longQuery.response.status === 400, 'HTTP search rejects overlong query with 400');

    const invalidState = await httpJson(`/api/excerpts/${httpId}/review`, {
      method: 'PUT',
      body: JSON.stringify({ state: 'bogus', notes: 'x' })
    });
    assert(invalidState.response.status === 400, 'HTTP review rejects invalid state with 400');
    const invalidNotes = await httpJson(`/api/excerpts/${httpId}/review`, {
      method: 'PUT',
      body: JSON.stringify({ state: 'read', notes: 123 })
    });
    assert(invalidNotes.response.status === 400, 'HTTP review rejects non-string notes with 400');
    const longNotes = await httpJson(`/api/excerpts/${httpId}/review`, {
      method: 'PUT',
      body: JSON.stringify({ state: 'read', notes: 'x'.repeat(5001) })
    });
    assert(longNotes.response.status === 400, 'HTTP review rejects overlong notes with 400');

    const validReview = await httpJson(`/api/excerpts/${httpId}/review`, {
      method: 'PUT',
      body: JSON.stringify({ state: 'read', notes: 'HTTP验收备注' })
    });
    assert(validReview.response.status === 200, 'HTTP valid review state update succeeds');
    const reviewedDetail = await httpJson(`/api/excerpts/${httpId}`);
    assert(
      reviewedDetail.json.state === 'read' && reviewedDetail.json.review_notes === 'HTTP验收备注',
      'HTTP review state and notes persist in database'
    );

    const httpStats = await httpJson('/api/stats');
    assert(
      httpStats.response.status === 200 && httpStats.json.reviews.unread >= 2,
      'HTTP stats include unread rows without review entries'
    );

    console.log('\n[11] Markdown Export Marks Synthetic Sources');
    const exportMarker = 'ExportMarker';
    const syntheticTitle = exportMarker + ' 导出标记合成样例 ' + stamp;
    const realTitle = '导出标记普通条目 ' + stamp;
    const syntheticExport = await httpJson('/api/excerpts', {
      method: 'POST',
      body: JSON.stringify({
        title: syntheticTitle,
        source_url: 'https://example.com/synthetic-export',
        source_page: '9',
        body_text: `Markdown export verification body contains ${exportMarker} for the synthetic sample.`,
        tags: '导出测试'
      })
    });
    assert(syntheticExport.response.status === 201, 'HTTP created synthetic-source excerpt for export test');
    createdIds.push(syntheticExport.json.id);

    const realExport = await httpJson('/api/excerpts', {
      method: 'POST',
      body: JSON.stringify({
        title: realTitle,
        source_url: 'https://example.org/export-check',
        source_page: '10',
        body_text: `Markdown export verification body contains ${exportMarker} for the normal record.`,
        tags: '导出测试'
      })
    });
    assert(realExport.response.status === 201, 'HTTP created non-synthetic excerpt for export test');
    createdIds.push(realExport.json.id);

    const exportResponse = await fetch(baseUrl + '/api/export?q=' + encodeURIComponent(exportMarker));
    const exportText = await exportResponse.text();
    assert(exportResponse.status === 200, 'HTTP Markdown export returns 200');
    assert(
      (exportResponse.headers.get('content-type') || '').includes('text/markdown'),
      'HTTP Markdown export returns text/markdown'
    );
    assert(
      (exportResponse.headers.get('content-disposition') || '').includes('attachment'),
      'HTTP Markdown export is an attachment'
    );
    assert(
      exportText.includes('本清单包含合成教学样例') && exportText.includes('不是真实文献'),
      'Markdown export header contains synthetic-source disclaimer'
    );

    const exportSections = exportText.split(/\n## /);
    const syntheticSection = exportSections.find(section => section.includes(syntheticTitle));
    const realSection = exportSections.find(section => section.includes(realTitle));
    assert(syntheticSection !== undefined, 'Markdown export includes the synthetic-source record');
    assert(
      syntheticSection && syntheticSection.includes('合成教学样例 · example.com 为占位来源 · 非真实文献'),
      'Synthetic record is labeled as teaching sample with placeholder source'
    );
    assert(
      realSection !== undefined && !realSection.includes('数据性质'),
      'Non-synthetic record is not labeled as a synthetic sample'
    );
    assert(
      syntheticSection && syntheticSection.includes('https://example.com/synthetic-export'),
      'Markdown export preserves the synthetic source URL'
    );
    const scoredSearch = await httpJson('/api/search?q=' + encodeURIComponent(exportMarker));
    const scoredSample = scoredSearch.json.data.find(item => item.id === syntheticExport.json.id);
    assert(scoredSample && scoredSample.title_score > 0, 'Weighted-score sample matches the title index');
    const expectedScore = scoredSample && Number(scoredSample.body_score) + 2 * Number(scoredSample.title_score);
    assert(scoredSample && Math.abs(scoredSample.relevance_score - expectedScore) < 1e-10,
      'Search API relevance matches the title-weighted database ordering');
    assert(scoredSample && syntheticSection.includes(`*相关度: ${expectedScore.toFixed(4)}*`),
      'Markdown export preserves the same weighted relevance as search');
  } finally {
    await new Promise(resolve => server.close(resolve));
  }

  console.log('\n[12] Cleanup (only test-created IDs)');
  let deleted = 0;
  for (const id of createdIds) {
    try {
      if (await db.deleteExcerpt(id)) deleted++;
    } catch (err) {
      console.error(`  cleanup failed for id ${id}: ${err.message}`);
    }
  }
  createdIds.length = 0;
  assert(deleted > 0, `Deleted ${deleted} excerpts created by this test run`);
}

async function runTests() {
  console.log('=== EvidenceDesk Integration Tests ===\n');
  const createdIds = [];
  let fatalError = null;

  try {
    await run(createdIds);
  } catch (err) {
    fatalError = err;
    failed++;
    console.error('\nTest runner error:', err);
  } finally {
    for (const id of createdIds) {
      try {
        await db.deleteExcerpt(id);
      } catch (err) {
        console.error(`  cleanup after error failed for id ${id}: ${err.message}`);
      }
    }
    try {
      const finalStats = await db.getStats();
      assert(
        finalStats.excerpts === initialCount,
        `Existing records preserved: expected ${initialCount}, got ${finalStats.excerpts}`
      );
    } catch (err) {
      failed++;
      console.error('  final count check failed:', err.message);
    }
    await db.closePool();
  }

  console.log('\n=== Test Summary ===');
  console.log(`Total: ${passed + failed} | Passed: ${passed} | Failed: ${failed}`);

  if (failed > 0) {
    console.log('\nFailed tests:');
    results.filter(r => r.status === 'FAIL').forEach(r => console.log(`  - ${r.test}`));
  }

  process.exit(failed > 0 || fatalError ? 1 : 0);
}

runTests();
