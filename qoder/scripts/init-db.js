require('dotenv').config();
const db = require('../src/db');

async function init() {
  console.log('[Init] Connecting to database...');

  const connected = await db.checkConnection();
  if (!connected) {
    console.error('[Init] Database connection failed:', db.getConnectionStatus().error);
    process.exit(1);
  }

  console.log('[Init] Connected successfully');
  console.log('[Init] Initializing schema...');

  await db.initDatabase();

  console.log('[Init] Done!');
  await db.closePool();
}

init().catch(err => {
  console.error('[Init] Error:', err);
  process.exit(1);
});
