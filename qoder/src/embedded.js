const fs = require('fs');
const path = require('path');
const http = require('http');

const VENDOR_DIR = path.join(__dirname, '..', 'vendor');

function platformKey() {
  const p = process.platform;
  const a = process.arch;
  if (p === 'linux' && a === 'x64') return 'linux-x64';
  if (p === 'win32' && a === 'x64') return 'win32-x64';
  if (p === 'darwin' && a === 'arm64') return 'darwin-arm64';
  return null;
}

let vendorServer = null;

// 评审环境可能无法访问境外下载源：仓库内置 linux-x64 原生包 zip，
// 用本机 HTTP 服务作为 SEEKDB_BINDINGS_BASE_URL，实现离线加载。
async function ensureBindingsBaseUrl() {
  if (process.env.SEEKDB_BINDINGS_BASE_URL) return;
  const key = platformKey();
  if (!key) return;
  const zip = path.join(VENDOR_DIR, `seekdb-js-bindings-${key}.zip`);
  if (!fs.existsSync(zip)) return;
  await new Promise((resolve, reject) => {
    vendorServer = http.createServer((req, res) => {
      const name = path.basename(decodeURIComponent(req.url || '/'));
      const file = path.join(VENDOR_DIR, name);
      if (!file.startsWith(VENDOR_DIR) || !fs.existsSync(file)) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'application/zip' });
      fs.createReadStream(file).pipe(res);
    });
    vendorServer.once('error', reject);
    vendorServer.listen(0, '127.0.0.1', () => {
      process.env.SEEKDB_BINDINGS_BASE_URL = `http://127.0.0.1:${vendorServer.address().port}`;
      console.log(`[embedded] 使用仓库内置原生包: ${process.env.SEEKDB_BINDINGS_BASE_URL}`);
      resolve();
    });
  });
}

let driverPromise = null;

function getDriver() {
  if (!driverPromise) driverPromise = openEmbedded();
  return driverPromise;
}

async function openEmbedded() {
  await ensureBindingsBaseUrl();
  const bindings = require('@seekdb/js-bindings');
  const native = await bindings.getNativeBindingAsync();
  const dir = process.env.EMBEDDED_DB_DIR || path.join(__dirname, '..', '.evidencedesk-seekdb');
  fs.mkdirSync(dir, { recursive: true });
  const dbName = process.env.DB_NAME || 'test';
  if (!/^[A-Za-z0-9_]+$/.test(dbName)) throw new Error(`DB_NAME 只允许字母数字下划线: ${dbName}`);

  const db = native.open(dir);
  let boot = null;
  for (const name of ['oceanbase', 'test', 'sys']) {
    try { boot = native.connect(db, name, true); break; } catch (e) { /* 尝试下一个默认库 */ }
  }
  if (!boot) boot = native.connect(db, dbName, true);
  try {
    await native.execute(boot, `CREATE DATABASE IF NOT EXISTS \`${dbName}\``, []);
  } finally {
    native.disconnect(boot);
  }
  const conn = native.connect(db, dbName, true);

  let chain = Promise.resolve();
  function serial(fn) {
    const p = chain.then(fn, fn);
    chain = p.catch(() => {});
    return p;
  }

  function toObjects(result) {
    const cols = result.columns || [];
    return (result.rows || []).map(row => {
      const o = {};
      cols.forEach((c, i) => { o[c] = row[i]; });
      return o;
    });
  }

  async function run(sql, params) {
    return serial(async () => {
      const result = await native.execute(conn, sql, params || []);
      if (/^\s*(insert|replace)\b/i.test(sql)) {
        const idRes = await native.execute(conn, 'SELECT LAST_INSERT_ID() AS id', []);
        const insertId = Number(toObjects(idRes)[0].id || 0);
        return [{ insertId, affectedRows: 1 }];
      }
      if (/^\s*(update|delete)\b/i.test(sql)) {
        const rcRes = await native.execute(conn, 'SELECT ROW_COUNT() AS n', []);
        return [{ affectedRows: Number(toObjects(rcRes)[0].n || 0), insertId: 0 }];
      }
      return [toObjects(result)];
    });
  }

  return {
    embedded: true,
    execute: (sql, params) => run(sql, params),
    query: (sql) => run(sql, []),
    getConnection: async () => ({ ping: async () => run('SELECT 1 AS ok', []), release: () => {}, execute: (sql, params) => run(sql, params), query: (sql) => run(sql, []) }),
    end: async () => {
      try { native.disconnect(conn); } catch (e) { /* 已断开 */ }
      try { native.close_sync(db); } catch (e) { /* 已关闭 */ }
      if (vendorServer) vendorServer.close();
      driverPromise = null;
    }
  };
}

module.exports = { getDriver };
