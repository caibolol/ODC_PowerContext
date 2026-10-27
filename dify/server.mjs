import express from 'express';
import mysql from 'mysql2/promise';
import {fileURLToPath} from 'node:url';
const pool=mysql.createPool({host:process.env.SEEKDB_HOST||'127.0.0.1',port:Number(process.env.SEEKDB_PORT||2881),user:process.env.SEEKDB_USER||'root',password:process.env.SEEKDB_PASSWORD||'',database:process.env.SEEKDB_DATABASE||'test',connectionLimit:4});
await pool.query('CREATE TABLE IF NOT EXISTS odc_detective_sessions (player_id VARCHAR(64) PRIMARY KEY, state_json JSON NOT NULL, revision INT NOT NULL DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)');
const app=express();app.use(express.json({limit:'32kb'}));
app.get('/workflow.yml',(req,res)=>res.sendFile(fileURLToPath(new URL('./detective.yml',import.meta.url))));
const valid=id=>typeof id==='string'&&/^[a-zA-Z0-9_-]{1,64}$/.test(id);
app.get('/state/:id',async(req,res)=>{try{if(!valid(req.params.id))return res.status(400).json({error:'invalid player id'});const [rows]=await pool.execute('SELECT state_json,revision FROM odc_detective_sessions WHERE player_id=?',[req.params.id]);res.json(rows.length?{state:typeof rows[0].state_json==='string'?JSON.parse(rows[0].state_json):rows[0].state_json,revision:rows[0].revision}:{state:{room:0,score:0,attempts:0,hints:0,history:[]},revision:0});}catch(e){res.status(500).json({error:e.message});}});
app.post('/state/:id',async(req,res)=>{try{const {state,revision}=req.body;if(!valid(req.params.id)||!Number.isInteger(revision)||revision<0||!state||!Array.isArray(state.history)||state.history.length>100)return res.status(400).json({error:'invalid state'});let affected=0;if(revision===0){const [r]=await pool.execute('INSERT IGNORE INTO odc_detective_sessions(player_id,state_json,revision) VALUES(?,?,1)',[req.params.id,JSON.stringify(state)]);affected=r.affectedRows;}else{const [r]=await pool.execute('UPDATE odc_detective_sessions SET state_json=?,revision=revision+1 WHERE player_id=? AND revision=?',[JSON.stringify(state),req.params.id,revision]);affected=r.affectedRows;}if(!affected)return res.status(409).json({error:'另一个回合已更新进度，请重新运行'});res.json({saved:true,revision:revision+1});}catch(e){res.status(500).json({error:e.message});}});
app.listen(Number(process.env.PORT||18747),'127.0.0.1',()=>console.log('Detective state store ready'));

