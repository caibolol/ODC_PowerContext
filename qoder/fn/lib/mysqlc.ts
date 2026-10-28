// 极简 MySQL 客户端（文本协议 + TLS），供 Qoder Sites Function（Deno edge）与本地 Node 自检共用。
// 参数一律经 hex 字面量/整数校验绑定，不使用字符串拼接，防 SQL 注入。

export interface SocketLike {
  write(bytes: Uint8Array): Promise<void>;
  read(): Promise<Uint8Array | null>;
  close(): void;
  upgradeTls(hostname: string): Promise<SocketLike>;
}

export interface QueryResult {
  rows: Record<string, string | number | null>[];
  columns: string[];
  affectedRows: number;
  insertId: number;
}

const enc = new TextEncoder();
const dec = new TextDecoder();

function readLen(buf: Uint8Array, pos: number): [number, number] {
  const b0 = buf[pos];
  if (b0 < 0xfb) return [b0, pos + 1];
  if (b0 === 0xfb) return [-1, pos + 1]; // NULL marker (rows only)
  if (b0 === 0xfc) return [buf[pos + 1] | (buf[pos + 2] << 8), pos + 3];
  if (b0 === 0xfd) return [buf[pos + 1] | (buf[pos + 2] << 8) | (buf[pos + 3] << 16), pos + 4];
  if (b0 === 0xfe) {
    if (pos + 9 > buf.length) {
      throw new Error("lenenc overflow at " + pos + " pkt=" + Array.from(buf).map(b => b.toString(16).padStart(2, "0")).join(" "));
    }
    let v = 0;
    for (let i = 0; i < 8; i++) v += buf[pos + 1 + i] * 2 ** (8 * i);
    return [v, pos + 9];
  }
  throw new Error("lenenc invalid byte " + b0 + " at " + pos);
}

function lenEnc(n: number): Uint8Array {
  if (n < 0xfb) return new Uint8Array([n]);
  if (n < 0x10000) return new Uint8Array([0xfc, n & 0xff, (n >> 8) & 0xff]);
  if (n < 0x1000000) return new Uint8Array([0xfd, n & 0xff, (n >> 8) & 0xff, (n >> 16) & 0xff]);
  const out = new Uint8Array(9);
  out[0] = 0xfe;
  const dv = new DataView(out.buffer);
  dv.setBigUint64(1, BigInt(n), true);
  return out;
}

function cstr(s: string): Uint8Array {
  const b = enc.encode(s);
  const out = new Uint8Array(b.length + 1);
  out.set(b);
  return out;
}

function cat(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

async function sha1(data: Uint8Array, subtle: SubtleCrypto): Promise<Uint8Array> {
  const buf = await subtle.digest("SHA-1", data as BufferSource);
  return new Uint8Array(buf);
}

export class MySqlClient {
  private socket: SocketLike;
  private buf = new Uint8Array(0);
  private subtle: SubtleCrypto;

  constructor(socket: SocketLike, subtle: SubtleCrypto) {
    this.socket = socket;
    this.subtle = subtle;
  }

  private async readPacket(): Promise<{ seq: number; body: Uint8Array }> {
    while (true) {
      if (this.buf.length >= 4) {
        const len = this.buf[0] | (this.buf[1] << 8) | (this.buf[2] << 16);
        const seq = this.buf[3];
        if (this.buf.length >= 4 + len) {
          const body = this.buf.slice(4, 4 + len);
          this.buf = this.buf.slice(4 + len);
          if (typeof process !== 'undefined' && process.env.MYSQLC_DEBUG) {
            console.log("[pkt]", seq, len, Array.from(body.slice(0, len <= 48 ? len : 12)).map(b => b.toString(16).padStart(2, "0")).join(" "));
          }
          if (len === 0) continue; // 代理保活空包
          return { seq, body };
        }
      }
      const chunk = await this.socket.read();
      if (!chunk || chunk.length === 0) throw new Error("mysql connection closed by peer");
      const merged = new Uint8Array(this.buf.length + chunk.length);
      merged.set(this.buf); merged.set(chunk, this.buf.length);
      this.buf = merged;
    }
  }

  private async writePacket(seq: number, body: Uint8Array): Promise<void> {
    let offset = 0;
    let s = seq;
    while (true) {
      const chunkLen = Math.min(0xffffff, body.length - offset);
      const header = new Uint8Array([chunkLen & 0xff, (chunkLen >> 8) & 0xff, (chunkLen >> 16) & 0xff, s & 0xff]);
      await this.socket.write(cat(header, body.slice(offset, offset + chunkLen)));
      offset += chunkLen;
      s = (s + 1) & 0xff;
      if (chunkLen < 0xffffff || offset === body.length) break;
    }
  }

  async connect(opts: { hostname: string; port: number; user: string; password: string; database: string }): Promise<void> {
    const { seq, body } = await this.readPacket();
    if (body[0] !== 10) throw new Error("unsupported mysql protocol version " + body[0]);
    let p = 1;
    const versionEnd = body.indexOf(0, p);
    p = versionEnd + 1 + 4; // thread id
    const salt1 = body.slice(p, p + 8); p += 8 + 1;
    const capLow = body[p] | (body[p + 1] << 8); p += 2;
    p += 1; // charset
    p += 2; // status
    const capHigh = body[p] | (body[p + 1] << 8); p += 2;
    const authLen = body[p]; p += 1 + 10;
    const serverCaps = (capLow | (capHigh << 16)) >>> 0;
    const CLIENT = { LONG_PASSWORD: 1, LONG_FLAG: 4, CONNECT_WITH_DB: 8, PROTOCOL_41: 512, SSL: 2048, SECURE_CONNECTION: 32768, PLUGIN_AUTH: 524288 };
    let salt2 = new Uint8Array(0);
    if (serverCaps & CLIENT.SECURE_CONNECTION) { salt2 = body.slice(p, p + 12); p += 13; } // 12 bytes + NUL
    let plugin = "mysql_native_password";
    if (serverCaps & CLIENT.PLUGIN_AUTH) {
      const rest = body.slice(p);
      const z = rest.indexOf(0);
      if (z > 0) plugin = dec.decode(rest.slice(0, z));
    }
    const salt = cat(salt1, salt2);

    const wanted = CLIENT.LONG_PASSWORD | CLIENT.LONG_FLAG | CLIENT.CONNECT_WITH_DB | CLIENT.PROTOCOL_41 | CLIENT.SSL | CLIENT.SECURE_CONNECTION | CLIENT.PLUGIN_AUTH;
    const caps = (serverCaps & wanted) >>> 0;

    const capsBlock = (): Uint8Array => {
      const b = new Uint8Array(32);
      const v = new DataView(b.buffer);
      v.setUint32(0, caps, true);
      v.setUint32(4, 16777216, true);
      b[8] = 0x21;
      return b;
    };

    const makeAuth = async (plug: string, s: Uint8Array): Promise<Uint8Array> => {
      if (plug === "caching_sha2_password") return enc.encode(opts.password + "\0");
      if (opts.password === "") return new Uint8Array(0);
      const h1 = await sha1(enc.encode(opts.password), this.subtle);
      const h2 = await sha1(h1, this.subtle);
      const h3 = await sha1(cat(s, h2), this.subtle);
      const out = new Uint8Array(h1.length);
      for (let i = 0; i < h1.length; i++) out[i] = h1[i] ^ h3[i];
      return out;
    };

    // SSL request
    const sslReq = capsBlock();
    await this.writePacket(seq + 1, sslReq);
    this.socket = await this.socket.upgradeTls(opts.hostname);

    let auth = await makeAuth(plugin, salt);
    const respParts = [capsBlock(), cstr(opts.user), new Uint8Array([auth.length]), auth, cstr(opts.database)];
    if (serverCaps & CLIENT.PLUGIN_AUTH) respParts.push(cstr(plugin));
    await this.writePacket(seq + 2, cat(...respParts));

    let authResp = await this.readPacket();
    if (authResp.body[0] === 0xfe) {
      // auth switch: parse new plugin + salt, resend auth over TLS
      const z = authResp.body.indexOf(0, 1);
      const newPlugin = dec.decode(authResp.body.slice(1, z));
      const newSalt = authResp.body.slice(z + 1, z + 1 + 20);
      auth = await makeAuth(newPlugin, newSalt);
      await this.writePacket(authResp.seq + 1, cat(auth, new Uint8Array([0])));
      authResp = await this.readPacket();
    }
    if (authResp.body[0] === 0x01) {
      // caching_sha2 over TLS: server may request full auth -> send cleartext again
      if (authResp.body[1] === 0x04) {
        await this.writePacket(authResp.seq + 1, enc.encode(opts.password + "\0"));
        const r2 = await this.readPacket();
        if (r2.body[0] !== 0x00) throw new Error("mysql auth failed after full auth request");
      } else if (authResp.body[1] === 0x03) {
        const okPkt = await this.readPacket();
        if (okPkt.body[0] !== 0x00) throw new Error("mysql auth failed: missing OK after fast-auth");
      } else {
        throw new Error("mysql auth unexpected fast-auth byte " + authResp.body[1]);
      }
    } else if (authResp.body[0] !== 0x00) {
      throw new Error("mysql auth failed: " + dec.decode(authResp.body.slice(3)));
    }
    await this.query("SET NAMES utf8mb4");
  }

  async query(sql: string): Promise<QueryResult> {
    await this.writePacket(0, cat(new Uint8Array([0x03]), enc.encode(sql)));
    const first = await this.readPacket();
    if (first.body[0] === 0x00) return this.parseOk(first.body);
    if (first.body[0] === 0xff) throw new Error("mysql error " + dec.decode(first.body.slice(3)));
    const [colCount] = readLen(first.body, 0);
    const columns: string[] = [];
    for (let i = 0; i < colCount; i++) {
      const pkt = await this.readPacket();
      const cbody = pkt.body;
      let p = 0;
      for (let f = 0; f < 4; f++) {
        const [v, np] = readLen(cbody, p);
        p = np + (v < 0 ? 0 : v);
      }
      const [nameLen, np2] = readLen(cbody, p);
      columns.push(dec.decode(cbody.slice(np2, np2 + nameLen)));
    }
    await this.readPacket(); // EOF
    const rows: Record<string, string | number | null>[] = [];
    while (true) {
      const pkt = await this.readPacket();
      if (pkt.body[0] === 0xfe && pkt.body.length < 9) break; // EOF
      if (pkt.body[0] === 0xff) throw new Error("mysql error " + dec.decode(pkt.body.slice(3)));
      let p = 0;
      const rbody = pkt.body;
      const row: Record<string, string | null> = {};
      for (let i = 0; i < colCount; i++) {
        const [len, np] = readLen(rbody, p);
        p = np;
        row[columns[i]] = len < 0 ? null : dec.decode(rbody.slice(p, p + len));
        p += len < 0 ? 0 : len;
      }
      rows.push(row);
    }
    return { rows, columns, affectedRows: 0, insertId: 0 };
  }

  private parseOk(body: Uint8Array): QueryResult {
    let p = 1;
    const [affected, p1] = readLen(body, p); p = p1;
    const [insertId] = readLen(body, p);
    return { rows: [], columns: [], affectedRows: affected, insertId };
  }

  close(): void { this.socket.close(); }
}

// 参数绑定：字符串转 hex 字面量（X'..'），整数严格校验，杜绝拼接注入
export function bindString(s: string | null | undefined): string {
  if (s === null || s === undefined) return "NULL";
  const bytes = enc.encode(s);
  let hex = "";
  for (const b of bytes) hex += b.toString(16).padStart(2, "0");
  return `X'${hex}'`;
}
export function bindInt(n: unknown): string {
  const v = Number(n);
  if (!Number.isSafeInteger(v)) throw new Error("invalid integer parameter");
  return String(v);
}
