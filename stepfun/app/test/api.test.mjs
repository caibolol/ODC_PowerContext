import test from 'node:test';
import assert from 'node:assert/strict';
const base=process.env.TEST_URL||'http://127.0.0.1:5173';
const post=async(path,body)=>fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

test('增量写入、更新与集合隔离（合成向量，仅验证数据层）',async()=>{
  const name='test_'+Date.now();
  assert.equal((await post('/api/collections',{name})).status,200);
  const embedding=Array(384).fill(0);embedding[0]=1;
  const first=await post(`/api/collections/${name}/documents`,{documents:[{id:'one',title:'First',text:'cometaudit original document',embedding}]});
  assert.equal(first.status,200);assert.equal((await first.json()).count,1);
  const update=await post(`/api/collections/${name}/documents`,{documents:[{id:'one',title:'Updated',text:'cometaudit updated document',embedding},{id:'two',title:'Second',text:'cometaudit second document',embedding}]});
  assert.equal(update.status,200);assert.equal((await update.json()).count,2);
  const r=await post(`/api/collections/${name}/search`,{query:'cometaudit',embedding,limit:5});
  assert.equal(r.status,200);const result=(await r.json()).result;
  assert.deepEqual(new Set(result.ids[0]),new Set(['one','two']));
  assert.ok(result.documents[0].includes('cometaudit updated document'));
  assert.ok(!result.documents[0].includes('cometaudit original document'));
  const rows=await(await fetch(base+'/api/collections')).json();
  assert.ok(rows.some(row=>row.name===name&&row.count===2));
});

test('拒绝无效集合名',async()=>{
  const r=await post('/api/collections',{name:'bad;DROP TABLE'});
  assert.equal(r.status,400);assert.match((await r.json()).error,/集合名/);
});

test('拒绝错误维数向量',async()=>{
  const name='test_invalid_'+Date.now();await post('/api/collections',{name});
  const r=await post(`/api/collections/${name}/search`,{query:'test',embedding:[1,2,3]});
  assert.equal(r.status,400);assert.match((await r.json()).error,/384/);
});
