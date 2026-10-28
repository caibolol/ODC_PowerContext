const db = require('../src/db');
const { SAMPLE_DATA } = require('../src/sample-data');

(async () => {
  try {
    const existing = await db.listExcerpts({ limit: 100000 });
    const keys = new Set(existing.map(e => `${e.title}|${e.source_url || ''}`));
    let added = 0;
    for (const s of SAMPLE_DATA) {
      if (keys.has(`${s.title}|${s.source_url}`)) continue;
      await db.createExcerpt(s);
      added++;
    }
    console.log(`[import-sample] 新增 ${added} 条合成样例，已有 ${existing.length} 条保持不变`);
    await db.closePool();
    process.exit(0);
  } catch (err) {
    console.error(`[import-sample] 导入失败: ${err.message}`);
    process.exit(1);
  }
})();
