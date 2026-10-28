import type { SocketLike } from "./mysqlc.ts";

export async function connectMysql(hostname: string, port: number): Promise<SocketLike> {
  let conn = await Deno.connect({ hostname, port });
  const sock: SocketLike = {
    async write(b: Uint8Array): Promise<void> {
      await conn.write(b);
    },
    async read(): Promise<Uint8Array | null> {
      const buf = new Uint8Array(16384);
      const n = await conn.read(buf);
      return n === null ? null : buf.slice(0, n);
    },
    close(): void {
      try { conn.close(); } catch { /* already closed */ }
    },
    async upgradeTls(host: string): Promise<SocketLike> {
      const tlsConn = await Deno.startTls(conn, { hostname: host });
      conn = tlsConn as typeof conn;
      return sock;
    },
  };
  return sock;
}
