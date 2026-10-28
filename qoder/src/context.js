const BASE = (process.env.POWERCONTEXT_URL || 'http://127.0.0.1:18752').replace(/\/+$/, '');
const SCOPE_KEY = 'evidencedesk-qoder';

let scopeId = null;

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(8000)
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`PowerContext ${path} HTTP ${res.status} ${detail.slice(0, 120)}`);
  }
  return res.json();
}

async function ensureScope() {
  if (scopeId) return scopeId;
  const r = await post('/v1/scopes', {
    title: '研读档案 EvidenceDesk',
    summary: '复习进度与检索历史的跨会话记忆',
    idempotency_key: SCOPE_KEY
  });
  scopeId = r.scope_id;
  return scopeId;
}

async function rememberProgress(payload) {
  const sid = await ensureScope();
  return post('/v1/memory/remember', {
    scope_id: sid,
    kind: 'review-progress',
    text: JSON.stringify(payload),
    reason: '复习状态更新后保存进度，供下次会话复用'
  });
}

async function latestProgress() {
  const sid = await ensureScope();
  const r = await post('/v1/memory/entries/list', { scope_id: sid });
  const entries = r.entries || [];
  if (!entries.length) return null;
  // MemoryEntry 无时间戳字段；version 随写入单调递增，列表顺序作为次序兜底
  const indexed = entries.map((e, i) => ({ e, i }));
  indexed.sort((a, b) => (Number(b.e.version || 0) - Number(a.e.version || 0)) || (b.i - a.i));
  const e = indexed[0].e;
  let parsed = null;
  try { parsed = JSON.parse(e.text); } catch (err) { parsed = { raw: e.text }; }
  return { entry: parsed, version: e.version || null };
}

async function status() {
  try {
    const sid = await ensureScope();
    return { connected: true, url: BASE, scope_id: sid };
  } catch (err) {
    return { connected: false, url: BASE, error: err.message };
  }
}

module.exports = { ensureScope, rememberProgress, latestProgress, status, BASE };
