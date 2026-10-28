import net from 'node:net';
import tls from 'node:tls';

function makeSource(socket) {
  const src = { queue: [], waiter: null, ended: false, onData: null, onEnd: null };
  src.onData = (d) => { if (src.waiter) { const w = src.waiter; src.waiter = null; w(d); } else src.queue.push(d); };
  src.onEnd = () => { src.ended = true; if (src.waiter) { const w = src.waiter; src.waiter = null; w(null); } };
  socket.on('data', src.onData);
  socket.on('end', src.onEnd);
  socket.on('close', src.onEnd);
  return src;
}

export async function connectMysql(hostname, port) {
  let socket = net.connect({ host: hostname, port });
  await new Promise((res, rej) => { socket.once('connect', res); socket.once('error', rej); });
  let src = makeSource(socket);
  const sock = {
    async write(b) {
      const s = socket;
      await new Promise((res, rej) => s.write(Buffer.from(b), (e) => (e ? rej(e) : res())));
    },
    async read() {
      if (src.queue.length) return new Uint8Array(src.queue.shift());
      if (src.ended) return null;
      const d = await new Promise((res) => { src.waiter = res; });
      return d ? new Uint8Array(d) : null;
    },
    close() { try { socket.destroy(); } catch { /* ignore */ } },
    async upgradeTls(host) {
      const pending = src.queue.splice(0);
      for (let i = pending.length - 1; i >= 0; i--) socket.unshift(pending[i]);
      socket.removeListener('data', src.onData);
      socket.removeListener('end', src.onEnd);
      socket.removeListener('close', src.onEnd);
      const tlsSock = tls.connect({ socket, servername: host, rejectUnauthorized: false });
      await new Promise((res, rej) => { tlsSock.once('secureConnect', res); tlsSock.once('error', rej); });
      socket = tlsSock;
      src = makeSource(tlsSock);
      return sock;
    },
  };
  return sock;
}
