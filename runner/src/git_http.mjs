// Read-only smart-HTTP Git server for a run's fixture repositories: `git http-backend` behind a loopback listener.
// Only clone and fetch (git-upload-pack) are served; pushes (git-receive-pack) and every other path are refused.
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { config } from './config.mjs';

const ALLOWED = /^\/[a-z][a-z0-9-]{0,30}\.git\/(info\/refs|git-upload-pack|HEAD|objects\/.+)$/;

export function allowed(method, path, query) {
  if (!ALLOWED.test(path) || path.includes('..')) return false;
  if (path.endsWith('/info/refs')) return method === 'GET' && query === 'service=git-upload-pack';
  if (path.endsWith('/git-upload-pack')) return method === 'POST';
  return method === 'GET';
}

/** Serve `root` (a folder of bare repositories) on 127.0.0.1:port; resolves to an object with close(). */
export function serveRepositories(root, port) {
  const server = createServer((req, res) => {
    const url = new URL(req.url, 'http://git');
    const query = url.search.slice(1);
    if (!allowed(req.method, url.pathname, query)) { res.writeHead(403); res.end(); return; }
    const child = spawn(config.gitPath, ['http-backend'], { env: {
      GIT_PROJECT_ROOT: root, GIT_HTTP_EXPORT_ALL: '1', PATH_INFO: url.pathname, QUERY_STRING: query, REQUEST_METHOD: req.method,
      CONTENT_TYPE: req.headers['content-type'] || '', CONTENT_LENGTH: req.headers['content-length'] || '', HTTP_CONTENT_ENCODING: req.headers['content-encoding'] || '',
      GIT_PROTOCOL: req.headers['git-protocol'] || '', REMOTE_ADDR: '127.0.0.1', PATH: process.env.PATH } });
    req.pipe(child.stdin);
    let head = Buffer.alloc(0);
    let sent = false;
    child.stdout.on('data', (chunk) => {
      if (sent) { res.write(chunk); return; }
      head = Buffer.concat([head, chunk]);
      const end = head.indexOf('\r\n\r\n');
      if (end < 0) return;
      // CGI response: header lines (with an optional Status), a blank line, then the body.
      let status = 200;
      const headers = {};
      for (const line of head.subarray(0, end).toString('latin1').split('\r\n')) {
        const i = line.indexOf(':');
        if (i < 0) continue;
        const name = line.slice(0, i).trim();
        const value = line.slice(i + 1).trim();
        if (name.toLowerCase() === 'status') status = Number.parseInt(value, 10) || 200; else headers[name] = value;
      }
      res.writeHead(status, headers);
      res.write(head.subarray(end + 4));
      sent = true;
    });
    child.on('close', () => { if (!sent) { res.writeHead(502); } res.end(); });
    child.on('error', () => { if (!sent) res.writeHead(502); res.end(); });
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => resolve({ port, close: () => new Promise((r) => server.close(() => r())) }));
  });
}
