export async function handler(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const json = (obj: unknown, status = 200) =>
    new Response(JSON.stringify(obj), {
      status,
      headers: { "content-type": "application/json; charset=utf-8" },
    });

  if (url.pathname.endsWith("/probe")) {
    const D = Deno as unknown as Record<string, unknown>;
    const out: Record<string, unknown> = {
      hasConnect: typeof D.connect === "function",
      hasConnectTls: typeof D.connectTls === "function",
      hasStartTls: typeof D.startTls === "function",
      hasListen: typeof D.listen === "function",
    };
    try {
      const connect = D.connect as (o: { hostname: string; port: number }) => Promise<any>;
      const conn = await connect({ hostname: "gw0.apac.seekdb.ai", port: 2881 });
      out.tcp = "connected";
      const buf = new Uint8Array(64);
      const n = await conn.read(buf);
      out.greetingBytes = n ? Array.from(buf.slice(0, Math.min(n, 8))) : null;
      try { conn.close(); } catch { /* ignore */ }
    } catch (e) {
      out.tcp = "error: " + ((e as Error)?.message || String(e));
    }
    return json(out);
  }

  return json({ ok: true, service: "evidencedesk-probe" });
}
