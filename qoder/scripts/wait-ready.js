const mysql = require('mysql2/promise');

const host = process.env.DB_HOST || '127.0.0.1';
const port = parseInt(process.env.DB_PORT || '2881', 10);
const user = process.env.DB_USER || 'root';
const password = process.env.DB_PASSWORD || '';
const dbName = process.env.DB_NAME || 'test';
const timeoutSec = parseInt(process.env.WAIT_TIMEOUT_SEC || '180', 10);

if (!/^[A-Za-z0-9_]+$/.test(dbName)) {
  console.error(`[wait-ready] DB_NAME 只允许字母数字下划线，当前值: ${dbName}`);
  process.exit(1);
}

const deadline = Date.now() + timeoutSec * 1000;

(async () => {
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const conn = await mysql.createConnection({ host, port, user, password, connectTimeout: 5000 });
      await conn.ping();
      await conn.query(`CREATE DATABASE IF NOT EXISTS \`${dbName}\` DEFAULT CHARACTER SET utf8mb4`);
      await conn.end();
      console.log(`[wait-ready] seekdb 已就绪: ${host}:${port}，数据库 ${dbName} 可用`);
      process.exit(0);
    } catch (err) {
      lastError = err;
      process.stdout.write(`[wait-ready] 等待 ${host}:${port} ... (${err.message.split('\n')[0]})\n`);
      await new Promise(r => setTimeout(r, 2000));
    }
  }
  console.error(`[wait-ready] 超时 ${timeoutSec}s 仍无法连接 ${host}:${port}: ${lastError && lastError.message}`);
  process.exit(1);
})();
