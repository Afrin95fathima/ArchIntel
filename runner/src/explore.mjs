// Breadth-first exploration of a running web application with REA browser scenarios.
import { forms as parseForms, links as parseLinks, pageUrl, routeShape } from './html.mjs';
import { formActions } from './fill.mjs';
import { runScenario } from './rea.mjs';

const DESTRUCTIVE = /(^|\/)(delete|remove|destroy|drop|logout|signout|sign-out|log-out|purge|reset)(\/|$|\?)/i;
const PATH = /^\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*(\?[^#\s]*)?$/;

export function validSeeds(seeds = []) {
  return seeds.filter((s) => typeof s === 'string' && PATH.test(s) && !s.includes('{') && !DESTRUCTIVE.test(s)).slice(0, 200);
}

/**
 * Explore one origin. `run` is injectable so tests can replace REA.
 * Returns pages, forms and every page-level HTTP transaction REA observed, with the Evidence ids behind them.
 */
export async function explore({ baseUrl, seeds = [], maxPages = 40, maxForms = 12, batch = 8, maxDurationMs = 15 * 60 * 1000, includeForms = true }, run = runScenario) {
  const origin = new URL(baseUrl).origin;
  const started = Date.now();
  const queue = [];
  const queued = new Set();
  const pages = [];
  const formResults = [];
  const formKeys = new Set();
  const pendingForms = [];
  const transactions = [];
  const evidence = [];
  const skipped = [];
  const failures = [];

  const enqueue = (url, from) => {
    const shape = routeShape(url);
    if (queued.has(shape)) return;
    if (DESTRUCTIVE.test(new URL(url).pathname)) { skipped.push({ url, reason: 'DESTRUCTIVE_LOOKING_LINK', from }); queued.add(shape); return; }
    queued.add(shape);
    queue.push(url);
  };
  enqueue(origin + '/', null);
  for (const seed of validSeeds(seeds)) enqueue(origin + seed, 'static-entry-point');

  const learn = (html, url) => {
    for (const link of parseLinks(html, url)) enqueue(link, url);
    if (!includeForms) return;
    for (const form of parseForms(html, url)) {
      const key = `${form.method} ${routeShape(form.action)} ${form.fields.map((f) => f.name).sort().join(',')}`;
      if (formKeys.has(key)) continue;
      formKeys.add(key);
      pendingForms.push({ page: url, form, key });
    }
  };
  const timeLeft = () => Date.now() - started < maxDurationMs;

  while ((queue.length || pendingForms.length) && timeLeft()) {
    if (queue.length && pages.length < maxPages) {
      const wave = queue.splice(0, Math.min(batch, maxPages - pages.length));
      const scenario = {
        start_url: { url: wave[0] },
        actions: [
          { step_id: 'p0-settle', action: 'wait_for_timeout', duration_ms: 300 },
          ...wave.slice(1).map((url, i) => ({ step_id: `p${i + 1}`, action: 'goto', destination: { url }, wait_until: 'load', timeout_ms: 30000 })),
        ],
        capture: { after_each_step: ['dom'], at_end: ['url'], events: ['network'] },
      };
      try {
        const result = await run(scenario, [origin]);
        evidence.push(result.evidence_id);
        transactions.push(...result.transactions.map((t) => ({ ...t, evidence_id: result.evidence_id })));
        // Step 0 is the start navigation, step 1 the settle wait on the first page, then one goto per further page.
        const byUrl = new Map(wave.map((u, i) => [u, i === 0 ? result.steps.find((s) => s.step_id === 'p0-settle') : result.steps.find((s) => s.step_id === `p${i}`)]));
        for (const [url, step] of byUrl) {
          const status = result.transactions.find((t) => t.method === 'GET' && t.url && pageUrl(t.url, url) === pageUrl(url, url))?.status ?? null;
          pages.push({ url, shape: routeShape(url), status, step_status: step?.status ?? 'missing', evidence_id: result.evidence_id });
          if (step?.status !== 'completed') failures.push({ url, error: step?.error || 'STEP_NOT_COMPLETED' });
          if (step?.dom) learn(step.dom, step.url || url);
        }
      } catch (error) {
        for (const url of wave) { pages.push({ url, shape: routeShape(url), status: null, step_status: 'failed', evidence_id: null }); failures.push({ url, error: error.code || String(error) }); }
      }
      continue;
    }
    if (!pendingForms.length || formResults.length >= maxForms) break;
    const { page, form, key } = pendingForms.shift();
    const actions = formActions(form, key, `form${formResults.length}`);
    if (!actions) { skipped.push({ url: form.action, reason: form.submit ? 'CREDENTIAL_FORM' : 'NO_SUBMIT_CONTROL', from: page }); continue; }
    try {
      const result = await run({ start_url: { url: page }, actions, capture: { at_end: ['dom', 'url'], events: ['network'] } }, [origin]);
      evidence.push(result.evidence_id);
      transactions.push(...result.transactions.map((t) => ({ ...t, evidence_id: result.evidence_id })));
      const submitted = result.transactions.filter((t) => t.method === form.method || (form.method === 'GET' && t.method === 'GET' && t.step_index > 0));
      const last = result.steps[result.steps.length - 1];
      const ok = result.steps.every((s) => s.status === 'completed');
      formResults.push({ page, method: form.method, action: form.action, shape: routeShape(form.action), fields: form.fields.map((f) => f.name),
        completed: ok, statuses: submitted.map((t) => t.status), final_url: last?.url ?? null, evidence_id: result.evidence_id,
        error: ok ? null : result.steps.find((s) => s.status !== 'completed')?.error ?? 'STEP_NOT_COMPLETED' });
      if (last?.dom) learn(last.dom, last.url || page);
    } catch (error) {
      formResults.push({ page, method: form.method, action: form.action, shape: routeShape(form.action), fields: form.fields.map((f) => f.name), completed: false, statuses: [], final_url: null, evidence_id: null, error: error.code || String(error) });
    }
  }

  const routes = new Map();
  for (const t of transactions) {
    if (!t.url) continue;
    const key = `${t.method} ${routeShape(t.url)}`;
    const entry = routes.get(key) || { method: t.method, shape: routeShape(t.url), statuses: [] };
    if (t.status !== null && !entry.statuses.includes(t.status)) entry.statuses.push(t.status);
    routes.set(key, entry);
  }
  return {
    origin, duration_ms: Date.now() - started, stopped_by_time: !timeLeft(),
    pages, forms: formResults, routes: [...routes.values()].sort((a, b) => a.shape.localeCompare(b.shape) || a.method.localeCompare(b.method)),
    unvisited: queue.slice(0, 50), skipped, failures, evidence_ids: [...new Set(evidence)], transactions,
  };
}
