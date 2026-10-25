// Local HTTP API of the runner. Bound to loopback, every request needs the bearer token from RUNNER_TOKEN.
import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { config } from './config.mjs';
import * as apps from './apps.mjs';
import * as services from './services.mjs';
import { explore } from './explore.mjs';
import { runScenario, version } from './rea.mjs';
import { compareRuns } from './compare.mjs';
import { storeDistribution } from './recipes.mjs';
import { exploreApi } from './api_explore.mjs';

const MAX_JSON = 4 * 1024 * 1024;

function authorized(req) {
  const header = req.headers.authorization || '';
  const given = Buffer.from(header.startsWith('Bearer ') ? header.slice(7) : '');
  const expected = Buffer.from(config.token);
  return expected.length >= 24 && given.length === expected.length && timingSafeEqual(given, expected);
}

async function body(req, limit) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error('BODY_TOO_LARGE'), { status: 413 });
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function json(req) {
  const raw = await body(req, MAX_JSON);
  try { return raw.length ? JSON.parse(raw.toString('utf8')) : {}; } catch { throw Object.assign(new Error('JSON_INVALID'), { status: 400 }); }
}

function send(res, status, payload) {
  const text = JSON.stringify(payload);
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
  res.end(text);
}

const busy = { explore: false, exploreApi: false };

/** Origins the runner may drive: only applications and services it started itself. */
function owned(baseUrl) {
  let origin;
  try { origin = new URL(baseUrl).origin; } catch { throw Object.assign(new Error('URL_INVALID'), { status: 400 }); }
  const known = [...apps.list().map((r) => r.base_url), ...services.list().map((s) => s.base_url)].map((u) => new URL(u).origin);
  if (!known.includes(origin)) throw Object.assign(new Error('ORIGIN_NOT_OWNED'), { status: 403 });
  return origin;
}

export async function health() {
  return {
    status: 'READY', runner: '1',
    tools: { java: !!config.javaPath, chrome: !!config.chromePath, otel_agent: !!config.otelAgentJar, rea: await version(), docker: await services.dockerVersion() },
    apps: apps.list(), services: services.list(),
  };
}

export async function handle(req, res) {
  const url = new URL(req.url, 'http://runner');
  const path = url.pathname;
  try {
    if (!authorized(req)) return send(res, 401, { error: 'UNAUTHORIZED' });
    if (req.method === 'GET' && path === '/v1/health') return send(res, 200, await health());
    let m;
    if (req.method === 'PUT' && (m = path.match(/^\/v1\/artifacts\/([0-9a-f]{64})$/))) return send(res, 201, await apps.storeArtifact(m[1], await body(req, config.maxArtifactBytes)));
    if (req.method === 'POST' && path === '/v1/apps') return send(res, 201, await apps.start(await json(req)));
    if (req.method === 'PUT' && (m = path.match(/^\/v1\/distributions\/([0-9a-f]{64})$/))) return send(res, 201, await storeDistribution(m[1], await body(req, config.maxDistributionBytes)));
    if (req.method === 'POST' && path === '/v1/recipe-runs') return send(res, 201, await apps.startRecipe(await json(req)));
    if (req.method === 'GET' && path === '/v1/apps') return send(res, 200, { items: apps.list() });
    if (req.method === 'DELETE' && (m = path.match(/^\/v1\/apps\/([0-9a-f-]{36})$/))) return send(res, 200, await apps.stop(m[1]));
    if (req.method === 'GET' && (m = path.match(/^\/v1\/apps\/([0-9a-f-]{36})\/log$/))) return send(res, 200, await apps.logTail(m[1]));
    if (req.method === 'POST' && path === '/v1/explore') {
      const input = await json(req);
      const run = apps.get(String(input.run_id || ''));
      if (busy.explore) return send(res, 409, { error: 'EXPLORATION_RUNNING' });
      busy.explore = true;
      try {
        return send(res, 200, await explore({ baseUrl: run.base_url, seeds: input.seeds || [], maxPages: Math.min(Number(input.max_pages) || 40, 200),
          maxForms: Math.min(Number(input.max_forms) || 12, 60), includeForms: input.include_forms !== false, maxDurationMs: Math.min(Number(input.max_duration_ms) || 900000, 3600000) }));
      } finally { busy.explore = false; }
    }
    if (req.method === 'POST' && path === '/v1/explore-api') {
      const input = await json(req);
      const run = apps.get(String(input.run_id || ''));
      if (busy.exploreApi) return send(res, 409, { error: 'EXPLORATION_RUNNING' });
      busy.exploreApi = true;
      try {
        return send(res, 200, await exploreApi({ baseUrl: run.base_url, credential: run.credential, endpoints: Array.isArray(input.endpoints) ? input.endpoints.slice(0, 2000) : [],
          scenarios: Array.isArray(input.scenarios) ? input.scenarios.slice(0, 20) : [], skipPaths: input.skip_paths || [], maxRequests: Math.min(Number(input.max_requests) || 400, 5000),
          maxDurationMs: Math.min(Number(input.max_duration_ms) || 900000, 3600000) }));
      } finally { busy.exploreApi = false; }
    }
    if (req.method === 'POST' && path === '/v1/scenarios') {
      const input = await json(req);
      const origin = owned(input.scenario?.start_url?.url || '');
      return send(res, 200, await runScenario(input.scenario, [origin]));
    }
    if (req.method === 'POST' && path === '/v1/services') return send(res, 201, await services.buildAndRun(await json(req)));
    if (req.method === 'GET' && path === '/v1/services') return send(res, 200, { items: services.list() });
    if (req.method === 'DELETE' && (m = path.match(/^\/v1\/services\/([a-z0-9][a-z0-9-]{0,62})$/))) return send(res, 200, await services.stop(m[1]));
    if (req.method === 'GET' && (m = path.match(/^\/v1\/services\/([a-z0-9][a-z0-9-]{0,62})\/log$/))) return send(res, 200, await services.logs(m[1]));
    if (req.method === 'POST' && path === '/v1/compare') {
      const input = await json(req);
      return send(res, 200, await compareRuns({ ...input, baseline: owned(input.baseline_url || ''), candidate: owned(input.candidate_url || '') }));
    }
    return send(res, 404, { error: 'NOT_FOUND' });
  } catch (error) {
    const status = error.status || (error.code ? 409 : 500);
    return send(res, status, { error: error.code || error.message || 'RUNNER_ERROR', detail: typeof error.detail === 'string' ? error.detail.slice(0, 2000) : undefined });
  }
}

export function serve() {
  if (config.token.length < 24) { console.error('RUNNER_TOKEN must be set to at least 24 characters.'); process.exit(2); }
  const server = createServer((req, res) => { handle(req, res); });
  server.requestTimeout = 0;                                           // explorations and builds can take minutes
  server.listen(config.port, config.host, () => console.log(`ArchIntel runner listening on http://${config.host}:${config.port}`));
  const shutdown = async () => { await apps.stopAll(); await services.stopAll(); process.exit(0); };
  process.on('SIGINT', shutdown); process.on('SIGTERM', shutdown);
  return server;
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) serve();
