import { connectMysql } from '../fn/lib/sock-node.mjs';
import { Store, parseDsn } from '../fn/lib/store.ts';

const dsn = process.env.SEEKDB_D0;
if (!dsn) { console.error('SEEKDB_D0 missing'); process.exit(1); }
const store = await Store.open(parseDsn(dsn), connectMysql, globalThis.crypto.subtle);
await store.ensureSchema();
const added = await store.seedIfEmpty();
console.log('seeded:', added, 'count:', await store.count());
const cn = await store.search('分布式数据库');
console.log('cn hits:', cn.length, '| top:', cn[0] && cn[0].title, '| score:', cn[0] && Number(cn[0].relevance_score).toFixed(4));
const en = await store.search('full-text search');
console.log('en hits:', en.length);
const id = await store.create({ title: '链路自检', body_text: 'Function 链路自检记录 HttpApiKeyword', source_url: 'https://example.com/chain', tags: '自检' });
const hit = await store.search('HttpApiKeyword');
console.log('create+search:', id, hit.some(r => Number(r.id) === id));
await store.setReview(id, 'review', '链路备注');
const rv = await store.getReview(id);
console.log('review:', rv.state, rv.notes);
console.log('stats:', JSON.stringify(await store.stats()));
console.log('version:', await store.version());
console.log('removed:', await store.remove(id));
store.close();
console.log('NODE-STORE-OK');
