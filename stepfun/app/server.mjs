import express from 'express';
import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from 'seekdb';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const app = express();
app.use(express.json({limit:'8mb'}));
const db = new SeekdbClient({host:process.env.SEEKDB_HOST || '127.0.0.1',port:Number(process.env.SEEKDB_PORT || 2881),user:process.env.SEEKDB_USER || 'root',password:process.env.SEEKDB_PASSWORD || '',database:process.env.SEEKDB_DATABASE || 'test'});
const prefix = 'local_seek_';
const nameOf = value => { if(!/^[a-z][a-z0-9_]{0,35}$/.test(value)) throw Error('集合名须为小写字母、数字和下划线'); return prefix+value; };
const vector = value => {if(!Array.isArray(value)||value.length!==384||!value.every(Number.isFinite)) throw Error('需要浏览器生成的 384 维向量'); return value;};
const route = fn => async(req,res,next)=>{try{res.json(await fn(req));}catch(e){next(e);}};
const collection = async name => db.getCollection({name:nameOf(name),embeddingFunction:null});
app.get('/api/collections',route(async()=>Promise.all((await db.listCollections({withEmbeddingFunction:false})).filter(c=>c.name.startsWith(prefix)).map(async c=>({name:c.name.slice(prefix.length),count:await c.count()})))));
app.post('/api/collections',route(async req=>{const name=nameOf(req.body.name); if(await db.hasCollection(name)) return {name:req.body.name,exists:true}; await db.createCollection({name,embeddingFunction:null,schema:new Schema({vectorIndex:new VectorIndexConfig({hnsw:{dimension:384,distance:'cosine'},embeddingFunction:null}),fulltextIndex:new FulltextIndexConfig('beng')})}); return {name:req.body.name};}));
app.post('/api/collections/:name/documents',route(async req=>{const docs=req.body.documents;if(!Array.isArray(docs)||!docs.length||docs.length>128) throw Error('每批需要 1–128 篇文档');for(const d of docs){if(typeof d.id!=='string'||!d.id||typeof d.text!=='string'||!d.text.trim()||d.text.length>20000)throw Error('文档格式不正确');vector(d.embedding);}const c=await collection(req.params.name);await c.upsert({ids:docs.map(d=>d.id),documents:docs.map(d=>d.text),embeddings:docs.map(d=>d.embedding),metadatas:docs.map(d=>({title:String(d.title||d.id),model:'Xenova/all-MiniLM-L6-v2',dtype:String(d.dtype||'q8')}))});await c.refresh_index();return {count:await c.count(),refreshed:true};}));
app.post('/api/collections/:name/search',route(async req=>{if(typeof req.body.query!=='string'||!req.body.query.trim())throw Error('请输入问题');const c=await collection(req.params.name);const start=performance.now();const result=await c.hybridSearch({query:{whereDocument:{$contains:req.body.query},nResults:20},knn:{queryEmbeddings:[vector(req.body.embedding)],nResults:20},rank:{rrf:{rankWindowSize:20,rankConstant:60}},nResults:Math.min(20,Math.max(1,Number(req.body.limit)||5)),include:['documents','metadatas','distances']});return {result,searchMs:performance.now()-start,ranking:'seekdb server-side hybrid RRF'};}));
app.post('/api/collections/:name/refresh',route(async req=>{await(await collection(req.params.name)).refresh_index();return {refreshed:true};}));
app.use('/api',(err,req,res,next)=>{console.error(err.message);res.status(400).json({error:err.message});});
const root=path.dirname(fileURLToPath(import.meta.url));
if(process.env.NODE_ENV==='production')app.use(express.static(path.join(root,'dist')));
else {const {createServer}=await import('vite');const vite=await createServer({server:{middlewareMode:true},appType:'spa'});app.use(vite.middlewares);}
const port=Number(process.env.PORT||5173);
app.listen(port,'127.0.0.1',()=>console.log(`Local Seek: http://127.0.0.1:${port}`));
