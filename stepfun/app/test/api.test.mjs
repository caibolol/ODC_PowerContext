import test from 'node:test';
import assert from 'node:assert/strict';
const base=process.env.TEST_URL||'http://127.0.0.1:18743';
test('数据库中的浏览器导入在后续请求仍然存在',async()=>{const r=await fetch(base+'/api/collections');assert.equal(r.status,200);const rows=await r.json();assert.ok(rows.some(r=>r.name==='my_knowledge'&&r.count>=12));});
test('拒绝无效集合名',async()=>{const r=await fetch(base+'/api/collections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'bad;DROP TABLE'})});assert.equal(r.status,400);assert.match((await r.json()).error,/集合名/);});
test('拒绝未在浏览器生成的错误维数向量',async()=>{const r=await fetch(base+'/api/collections/my_knowledge/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:'test',embedding:[1,2,3]})});assert.equal(r.status,400);assert.match((await r.json()).error,/384/);});
