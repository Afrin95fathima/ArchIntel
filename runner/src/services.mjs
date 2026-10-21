// Build a generated Java service with the runner's own Dockerfile and run it in a constrained local container.
import { execFile } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { dirname, join, normalize, sep } from 'node:path';
import { config } from './config.mjs';

export class ServiceError extends Error {
  constructor(code, detail) { super(code); this.code = code; this.detail = detail; }
}

const NAME = /^[a-z0-9][a-z0-9-]{0,62}$/;
const services = new Map();
const MAX_FILES = 300;
const MAX_BYTES = 8 * 1024 * 1024;

// Generated code never supplies its own Dockerfile: the build recipe is this fixed file, shared with ArchIntel's deployment package.
export const DOCKERFILE = readFileSync(join(config.root, 'recipe', 'Dockerfile'), 'utf8');

function run(args, timeoutMs, input) {
  return new Promise((resolve) => {
    const child = execFile('docker', args, { timeout: timeoutMs, maxBuffer: 32 * 1024 * 1024 }, (error, stdout, stderr) =>
      resolve({ code: error ? (typeof error.code === 'number' ? error.code : 1) : 0, stdout, stderr, killed: !!error?.killed }));
    if (input) { child.stdin.end(input); }
  });
}

export async function dockerVersion() {
  const r = await run(['version', '--format', '{{.Server.Version}}'], 15000);
  return r.code === 0 ? r.stdout.trim() : null;
}

/** Relative, normalised, inside the service folder; no Dockerfile or build-hook overrides. */
export function safePath(path) {
  if (typeof path !== 'string' || !path || path.length > 300 || path.startsWith('/') || path.includes('\\') || path.includes('\0')) throw new ServiceError('FILE_PATH_INVALID', path);
  const clean = normalize(path);
  if (clean.startsWith('..') || clean.split(sep).includes('..')) throw new ServiceError('FILE_PATH_INVALID', path);
  const base = clean.split(sep).pop().toLowerCase();
  if (['dockerfile', '.dockerignore', 'containerfile'].includes(base) || clean.startsWith('.mvn') || clean.startsWith('.git')) throw new ServiceError('FILE_PATH_NOT_ALLOWED', path);
  return clean;
}

function free(port) {
  return new Promise((resolve) => {
    const s = createServer().once('error', () => resolve(false)).once('listening', () => s.close(() => resolve(true)));
    s.listen(port, '127.0.0.1');
  });
}

async function port() {
  const used = new Set([...services.values()].map((s) => s.port));
  for (let p = config.appPorts[1] + 1; p <= config.appPorts[1] + 40; p += 1) if (!used.has(p) && await free(p)) return p;
  throw new ServiceError('NO_FREE_PORT');
}

async function ready(base, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { const r = await fetch(base + '/', { redirect: 'manual', signal: AbortSignal.timeout(3000) }); if (r.status < 500) return true; } catch { /* starting */ }
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}

export async function buildAndRun({ name, files, build_timeout_ms = 20 * 60 * 1000, ready_timeout_ms = 180000 }) {
  if (!NAME.test(name || '')) throw new ServiceError('SERVICE_NAME_INVALID');
  if (!Array.isArray(files) || !files.length || files.length > MAX_FILES) throw new ServiceError('FILE_COUNT_INVALID');
  let total = 0;
  const checked = files.map((f) => {
    if (typeof f?.content !== 'string') throw new ServiceError('FILE_CONTENT_INVALID', f?.path);
    total += Buffer.byteLength(f.content);
    return { path: safePath(f.path), content: f.content };
  });
  if (total > MAX_BYTES) throw new ServiceError('FILES_TOO_LARGE');
  if (!checked.some((f) => f.path === 'pom.xml')) throw new ServiceError('POM_MISSING');
  if (!await dockerVersion()) throw new ServiceError('DOCKER_UNAVAILABLE');
  if (services.has(name)) await stop(name);

  const dir = join(config.workDir, 'services', name);
  await rm(dir, { recursive: true, force: true });
  for (const f of checked) {
    const target = join(dir, f.path);
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, f.content);
  }
  await writeFile(join(dir, 'Dockerfile'), DOCKERFILE);
  await writeFile(join(dir, '.dockerignore'), 'target\n.git\n');
  const image = `archintel-svc/${name}:candidate`;
  const build = await run(['build', '--pull=false', '-t', image, dir], build_timeout_ms);
  const record = { name, image, port: null, base_url: null, container: `archintel-svc-${name}`, state: 'BUILD_FAILED', built_at: new Date().toISOString(),
    build_log: (build.stdout + build.stderr).slice(-12000) };
  if (build.code !== 0) { record.state = build.killed ? 'BUILD_TIMEOUT' : 'BUILD_FAILED'; services.set(name, record); return view(record); }

  record.port = await port();
  record.base_url = `http://127.0.0.1:${record.port}`;
  await run(['rm', '-f', record.container], 30000);
  const started = await run(['run', '-d', '--name', record.container, '-p', `127.0.0.1:${record.port}:8080`,
    '--memory', '768m', '--cpus', '1', '--pids-limit', '256', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--read-only', '--tmpfs', '/tmp:rw,size=128m', '--label', 'archintel.service=' + name, image], 60000);
  if (started.code !== 0) { record.state = 'START_FAILED'; record.run_log = started.stderr.slice(-4000); services.set(name, record); return view(record); }
  services.set(name, record);
  record.state = await ready(record.base_url, ready_timeout_ms) ? 'RUNNING' : 'NOT_READY';
  return view(record);
}

export async function stop(name) {
  const record = services.get(name);
  if (!record) throw new ServiceError('SERVICE_NOT_FOUND');
  await run(['rm', '-f', record.container], 60000);
  services.delete(name);
  return { name, stopped: true };
}

export async function logs(name) {
  const record = services.get(name);
  if (!record) throw new ServiceError('SERVICE_NOT_FOUND');
  if (!record.port) return { name, text: record.build_log || record.run_log || '' };
  const r = await run(['logs', '--tail', '200', record.container], 30000);
  return { name, text: (r.stdout + r.stderr).slice(-20000) };
}

export function view(r) { return { name: r.name, state: r.state, image: r.image, base_url: r.base_url, port: r.port, built_at: r.built_at, build_log_tail: r.state === 'RUNNING' ? undefined : (r.build_log || r.run_log || '').slice(-4000) }; }
export function list() { return [...services.values()].filter((s) => s.base_url).map(view); }
export async function stopAll() { for (const name of [...services.keys()]) await stop(name).catch(() => {}); }
