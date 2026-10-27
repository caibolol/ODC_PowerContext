import test from 'node:test';
import assert from 'node:assert/strict';
const base=process.env.TEST_URL||'http://127.0.0.1:18747';
test('seekdb 持久化与乐观并发冲突',async()=>{const id='test_'+Date.now();const initial=await(await fetch(`${base}/state/${id}`)).json();assert.equal(initial.revision,0);const state={...initial.state,score:10,room:1};const send=()=>fetch(`${base}/state/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({state,revision:0})});assert.equal((await send()).status,200);assert.equal((await send()).status,409);const next=await(await fetch(`${base}/state/${id}`)).json();assert.equal(next.state.score,10);assert.equal(next.revision,1);});
