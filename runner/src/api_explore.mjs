// API exploration of a running application: the GET endpoints the static analysis found, with path variables filled from
// values seen in earlier responses, plus explicit scenario files for anything that writes. Only the run's own origin is called.
import { randomBytes } from 'node:crypto';

export class ApiError extends Error {
  constructor(code, detail) { super(code); this.code = code; this.detail = detail; }
}

const METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);
const MAX_BODY = 1024 * 1024;
const MAX_VALUES = 20;

/** `/api/v1/org/{orgName: .*}/project` -> { template, variables: ['orgName'] } with regex constraints removed. */
export function parseTemplate(path) {
  const variables = [];
  const template = path.replace(/\{\s*([A-Za-z_][\w]*)\s*(:[^}]*)?\}/g, (_, name) => { variables.push(name); return `{${name}}`; });
  return { template: template.replace(/\/+$/, '') || '/', variables };
}

/** Collects scalar values from JSON responses, by field name and by the resource path they came from. */
export class Values {
  constructor() { this.byField = new Map(); this.byResource = new Map(); }

  static resource(path) {
    const literals = path.split('?')[0].split('/').filter((s) => s && !/^\d+$/.test(s) && !/^[0-9a-f-]{36}$/i.test(s));
    return (literals.pop() || '').toLowerCase();
  }

  /** Keeps the most recently seen values: a value seen again moves to the end, the oldest is dropped beyond the cap. */
  add(key, value, store) {
    const set = store.get(key) || new Set();
    set.delete(value);
    set.add(value);
    if (set.size > MAX_VALUES) set.delete(set.values().next().value);
    store.set(key, set);
  }

  learn(path, body) {
    const resource = Values.resource(path);
    // Only the response object itself, or the items of a top-level list, describe the resource; nested objects
    // (status history, checkpoints, ...) feed the by-field index only.
    const walk = (node, depth, own) => {
      if (depth > 6 || node === null) return;
      if (Array.isArray(node)) { node.slice(0, 50).forEach((item) => walk(item, depth + 1, own && depth === 0)); return; }
      if (typeof node !== 'object') return;
      for (const [key, value] of Object.entries(node)) {
        if ((typeof value === 'string' && value.length > 0 && value.length <= 200 && !value.includes('/')) || typeof value === 'number') {
          this.add(key.toLowerCase(), String(value), this.byField);
          if (own) this.add(`${resource}.${key.toLowerCase()}`, String(value), this.byResource);
        } else walk(value, depth + 1, false);
      }
    };
    walk(body, 0, true);
  }

  /**
   * Candidate values for one path variable, most specific first: the same field of the preceding resource
   * (`/process/{id}` -> process.id, process.processId, process.instanceId), then name/id of the resource the variable
   * names (`{orgName}` -> org.name), then the field anywhere. Generic `id`/`name` never fall back to any response.
   * Within one field the newest values come first, so data a scenario just created is preferred over seed data.
   */
  candidates(variable, preceding) {
    const lower = variable.toLowerCase();
    const out = [];
    const push = (set) => { for (const v of [...(set || [])].reverse()) if (!out.includes(v)) out.push(v); };
    const suffix = lower.endsWith('name') ? 'name' : lower.endsWith('id') ? 'id' : null;
    const base = suffix ? lower.slice(0, -suffix.length) : lower;
    const resources = [...new Set([preceding?.toLowerCase(), base, `${base}s`].filter(Boolean))];
    for (const resource of resources) {
      push(this.byResource.get(`${resource}.${lower}`));
      if (suffix) for (const field of [suffix, `${resource}${suffix}`, `instance${suffix}`]) push(this.byResource.get(`${resource}.${field}`));
    }
    if (!['id', 'name'].includes(lower)) push(this.byField.get(lower));
    return out;
  }
}

/** Concrete paths for a template, or null with the variables that had no value. */
export function expand(template, variables, values, limit = 3) {
  let paths = [template];
  const missing = [];
  for (const variable of variables) {
    const before = template.split(`{${variable}}`)[0].split('/').filter((s) => s && !s.startsWith('{')).pop();
    const options = values.candidates(variable, before).slice(0, limit);
    if (!options.length) { missing.push(variable); continue; }
    paths = paths.flatMap((p) => options.map((o) => p.replace(`{${variable}}`, encodeURIComponent(o))));
  }
  return missing.length ? { paths: [], missing } : { paths: paths.slice(0, limit), missing };
}

function substitute(value, vars) {
  if (typeof value === 'string') return value.replace(/\$\{([A-Za-z_][\w]*)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  if (Array.isArray(value)) return value.map((v) => substitute(v, vars));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, substitute(v, vars)]));
  return value;
}

function pick(body, path) {
  let node = body;
  for (const part of String(path).split('.').filter(Boolean)) {
    if (node === null || node === undefined) return undefined;
    node = Array.isArray(node) && /^\d+$/.test(part) ? node[Number(part)] : node[part];
  }
  return node;
}

/** Route templates the crawl must not call, e.g. long-polling endpoints; plain regular expressions, bounded in number and length. */
export function compileSkips(patterns) {
  if (!Array.isArray(patterns) || patterns.length > 20) throw new ApiError('SKIP_PATHS_INVALID');
  return patterns.map((p) => {
    if (typeof p !== 'string' || !p || p.length > 200) throw new ApiError('SKIP_PATHS_INVALID');
    try { return new RegExp(p); } catch { throw new ApiError('SKIP_PATHS_INVALID', p); }
  });
}

export function validateScenario(scenario) {
  if (!scenario || typeof scenario !== 'object' || typeof scenario.name !== 'string' || scenario.name.length > 120) throw new ApiError('SCENARIO_INVALID');
  const check = (steps, label) => {
    if (steps === undefined) return [];
    if (!Array.isArray(steps) || steps.length > 100) throw new ApiError('SCENARIO_INVALID', label);
    return steps.map((s, i) => {
      if (!METHODS.has(s?.method) || typeof s.path !== 'string' || !s.path.startsWith('/') || s.path.startsWith('//') || s.path.length > 500) throw new ApiError('SCENARIO_STEP_INVALID', `${label} ${i + 1}`);
      if ([s.json, s.multipart, s.text].filter((b) => b !== undefined).length > 1) throw new ApiError('SCENARIO_STEP_INVALID', `${label} ${i + 1}: one of json, multipart or text`);
      if (s.text !== undefined && (typeof s.text !== 'string' || s.text.length > 100000)) throw new ApiError('SCENARIO_STEP_INVALID', `${label} ${i + 1}: text must be a string`);
      let until = null;
      if (s.until !== undefined) {
        if (s.method !== 'GET' || typeof s.until?.path !== 'string' || !Array.isArray(s.until.in) || !s.until.in.length || s.until.in.length > 20) throw new ApiError('SCENARIO_STEP_INVALID', `${label} ${i + 1}: until needs a GET, a path and values`);
        until = { path: s.until.path, in: s.until.in.map(String), success: (Array.isArray(s.until.success) && s.until.success.length ? s.until.success : s.until.in).map(String), timeout_ms: Math.min(Math.max(Number(s.until.timeout_ms) || 120000, 1000), 600000),
          interval_ms: Math.min(Math.max(Number(s.until.interval_ms) || 2000, 500), 30000) };
      }
      if (s.basic_auth !== undefined && (typeof s.basic_auth?.username !== 'string' || typeof s.basic_auth?.password !== 'string')) throw new ApiError('SCENARIO_STEP_INVALID', `${label} ${i + 1}: basic_auth needs a username and a password`);
      return { id: String(s.id || `${label}-${i + 1}`).slice(0, 80), method: s.method, path: s.path, json: s.json, multipart: s.multipart, text: s.text, until,
        basic_auth: s.basic_auth ? { username: s.basic_auth.username, password: s.basic_auth.password } : null,
        expect: Array.isArray(s.expect) ? s.expect.map(Number) : null, extract: s.extract && typeof s.extract === 'object' ? s.extract : {} };
    });
  };
  return { name: scenario.name, description: String(scenario.description || '').slice(0, 500), steps: check(scenario.steps, 'step'), cleanup: check(scenario.cleanup, 'cleanup') };
}

/**
 * Explore one origin. `fetcher` is injectable for tests. Returns every request (bounded), the endpoint coverage of the
 * static GET routes and the scenario results. Credentials are sent but never returned.
 */
export async function exploreApi({ baseUrl, credential = null, endpoints = [], scenarios = [], skipPaths = [], variables = {}, maxRequests = 400, maxDurationMs = 15 * 60 * 1000 }, fetcher = fetch) {
  const origin = new URL(baseUrl).origin;
  const started = Date.now();
  const values = new Values();
  const requests = [];
  const vars = { ...variables, RUN_ID: randomBytes(4).toString('hex') };
  const budget = () => requests.length < maxRequests && Date.now() - started < maxDurationMs;
  const checked = scenarios.map(validateScenario);
  const skip = compileSkips(skipPaths);

  async function call(method, path, phase, { json, multipart, text, basicAuth = null, template = null } = {}) {
    const url = new URL(path, origin);
    if (url.origin !== origin) throw new ApiError('ORIGIN_NOT_ALLOWED', path);
    const headers = { accept: 'application/json, text/plain, */*' };
    if (credential) headers[credential.header.toLowerCase()] = credential.value;
    // A step may log in as someone else (for example an LDAP user) instead of using the run's credential.
    if (basicAuth) { delete headers[(credential?.header || 'authorization').toLowerCase()]; headers.authorization = 'Basic ' + Buffer.from(`${basicAuth.username}:${basicAuth.password}`).toString('base64'); }
    let body;
    if (json !== undefined) { headers['content-type'] = 'application/json'; body = JSON.stringify(json); }
    if (text !== undefined) { headers['content-type'] = 'text/plain'; body = text; }
    if (multipart !== undefined) {
      body = new FormData();
      for (const [name, value] of Object.entries(multipart)) {
        if (value && typeof value === 'object') body.append(name, new Blob([String(value.content ?? '')], { type: value.type || 'application/octet-stream' }), value.filename || name);
        else body.append(name, String(value));
      }
    }
    const t0 = Date.now();
    const record = { phase, method, template: template || url.pathname, path: url.pathname + url.search, status: null, duration_ms: null, error: null };
    let parsed;
    try {
      const response = await fetcher(url, { method, headers, body, redirect: 'manual', signal: AbortSignal.timeout(20000) });
      record.status = response.status;
      const text = (await response.text()).slice(0, MAX_BODY);
      if ((response.headers.get('content-type') || '').includes('json')) {
        try { parsed = JSON.parse(text); } catch { parsed = undefined; }
      }
      if (parsed !== undefined && response.status < 400) values.learn(url.pathname, parsed);
    } catch (error) {
      record.error = error.name === 'TimeoutError' ? 'TIMEOUT' : String(error.code || error.name || error).slice(0, 120);
    }
    record.duration_ms = Date.now() - t0;
    requests.push(record);
    return { record, body: parsed };
  }

  const routes = new Map();
  const skipped = [];
  for (const e of endpoints) {
    if (e?.method !== 'GET' || typeof e.path !== 'string' || !e.path.startsWith('/')) continue;
    const parsed = parseTemplate(e.path);
    if (skip.some((pattern) => pattern.test(parsed.template))) { skipped.push(parsed.template); continue; }
    routes.set(parsed.template, parsed);
  }
  const called = new Set();
  const ordered = [...routes.values()].sort((a, b) => a.variables.length - b.variables.length || a.template.localeCompare(b.template));
  const crawl = async (phase, withVariables) => {
    for (const route of ordered) {
      if (!budget()) return;
      if (route.variables.length ? !withVariables || called.has(route.template) : false) continue;
      const { paths } = expand(route.template, route.variables, values);
      if (!paths.length) continue;
      called.add(route.template);
      for (const path of paths) { if (budget()) await call('GET', path, phase, { template: route.template }); }
    }
  };

  const scenarioResults = [];
  const runSteps = async (scenario, steps, kind) => {
    const results = [];
    for (const step of steps) {
      if (!budget()) { results.push({ id: step.id, state: 'SKIPPED_BUDGET' }); continue; }
      // A value an earlier step should have extracted is missing: sending the literal placeholder would only produce noise.
      const missing = [...new Set([...substitute(step.path, vars).matchAll(/\$\{([A-Za-z_][\w]*)\}/g)].map((m) => m[1]))];
      if (missing.length) {
        results.push({ id: step.id, kind, method: step.method, path: step.path, status: null, state: 'SKIPPED_MISSING_VALUE', error: `no value for ${missing.join(', ')}` });
        continue;
      }
      let { record, body } = await call(step.method, substitute(step.path, vars), `scenario:${scenario.name}`, { json: substitute(step.json, vars), multipart: substitute(step.multipart, vars), text: substitute(step.text, vars), basicAuth: substitute(step.basic_auth, vars) });
      // A polling step repeats its GET until the field at until.path holds one of until.in, or its timeout passes.
      let reached = null;
      if (step.until) {
        const deadline = Date.now() + step.until.timeout_ms;
        while (!step.until.in.includes(String(pick(body, step.until.path))) && record.error === null && record.status < 400 && Date.now() < deadline && budget()) {
          await new Promise((r) => setTimeout(r, step.until.interval_ms));
          ({ record, body } = await call(step.method, substitute(step.path, vars), `scenario:${scenario.name}`));
        }
        reached = pick(body, step.until.path) ?? null;
      }
      const ok = record.error === null && (step.expect ? step.expect.includes(record.status) : record.status < 400) && (!step.until || step.until.success.includes(String(reached)));
      for (const [name, path] of Object.entries(step.extract)) {
        const value = pick(body, path);
        if (value !== undefined && value !== null && typeof value !== 'object') vars[name] = value;
      }
      results.push({ id: step.id, kind, method: step.method, path: record.path, status: record.status, state: ok ? 'PASSED' : 'FAILED', error: record.error,
        ...(step.until ? { reached: reached === null ? null : String(reached).slice(0, 120) } : {}) });
    }
    return results;
  };

  // Baseline reads, then the scenarios create data, then lists are read again so parameterised routes can use what exists.
  await crawl('crawl', false);
  for (const scenario of checked) {
    const steps = await runSteps(scenario, scenario.steps, 'step');
    scenarioResults.push({ name: scenario.name, steps });
  }
  await crawl('crawl-after-scenarios', true);
  for (const [index, scenario] of checked.entries()) scenarioResults[index].cleanup = await runSteps(scenario, scenario.cleanup, 'cleanup');

  const unresolved = [...routes.values()].filter((r) => !called.has(r.template))
    .map((r) => ({ template: r.template, missing: expand(r.template, r.variables, values).missing }));
  const statuses = {};
  for (const r of requests) { const key = r.status ? `${Math.floor(r.status / 100)}xx` : 'error'; statuses[key] = (statuses[key] || 0) + 1; }
  return {
    origin, duration_ms: Date.now() - started, stopped_by_budget: !budget() && (requests.length >= maxRequests || Date.now() - started >= maxDurationMs),
    summary: { requests: requests.length, get_routes: routes.size, get_routes_called: called.size, statuses,
      scenario_steps: scenarioResults.reduce((n, s) => n + s.steps.length, 0), scenario_steps_passed: scenarioResults.reduce((n, s) => n + s.steps.filter((x) => x.state === 'PASSED').length, 0) },
    requests: requests.slice(0, 1000), scenarios: scenarioResults, unresolved: unresolved.slice(0, 200), skipped: [...new Set(skipped)].slice(0, 100),
  };
}
