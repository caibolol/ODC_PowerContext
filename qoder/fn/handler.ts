import { Store, parseDsn } from "./lib/store.ts";
import { connectMysql } from "./lib/sock-deno.ts";

const STATE_LABEL: Record<string, string> = { unread: "未读", read: "已读", review: "待复习", mastered: "已掌握" };
const VALID_STATES = ["unread", "read", "review", "mastered"];

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
  });
}

function isSynthetic(item: { source_url?: string | null; tags?: string | null }): boolean {
  const h = `${item.source_url || ""} ${item.tags || ""}`.toLowerCase();
  return h.includes("example.com") || h.includes("synthetic") || h.includes("合成教学样例");
}

function validateCreate(b: Record<string, unknown>): string | null {
  const { title, body_text, source_url, source_page, tags } = b as Record<string, any>;
  if (!title || typeof title !== "string" || title.trim().length === 0) return "标题不能为空";
  if (title.length > 500) return "标题不能超过500字";
  if (!body_text || typeof body_text !== "string" || body_text.trim().length === 0) return "正文摘录不能为空";
  if (body_text.length > 20000) return "正文摘录不能超过20000字";
  if (source_url !== undefined && source_url !== null && typeof source_url !== "string") return "来源URL类型不正确";
  if (source_url && source_url.length > 1000) return "来源URL不能超过1000字符";
  if (source_url && source_url.trim().length > 0 && !/^https?:\/\/.+/i.test(source_url)) return "来源URL格式不正确";
  if (source_page !== undefined && source_page !== null && typeof source_page !== "string") return "页码类型不正确";
  if (source_page && source_page.length > 100) return "页码不能超过100字符";
  if (tags !== undefined && tags !== null && typeof tags !== "string") return "标签类型不正确";
  if (tags && tags.length > 1000) return "标签不能超过1000字符";
  return null;
}

function buildMarkdown(rows: Record<string, any>[], q: string | null): string {
  let md = "# 研读档案证据清单\n\n";
  md += `导出时间: ${new Date().toLocaleString("zh-CN")}\n`;
  md += `记录数: ${rows.length}\n\n`;
  if (rows.some(isSynthetic)) {
    md += "> **数据性质说明**：本清单包含合成教学样例，example.com 为占位来源，不是真实文献或真实用户数据。带“合成教学样例 · 占位来源 · 非真实文献”标记的条目仅用于演示。\n\n";
  }
  if (q) md += `搜索关键词: ${q.trim()}\n\n`;
  md += "---\n\n";
  rows.forEach((item, idx) => {
    md += `## ${idx + 1}. ${item.title}\n\n`;
    if (isSynthetic(item)) md += "- **数据性质**: 合成教学样例 · example.com 为占位来源 · 非真实文献\n";
    if (item.source_url) md += `- **来源**: [${item.source_url}](${item.source_url})\n`;
    if (item.source_page) md += `- **页码**: ${item.source_page}\n`;
    if (item.tags) md += `- **标签**: ${item.tags}\n`;
    if (item.state) md += `- **状态**: ${STATE_LABEL[item.state] || item.state}\n`;
    if (item.review_notes) md += `- **备注**: ${item.review_notes}\n`;
    md += `\n### 摘录内容\n\n${item.body_text}\n\n`;
    if (item.relevance_score !== undefined) md += `*相关度: ${Number(item.relevance_score).toFixed(4)}*\n\n`;
    md += "---\n\n";
  });
  md += "> 导出来源：Qoder Sites 在线体验，数据存于 seekdb 云端实例（真实数据库记录）。\n";
  return md;
}

async function withStore<T>(fn: (s: Store) => Promise<T>): Promise<T> {
  const dsn = Deno.env.get("SEEKDB_D0");
  if (!dsn) throw new Error("service_not_configured");
  const store = await Store.open(parseDsn(dsn), connectMysql, crypto.subtle);
  try {
    await store.ensureSchema();
    return await fn(store);
  } finally {
    store.close();
  }
}

export async function handler(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const idx = url.pathname.indexOf("/api/");
  if (idx < 0) {
    return json({ ok: true, service: "evidencedesk", endpoints: ["/api/health", "/api/stats", "/api/excerpts", "/api/search", "/api/export", "/api/import-sample", "/api/excerpts/:id/review"] });
  }
  const path = url.pathname.slice(idx + 4); // 以 /api/... 为准
  const method = request.method;

  try {
    if (path === "/api/health" && method === "GET") {
      return await withStore(async (s) => json({ status: "ok", backend: "seekdb (cloud instance, MySQL protocol over TLS)", version: await s.version() }));
    }

    if (path === "/api/stats" && method === "GET") {
      return await withStore(async (s) => json(await s.stats()));
    }

    if (path === "/api/import-sample" && method === "POST") {
      return await withStore(async (s) => json({ added: await s.seedIfEmpty(), total: await s.count() }));
    }

    if (path === "/api/excerpts" && method === "GET") {
      const tag = url.searchParams.get("tag");
      const state = url.searchParams.get("state");
      return await withStore(async (s) => json({ data: await s.list(tag, state, 200) }));
    }

    if (path === "/api/excerpts" && method === "POST") {
      const body = await request.json().catch(() => null);
      if (!body || typeof body !== "object") return json({ error: "请求体类型不正确" }, 400);
      const err = validateCreate(body as Record<string, unknown>);
      if (err) return json({ error: err }, 400);
      const b = body as Record<string, any>;
      return await withStore(async (s) => {
        const id = await s.create({ title: b.title, source_url: b.source_url || null, source_page: b.source_page || null, body_text: b.body_text, tags: b.tags || null });
        return json({ id }, 201);
      });
    }

    if (path === "/api/search" && method === "GET") {
      const q = (url.searchParams.get("q") || "").trim();
      if (!q) return json({ error: "检索关键词不能为空" }, 400);
      const tag = url.searchParams.get("tag");
      const state = url.searchParams.get("state");
      return await withStore(async (s) => {
        const data = await s.search(q, tag, state, 50);
        return json({ query: q, count: data.length, data });
      });
    }

    if (path === "/api/export" && method === "GET") {
      const q = (url.searchParams.get("q") || "").trim();
      const tag = url.searchParams.get("tag");
      const state = url.searchParams.get("state");
      return await withStore(async (s) => {
        const rows = q ? await s.search(q, tag, state, 200) : await s.list(tag, state, 200);
        return new Response(buildMarkdown(rows, q || null), {
          headers: { "content-type": "text/markdown; charset=utf-8", "content-disposition": `attachment; filename="evidence-${Date.now()}.md"` },
        });
      });
    }

    const reviewMatch = path.match(/^\/api\/excerpts\/(\d+)\/review$/);
    if (reviewMatch) {
      const id = Number(reviewMatch[1]);
      if (method === "GET") {
        return await withStore(async (s) => json((await s.getReview(id)) || { state: "unread", notes: null }));
      }
      if (method === "PUT") {
        const body = await request.json().catch(() => null) as Record<string, any> | null;
        if (!body || !VALID_STATES.includes(body.state)) return json({ error: "无效的复习状态", valid: VALID_STATES }, 400);
        if (body.notes !== undefined && body.notes !== null && typeof body.notes !== "string") return json({ error: "备注类型不正确" }, 400);
        if (body.notes && body.notes.length > 5000) return json({ error: "备注不能超过5000字" }, 400);
        return await withStore(async (s) => {
          if (!(await s.get(id))) return json({ error: "未找到该记录" }, 404);
          await s.setReview(id, body.state, body.notes?.trim() || null);
          return json({ message: "更新成功" });
        });
      }
      return json({ error: "method not allowed" }, 405);
    }

    const idMatch = path.match(/^\/api\/excerpts\/(\d+)$/);
    if (idMatch) {
      const id = Number(idMatch[1]);
      if (method === "GET") {
        return await withStore(async (s) => {
          const row = await s.get(id);
          return row ? json(row) : json({ error: "未找到该记录" }, 404);
        });
      }
      if (method === "DELETE") {
        return await withStore(async (s) => json({ deleted: await s.remove(id) }));
      }
      return json({ error: "method not allowed" }, 405);
    }

    return json({ error: "not found" }, 404);
  } catch (err) {
    const msg = (err as Error)?.message || "";
    if (msg === "service_not_configured") return json({ error: "service_not_configured" }, 503);
    return json({ error: "database_unavailable" }, 503);
  }
}
