// Run one REA browser scenario and reduce its Evidence to what ArchIntel needs.
import { execFile } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { config } from './config.mjs';

export class ReaError extends Error {
  constructor(code, detail) { super(code); this.code = code; this.detail = detail; }
}

function exec(command, args, timeoutMs) {
  return new Promise((resolve) => {
    execFile(command, args, { timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024, env: { ...process.env, NO_COLOR: '1' } },
      (error, stdout, stderr) => resolve({ code: error ? (typeof error.code === 'number' ? error.code : 1) : 0, stdout, stderr, killed: !!error?.killed }));
  });
}

/** Enforce the runner's browser and the allowed origins; callers never choose the executable or a remote site. */
export function prepare(scenario, allowedOrigins) {
  const start = new URL(scenario.start_url?.url);
  if (!allowedOrigins.includes(start.origin)) throw new ReaError('ORIGIN_NOT_ALLOWED', start.origin);
  for (const action of scenario.actions || []) {
    if (action.action === 'goto' && !allowedOrigins.includes(new URL(action.destination?.url).origin)) throw new ReaError('ORIGIN_NOT_ALLOWED', action.destination?.url);
  }
  return { ...scenario, browser: { mode: 'launch', executable_path: config.chromePath, headless: true } };
}

export async function runScenario(scenario, allowedOrigins, { timeoutMs = 180000 } = {}) {
  const checked = prepare(scenario, allowedOrigins);
  const dir = await mkdtemp(join(tmpdir(), 'archintel-rea-'));
  try {
    const file = join(dir, 'scenario.json');
    await writeFile(file, JSON.stringify(checked));
    const [command, ...prefix] = config.reaCommand;
    const result = await exec(command, [...prefix, 'capture-browser-scenario', file, '--json'], timeoutMs);
    if (result.killed) throw new ReaError('REA_TIMEOUT');
    let evidence;
    try { evidence = JSON.parse(result.stdout); } catch { throw new ReaError('REA_OUTPUT_INVALID', result.stderr.slice(0, 2000)); }
    if (result.code !== 0 || !evidence.normalized_result) throw new ReaError('REA_FAILED', (evidence?.error?.message || result.stderr || '').slice(0, 2000));
    return summarize(evidence);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Steps, page-level transactions and captured DOM text; asset requests (css, images, fonts) are dropped. */
export function summarize(evidence) {
  const r = evidence.normalized_result;
  const pages = new Map();
  for (const e of r.events?.items || []) {
    if (!['document', 'xhr', 'fetch'].includes(e.resource_type)) continue;
    const t = pages.get(e.transaction_id) || { transaction_id: e.transaction_id, method: e.method, url: e.url?.url, resource_type: e.resource_type, step_index: e.step_index, status: null, failure: null };
    if (e.kind === 'response') t.status = e.status;
    if (e.failure) t.failure = typeof e.failure === 'string' ? e.failure : JSON.stringify(e.failure).slice(0, 300);
    pages.set(e.transaction_id, t);
  }
  return {
    evidence_id: evidence.evidence_id,
    scenario_sha256: evidence.parameters?.scenario_sha256 || null,
    duration_ms: r.duration_ms,
    completeness: r.completeness?.status,
    steps: (r.steps || []).map((s) => ({
      step_index: s.step_index, step_id: s.step_id, action: s.action, status: s.status,
      error: s.error ? (s.error.message || s.error.code || JSON.stringify(s.error)).slice(0, 500) : null,
      url: s.after_url?.url || null,
      dom: s.artifacts?.dom?.state === 'captured' ? s.artifacts.dom.value?.text ?? null : null,
    })),
    transactions: [...pages.values()],
    events_dropped: r.events?.dropped ?? 0,
    limitations: (r.limitations || []).slice(0, 10),
  };
}

export async function version() {
  const [command, ...prefix] = config.reaCommand;
  const result = await exec(command, [...prefix, '--version'], 30000);
  return result.code === 0 ? result.stdout.trim().split('\n').pop() : null;
}
