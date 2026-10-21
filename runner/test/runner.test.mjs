import { test } from 'node:test';
import assert from 'node:assert/strict';

process.env.RUNNER_TOKEN = 'test-token-0123456789abcdefghij';
process.env.RUNNER_CHROME = process.execPath;            // any existing file; tests never launch a browser
const { mkdtempSync } = await import('node:fs');
const { tmpdir } = await import('node:os');
process.env.RUNNER_WORK_DIR = mkdtempSync(`${tmpdir()}/runner-test-`);

const { links, forms, routeShape, pageUrl } = await import('../src/html.mjs');
const { valueFor, formActions } = await import('../src/fill.mjs');
const { explore, validSeeds } = await import('../src/explore.mjs');
const { compareRuns, visibleText, similarity } = await import('../src/compare.mjs');
const { prepare, summarize } = await import('../src/rea.mjs');
const { otelEnvironment, storeArtifact } = await import('../src/apps.mjs');
const { safePath, DOCKERFILE } = await import('../src/services.mjs');
const { handle } = await import('../src/server.mjs');

const OWNER_FORM = `<html><body>
<a href="/owners/find">Find</a><a href="/owners/3;jsessionid=AB12">Owner</a><a href="https://elsewhere.example/x">Out</a>
<a href="/resources/css/app.css">css</a><a href="#top">top</a><a href="mailto:a@b.c">m</a>
<form id="add-owner-form" method="post" class="x">
 <input type="hidden" name="_csrf" value="t"><input name="firstName" required><input name="telephone" type="text">
 <select name="type"><option value="">--</option><option value="cat">Cat</option></select>
 <textarea name="description"></textarea><input type="checkbox" name="agree">
 <button type="submit">Add</button></form>
<form action="/owners" method="get"><input name="lastName"><button>Find</button></form>
<form action="/login" method="post"><input name="user"><input type="password" name="pw"><button type="submit">Go</button></form>
</body></html>`;

test('links keep same-origin pages only, drop assets, fragments and session ids', () => {
  assert.deepEqual(links(OWNER_FORM, 'http://app.test/owners/new'), ['http://app.test/owners/3', 'http://app.test/owners/find']);
  assert.equal(pageUrl('/x;jsessionid=99/y', 'http://app.test/'), 'http://app.test/x/y');
});

test('forms list fields with single-element selectors and skip hidden inputs', () => {
  const [owner, search, login] = forms(OWNER_FORM, 'http://app.test/owners/new');
  assert.equal(owner.method, 'POST');
  assert.equal(owner.action, 'http://app.test/owners/new');
  assert.deepEqual(owner.fields.map((f) => `${f.name}:${f.kind}`), ['firstName:input', 'telephone:input', 'agree:checkbox', 'type:select', 'description:input']);
  assert.equal(owner.fields.find((f) => f.name === 'type').options[0], 'cat');
  assert.equal(owner.submit, ':nth-match(form#add-owner-form [type="submit"], 1)');
  assert.equal(search.method, 'GET');
  assert.equal(search.submit, ':nth-match(:nth-match(form, 2) button, 1)');
  assert.equal(login.fields.some((f) => f.type === 'password'), true);
});

test('route shapes collapse numeric ids, query values and session ids', () => {
  assert.equal(routeShape('http://a.test/owners/12;jsessionid=X/pets/3?b=1&a=2'), '/owners/{id}/pets/{id}?a&b');
});

test('synthetic values are fake and deterministic, and credential forms are never filled', () => {
  assert.match(valueFor({ name: 'email', type: 'text', kind: 'input' }, 's'), /@example\.test$/);
  assert.match(valueFor({ name: 'telephone', type: 'text', kind: 'input' }, 's'), /^\d{10}$/);
  assert.equal(valueFor({ name: 'telephone', type: 'text', kind: 'input' }, 's'), valueFor({ name: 'telephone', type: 'text', kind: 'input' }, 's'));
  assert.equal(valueFor({ name: 'pw', type: 'password', kind: 'input' }, 's'), null);
  const [, , login] = forms(OWNER_FORM, 'http://app.test/');
  assert.equal(formActions(login, 's', 'f'), null);
  const actions = formActions(forms(OWNER_FORM, 'http://app.test/')[0], 's', 'f');
  assert.deepEqual(actions.map((a) => a.action), ['fill', 'fill', 'check', 'select_option', 'fill', 'click', 'wait_for_timeout']);
});

test('seeds must be literal paths without variables or destructive words', () => {
  assert.deepEqual(validSeeds(['/vets', '/owners/{id}', 'http://x/y', '/owners/1/delete', '/logout', '/oups']), ['/vets', '/oups']);
});

function fakeSite(pages) {
  const calls = [];
  const run = async (scenario, origins) => {
    calls.push({ scenario, origins });
    const urls = [scenario.start_url.url, ...scenario.actions.filter((a) => a.action === 'goto').map((a) => a.destination.url)];
    const steps = [{ step_index: 0, step_id: 'scenario_start', status: 'completed', url: urls[0], dom: null }];
    scenario.actions.forEach((a, i) => {
      const url = a.action === 'goto' ? a.destination.url : (a.action === 'click' ? urls[0].replace(/\/new$/, '/7') : steps[steps.length - 1].url);
      steps.push({ step_index: i + 1, step_id: a.step_id, status: 'completed', url, dom: pages[new URL(url).pathname] ?? '<html></html>' });
    });
    const transactions = urls.map((u, i) => ({ transaction_id: `r${i}`, method: 'GET', url: u, status: pages[new URL(u).pathname] === undefined ? 404 : 200, step_index: i }));
    if (scenario.actions.some((a) => a.action === 'click')) transactions.push({ transaction_id: 'post', method: 'POST', url: urls[0], status: 302, step_index: 5 });
    return { evidence_id: `ev_${calls.length}`, steps, transactions };
  };
  return { run, calls };
}

test('exploration follows links once per route shape, submits each form once and skips destructive links', async () => {
  const site = fakeSite({
    '/': '<a href="/owners/find">f</a><a href="/owners/1">o1</a><a href="/owners/2">o2</a><a href="/owners/1/delete">x</a>',
    '/owners/find': '<form action="/owners" method="get"><input name="lastName"><button>Find</button></form>',
    '/owners/1': '<a href="/owners/new">new</a>',
    '/owners/new': '<form id="o" method="post"><input name="firstName"><button type="submit">Add</button></form>',
  });
  const result = await explore({ baseUrl: 'http://app.test', seeds: ['/vets'] }, site.run);
  assert.deepEqual(result.pages.map((p) => p.shape).sort(), ['/', '/owners/find', '/owners/new', '/owners/{id}', '/vets'].sort());
  assert.equal(result.pages.find((p) => p.shape === '/vets').status, 404);
  assert.deepEqual(result.skipped.map((s) => s.reason), ['DESTRUCTIVE_LOOKING_LINK']);
  assert.deepEqual(result.forms.map((f) => `${f.method} ${f.shape}`).sort(), ['GET /owners', 'POST /owners/new']);
  assert.ok(site.calls.every((c) => c.origins.length === 1 && c.origins[0] === 'http://app.test'));
  assert.ok(result.routes.some((r) => r.method === 'POST' && r.statuses.includes(302)));
});

test('exploration stops at the page limit and reports what it did not visit', async () => {
  const many = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`/p${i}`, '']));
  many['/'] = Object.keys(many).map((p) => `<a href="${p}">x</a>`).join('');
  const result = await explore({ baseUrl: 'http://app.test', maxPages: 5, includeForms: false }, fakeSite(many).run);
  assert.equal(result.pages.length, 5);
  assert.ok(result.unvisited.length > 0);
});

test('comparison calls the same scenario on both origins and reports request and text differences', async () => {
  const run = async (scenario) => {
    const origin = new URL(scenario.start_url.url).origin;
    const candidate = origin.endsWith(':2');
    return { evidence_id: 'e', steps: [{ step_index: 0, status: 'completed', url: scenario.start_url.url, dom: candidate ? '<p>Vets list Helen</p>' : '<p>Vets list James</p>' }],
      transactions: [{ method: 'GET', url: scenario.start_url.url, status: candidate ? 404 : 200 }] };
  };
  const out = await compareRuns({ baseline: 'http://h:1', candidate: 'http://h:2', scenarios: [{ name: 'vets', scenario: { start_url: { url: 'http://h:1/vets' }, actions: [] } }] }, run);
  assert.equal(out.results[0].status, 'DIFFERENT');
  assert.match(out.results[0].differences.join(' '), /Requests differ/);
  assert.equal(out.counts.DIFFERENT, 1);
  const same = await compareRuns({ baseline: 'http://h:1', candidate: 'http://h:3', scenarios: [{ name: 'v', scenario: { start_url: { url: 'http://h:1/vets' }, actions: [] } }] }, run);
  assert.equal(same.results[0].status, 'EQUIVALENT');
});

test('visible text and similarity ignore markup, scripts and session ids', () => {
  assert.equal(visibleText('<script>x()</script><p>Owner&nbsp;<b>Davis</b></p><a href="/o;jsessionid=AB">l</a>'), 'Owner Davis l');
  assert.equal(similarity('a list of vets', 'a list of vets'), 1);
  assert.ok(similarity('vets list james carter', 'owners page') < 0.2);
});

test('scenarios are pinned to the runner browser and may not leave the allowed origins', () => {
  const s = prepare({ browser: { mode: 'launch', executable_path: '/tmp/evil' }, start_url: { url: 'http://127.0.0.1:18080/' }, actions: [] }, ['http://127.0.0.1:18080']);
  assert.equal(s.browser.executable_path, process.execPath);
  assert.throws(() => prepare({ start_url: { url: 'https://example.com/' }, actions: [] }, ['http://127.0.0.1:18080']), /ORIGIN_NOT_ALLOWED/);
  assert.throws(() => prepare({ start_url: { url: 'http://127.0.0.1:18080/' }, actions: [{ action: 'goto', destination: { url: 'https://example.com' } }] }, ['http://127.0.0.1:18080']), /ORIGIN_NOT_ALLOWED/);
});

test('REA Evidence is reduced to steps, page transactions and DOM text', () => {
  const out = summarize({ evidence_id: 'ev1', parameters: { scenario_sha256: 'h' }, normalized_result: { duration_ms: 5, completeness: { status: 'complete' },
    steps: [{ step_index: 0, step_id: 'scenario_start', action: 'goto_start', status: 'completed', after_url: { url: 'http://a/' }, artifacts: { dom: { state: 'captured', value: { text: '<p>x</p>' } } } }],
    events: { dropped: 0, items: [
      { kind: 'request', transaction_id: 't1', method: 'GET', resource_type: 'document', url: { url: 'http://a/' }, step_index: 0 },
      { kind: 'response', transaction_id: 't1', method: 'GET', resource_type: 'document', url: { url: 'http://a/' }, status: 200, step_index: 0 },
      { kind: 'response', transaction_id: 't2', method: 'GET', resource_type: 'image', url: { url: 'http://a/i.png' }, status: 200 }] } } });
  assert.deepEqual(out.transactions, [{ transaction_id: 't1', method: 'GET', url: 'http://a/', resource_type: 'document', step_index: 0, status: 200, failure: null }]);
  assert.equal(out.steps[0].dom, '<p>x</p>');
});

test('OpenTelemetry settings accept one bearer header and an http(s) endpoint only', () => {
  const env = otelEnvironment({ endpoint: 'http://127.0.0.1:8000/api/v1/runtime-sessions/x/v1/traces', headers: 'Authorization=Bearer abc', service_name: 's' });
  assert.equal(env.OTEL_EXPORTER_OTLP_TRACES_HEADERS, 'Authorization=Bearer abc');
  assert.throws(() => otelEnvironment({ endpoint: 'file:///etc/passwd' }), /OTEL_ENDPOINT_INVALID/);
  assert.throws(() => otelEnvironment({ endpoint: 'http://x', headers: 'A=b\nC=d' }), /OTEL_HEADERS_INVALID/);
});

test('artifacts must match their hash and be ZIP based', async () => {
  const bytes = Buffer.from('PK\u0003\u0004 fake jar');
  const { createHash } = await import('node:crypto');
  const sha = createHash('sha256').update(bytes).digest('hex');
  await assert.rejects(storeArtifact('0'.repeat(64), bytes), /ARTIFACT_HASH_MISMATCH/);
  await assert.rejects(storeArtifact(createHash('sha256').update('x').digest('hex'), Buffer.from('x')), /ARTIFACT_NOT_A_JAR/);
  assert.deepEqual(await storeArtifact(sha, bytes), { sha256: sha, bytes: bytes.length });
});

test('generated files stay inside the service folder and cannot replace the build recipe', () => {
  assert.equal(safePath('src/main/java/A.java'), 'src/main/java/A.java');
  for (const bad of ['../x', '/etc/passwd', 'a/../../b', 'Dockerfile', 'sub/dockerfile', '.dockerignore', '.mvn/wrapper/x', '.git/config', 'a\\b'])
    assert.throws(() => safePath(bad), /FILE_PATH/);
  assert.match(DOCKERFILE, /USER 10001/);
});

test('every endpoint requires the bearer token and unknown routes are 404', async () => {
  const call = async (method, path, token) => {
    const { Readable } = await import('node:stream');
    const req = Readable.from([]);
    Object.assign(req, { method, url: path, headers: token ? { authorization: `Bearer ${token}` } : {} });
    let status; let payload;
    const res = { writeHead: (s) => { status = s; }, end: (t) => { payload = JSON.parse(t); } };
    await handle(req, res);
    return { status, payload };
  };
  assert.equal((await call('GET', '/v1/health')).status, 401);
  assert.equal((await call('GET', '/v1/health', 'wrong-token-0123456789abcdefgh')).status, 401);
  assert.equal((await call('GET', '/v1/nothing', process.env.RUNNER_TOKEN)).status, 404);
  assert.equal((await call('POST', '/v1/scenarios', process.env.RUNNER_TOKEN)).status, 400);       // no start URL
});
