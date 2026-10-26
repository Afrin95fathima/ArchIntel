import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, symlinkSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

process.env.RUNNER_TOKEN = 'test-token-0123456789abcdefghij';
process.env.RUNNER_WORK_DIR = mkdtempSync(`${tmpdir()}/runner-recipe-test-`);
const { validateRecipe, interpolate, storeDistribution, distributionDir, generateSecrets } = await import('../src/recipes.mjs');
const { parseTemplate, Values, expand, exploreApi, validateScenario } = await import('../src/api_explore.mjs');

const RECIPE = {
  name: 'demo-server', main_class: 'com.example.Main', classpath: ['lib/*', 'classes'], jvm_args: ['-Xmx512m', '--add-opens', 'java.base/java.lang=ALL-UNNAMED'],
  system_properties: { 'app.conf': '${FILE:app.conf}' }, generated_secrets: [{ name: 'TOKEN', kind: 'base64' }],
  dependencies: [{ name: 'db', image: 'postgres:14.21-alpine', port: 5432, env: { POSTGRES_PASSWORD: '${TOKEN}' }, ready_log: 'ready', ready_log_count: 2 }],
  config_files: [{ name: 'app.conf', content: 'port=${PORT} db=${DB_PORT}' }], ready: { path: '/health' }, credential: { header: 'Authorization', value: 'Bearer ${TOKEN}' },
};

test('a valid recipe is normalised; anything that changes what runs is rejected', () => {
  const recipe = validateRecipe(RECIPE);
  assert.equal(recipe.ready.path, '/health');
  assert.equal(recipe.dependencies[0].ready_log_count, 2);
  const reject = (change, code) => assert.throws(() => validateRecipe({ ...RECIPE, ...change }), (e) => e.code === code);
  reject({ jvm_args: ['-javaagent:/tmp/evil.jar'] }, 'RECIPE_JVM_ARGS_INVALID');
  reject({ jvm_args: ['-cp'] }, 'RECIPE_JVM_ARGS_INVALID');
  reject({ jvm_args: ['-XX:OnError=sh'] }, 'RECIPE_JVM_ARGS_INVALID');
  reject({ classpath: ['../outside/*'] }, 'RECIPE_CLASSPATH_INVALID');
  reject({ classpath: ['/etc'] }, 'RECIPE_CLASSPATH_INVALID');
  reject({ main_class: 'sh -c id' }, 'RECIPE_MAIN_CLASS_INVALID');
  reject({ dependencies: [{ ...RECIPE.dependencies[0], image: 'attacker/miner:latest' }] }, 'RECIPE_IMAGE_NOT_ALLOWED');
  reject({ credential: { header: 'Bad Header', value: 'x' } }, 'RECIPE_CREDENTIAL_INVALID');
});

test('placeholders resolve from generated secrets, ports and config files; unknown ones are errors', () => {
  const secrets = generateSecrets([{ name: 'TOKEN', kind: 'base64' }, { name: 'PW', kind: 'password' }]);
  assert.match(secrets.TOKEN, /^[A-Za-z0-9+/]+=*$/);
  assert.notEqual(generateSecrets([{ name: 'TOKEN', kind: 'base64' }]).TOKEN, secrets.TOKEN);
  assert.equal(interpolate('port=${PORT} file=${FILE:app.conf}', { PORT: 18080 }, { 'app.conf': '/run/app.conf' }), 'port=18080 file=/run/app.conf');
  assert.throws(() => interpolate('${MISSING}', {}), (e) => e.code === 'RECIPE_PLACEHOLDER_UNKNOWN');
  assert.equal(interpolate('${?HOCON_ENV} ${lower}', {}), '${?HOCON_ENV} ${lower}');   // configuration-language syntax is left alone
});

function tarball(build) {
  const dir = mkdtempSync(`${tmpdir()}/dist-src-`);
  build(dir);
  const out = join(mkdtempSync(`${tmpdir()}/dist-out-`), 'dist.tar.gz');
  execFileSync('tar', ['-czf', out, '-C', dir, '.']);
  const bytes = readFileSync(out);
  return { bytes, sha: createHash('sha256').update(bytes).digest('hex') };
}

test('distributions are unpacked once; links and hash mismatches are refused', async () => {
  const good = tarball((d) => { mkdirSync(join(d, 'lib')); writeFileSync(join(d, 'lib', 'a.jar'), 'PK'); writeFileSync(join(d, 'start.sh'), '#!/bin/sh'); });
  const stored = await storeDistribution(good.sha, good.bytes);
  assert.equal(stored.reused, false);
  assert.ok(existsSync(join(distributionDir(good.sha), 'lib', 'a.jar')));
  assert.equal((await storeDistribution(good.sha, good.bytes)).reused, true);
  await assert.rejects(storeDistribution(good.sha.replace(/^./, good.sha[0] === 'a' ? 'b' : 'a'), good.bytes), (e) => e.code === 'DISTRIBUTION_HASH_MISMATCH');
  const linked = tarball((d) => { symlinkSync('/etc/passwd', join(d, 'passwd')); });
  await assert.rejects(storeDistribution(linked.sha, linked.bytes), (e) => e.code === 'DISTRIBUTION_ENTRY_TYPE');
  const plain = Buffer.from('PK not gzip');
  await assert.rejects(storeDistribution(createHash('sha256').update(plain).digest('hex'), plain), (e) => e.code === 'DISTRIBUTION_NOT_TAR_GZ');
  assert.throws(() => distributionDir('f'.repeat(64)), (e) => e.code === 'DISTRIBUTION_NOT_UPLOADED');
});

test('path templates lose regex constraints and variables fill from the matching resource, newest first', () => {
  assert.deepEqual(parseTemplate('/api/v1/org/{orgName}/jsonstore/{storeName}/item/{itemPath:.*}'), {
    template: '/api/v1/org/{orgName}/jsonstore/{storeName}/item/{itemPath}', variables: ['orgName', 'storeName', 'itemPath'] });
  const values = new Values();
  values.learn('/api/v1/org', [{ id: 'o1', name: 'Default' }]);
  values.learn('/api/v1/org', [{ id: 'o1', name: 'Default' }, { id: 'o2', name: 'created-by-scenario' }]);
  values.learn('/api/v1/org/created-by-scenario/secret', [{ id: 's1', name: 'secret-1', orgName: 'created-by-scenario' }]);
  values.learn('/api/v2/process', [{ instanceId: 'p-1', statusHistory: [{ id: 'history-entry' }] }]);
  assert.deepEqual(values.candidates('orgName', 'org'), ['created-by-scenario', 'Default']);
  assert.deepEqual(values.candidates('secretName', 'secret'), ['secret-1']);
  assert.deepEqual(values.candidates('id', 'process'), ['p-1']);                   // nested history ids are not the process id
  assert.deepEqual(expand('/api/v1/org/{orgName}/secret/{secretName}', ['orgName', 'secretName'], values, 1).paths, ['/api/v1/org/created-by-scenario/secret/secret-1']);
  assert.deepEqual(expand('/api/v1/card/{cardId}', ['cardId'], values).missing, ['cardId']);
});

test('API exploration crawls GET routes, runs scenarios with extracted values, skips listed routes and never leaves the origin', async () => {
  const seen = [];
  const data = { orgs: [{ id: 'o1', name: 'Default' }] };
  const fetcher = async (url, init) => {
    const u = new URL(url);
    seen.push({ method: init.method, path: u.pathname + u.search, auth: init.headers.authorization, body: init.body });
    const reply = (status, body) => ({ status, headers: new Headers({ 'content-type': 'application/json' }), text: async () => JSON.stringify(body) });
    if (init.method === 'POST' && u.pathname === '/api/org') { const name = JSON.parse(init.body).name; data.orgs.push({ id: 'o2', name }); return reply(200, { id: 'o2', ok: true }); }
    if (u.pathname === '/api/org') return reply(200, data.orgs);
    if (/^\/api\/org\/[^/]+$/.test(u.pathname)) return reply(200, { name: decodeURIComponent(u.pathname.split('/').pop()) });
    if (u.pathname === '/api/org/o2-id') return reply(404, {});
    if (init.method === 'DELETE') return reply(200, {});
    return reply(404, {});
  };
  const scenario = { name: 'demo', steps: [{ id: 'create', method: 'POST', path: '/api/org', json: { name: 'org-${RUN_ID}' }, extract: { ORG_ID: 'id' } }],
    cleanup: [{ id: 'delete', method: 'DELETE', path: '/api/org/${ORG_ID}' }] };
  const result = await exploreApi({ baseUrl: 'http://app.test:9000', credential: { header: 'Authorization', value: 'Bearer secret' },
    endpoints: [{ method: 'GET', path: '/api/org' }, { method: 'GET', path: '/api/org/{orgName}' }, { method: 'GET', path: '/api/org/{orgName}/wait' }, { method: 'POST', path: '/api/org' }, { method: 'GET', path: '/api/card/{cardId}' }],
    scenarios: [scenario], skipPaths: ['/wait$'] }, fetcher);
  assert.ok(seen.every((r) => r.auth === 'Bearer secret'));
  assert.equal(result.summary.get_routes, 3);                                    // POST routes are never crawled; the skipped route is not counted
  assert.deepEqual(result.skipped, ['/api/org/{orgName}/wait']);
  assert.equal(result.summary.scenario_steps_passed, 1);
  assert.equal(result.scenarios[0].cleanup[0].path, '/api/org/o2');               // value extracted from the create response
  const crawled = seen.filter((r) => r.method === 'GET').map((r) => r.path);
  assert.ok(crawled.some((p) => /^\/api\/org\/org-[0-9a-f]{8}$/.test(p)), 'the scenario-created org is read back by the second crawl');
  assert.deepEqual(result.unresolved, [{ template: '/api/card/{cardId}', missing: ['cardId'] }]);
  assert.ok(!JSON.stringify(result).includes('Bearer secret'), 'the credential is never returned');
  await assert.rejects(exploreApi({ baseUrl: 'http://app.test:9000', scenarios: [{ name: 'out', steps: [{ method: 'GET', path: '//evil.test/x' }] }] }, fetcher),
    (e) => e.code === 'SCENARIO_STEP_INVALID');
});

test('scenario files are validated before anything is sent', () => {
  assert.throws(() => validateScenario({ name: 'x', steps: [{ method: 'TRACE', path: '/a' }] }), (e) => e.code === 'SCENARIO_STEP_INVALID');
  assert.throws(() => validateScenario({ name: 'x', steps: [{ method: 'GET', path: 'http://elsewhere/a' }] }), (e) => e.code === 'SCENARIO_STEP_INVALID');
  assert.throws(() => validateScenario({ name: 'x', steps: [{ method: 'POST', path: '/a', json: {}, multipart: {} }] }), (e) => e.code === 'SCENARIO_STEP_INVALID');
  assert.equal(validateScenario({ name: 'x', steps: [{ method: 'GET', path: '/a' }] }).steps[0].id, 'step-1');
});

test('companion processes need their own distribution and the same JVM rules; extra ports are named variables', async () => {
  const companion = { name: 'agent', distribution: 'agent', main_class: 'com.example.agent.Main', classpath: ['lib/*'], jvm_args: ['-Xmx256m'], ready_log: 'started' };
  const recipe = validateRecipe({ ...RECIPE, ports: ['AGENT_PORT'], companions: [companion] });
  assert.equal(recipe.companions[0].ready_timeout_ms, 120000);
  assert.deepEqual(recipe.ports, ['AGENT_PORT']);
  const reject = (change, code) => assert.throws(() => validateRecipe({ ...RECIPE, ...change }), (e) => e.code === code);
  reject({ companions: [{ ...companion, jvm_args: ['-javaagent:/tmp/x.jar'] }] }, 'RECIPE_JVM_ARGS_INVALID');
  reject({ companions: [{ ...companion, classpath: ['../../etc'] }] }, 'RECIPE_CLASSPATH_INVALID');
  reject({ companions: [{ ...companion, distribution: 'Not Valid' }] }, 'RECIPE_COMPANION_INVALID');
  reject({ companions: [companion, companion] }, 'RECIPE_COMPANION_INVALID');
  reject({ ports: ['PORT'] }, 'RECIPE_PORTS_INVALID');
  const { startRecipe, redact } = await import('../src/apps.mjs');
  await assert.rejects(startRecipe({ distribution_sha256: 'a'.repeat(64), recipe: { ...RECIPE, companions: [companion] } }),
    (e) => ['DISTRIBUTION_NOT_UPLOADED', 'COMPANION_DISTRIBUTION_MISSING'].includes(e.code));
  assert.equal(redact('API token created: c2VjcmV0LXRva2VuLXZhbHVl and again c2VjcmV0LXRva2VuLXZhbHVl', ['c2VjcmV0LXRva2VuLXZhbHVl']),
    'API token created: [generated secret] and again [generated secret]');
});

test('a polling step repeats its GET until a final value and passes only on a success value', async () => {
  let calls = 0;
  const fetcher = async () => {
    calls += 1;
    const status = calls < 3 ? 'RUNNING' : 'FAILED';
    return { status: 200, headers: new Headers({ 'content-type': 'application/json' }), text: async () => JSON.stringify({ status }) };
  };
  const scenario = { name: 'wait', steps: [{ id: 'wait', method: 'GET', path: '/p/1', until: { path: 'status', in: ['FINISHED', 'FAILED'], success: ['FINISHED'], interval_ms: 500, timeout_ms: 10000 } }] };
  const result = await exploreApi({ baseUrl: 'http://app.test', scenarios: [scenario] }, fetcher);
  assert.equal(calls, 3);
  assert.deepEqual([result.scenarios[0].steps[0].state, result.scenarios[0].steps[0].reached], ['FAILED', 'FAILED']);
  assert.throws(() => validateScenario({ name: 'x', steps: [{ method: 'POST', path: '/a', until: { path: 's', in: ['A'] } }] }), (e) => e.code === 'SCENARIO_STEP_INVALID');
});

test('steps with a missing extracted value are skipped, and polling stops on an error response', async () => {
  const seen = [];
  const fetcher = async (url) => {
    seen.push(new URL(url).pathname);
    return { status: 404, headers: new Headers({ 'content-type': 'application/json' }), text: async () => '{}' };
  };
  const scenario = { name: 's', steps: [
    { id: 'start', method: 'POST', path: '/start', json: {}, extract: { ID: 'instanceId' } },
    { id: 'wait', method: 'GET', path: '/p/${ID}', until: { path: 'status', in: ['DONE'], interval_ms: 500, timeout_ms: 60000 } },
    { id: 'poll-missing', method: 'GET', path: '/known', until: { path: 'status', in: ['DONE'], interval_ms: 500, timeout_ms: 60000 } }] };
  const started = Date.now();
  const result = await exploreApi({ baseUrl: 'http://app.test', scenarios: [scenario] }, fetcher);
  const [, wait, known] = result.scenarios[0].steps;
  assert.deepEqual([wait.state, wait.error], ['SKIPPED_MISSING_VALUE', 'no value for ID']);
  assert.equal(known.state, 'FAILED');
  assert.deepEqual(seen, ['/start', '/known']);                                  // nothing sent for /p/${ID}, one call for /known
  assert.ok(Date.now() - started < 5000);
});

test('fixture repositories are served read-only over HTTP, and their URLs and named secrets reach the scenarios', async () => {
  const { createRepositories } = await import('../src/recipes.mjs');
  const { allowed } = await import('../src/git_http.mjs');
  const recipe = validateRecipe({ ...RECIPE, generated_secrets: [...RECIPE.generated_secrets, { name: 'USER_PW', kind: 'password' }], scenario_variables: ['USER_PW'],
    git_repositories: [{ name: 'demo', files: { 'concord.yml': 'flows: {}\n' } }] });
  assert.deepEqual(recipe.scenario_variables, ['USER_PW']);
  assert.throws(() => validateRecipe({ ...RECIPE, scenario_variables: ['NOT_GENERATED'] }), (e) => e.code === 'RECIPE_SCENARIO_VARIABLES_INVALID');
  assert.throws(() => validateRecipe({ ...RECIPE, git_repositories: [{ name: 'demo', files: { '../escape': 'x' } }] }), (e) => e.code === 'RECIPE_GIT_INVALID');
  assert.throws(() => validateRecipe({ ...RECIPE, git_repositories: [{ name: 'demo', files: { '.git/config': 'x' } }] }), (e) => e.code === 'RECIPE_GIT_INVALID');
  const dir = mkdtempSync(`${tmpdir()}/repo-test-`);
  const { urls, server } = await createRepositories(dir, recipe.git_repositories, 15468);
  try {
    assert.deepEqual(urls, { GIT_DEMO_URL: 'http://127.0.0.1:15468/demo.git' });
    const refs = await fetch(urls.GIT_DEMO_URL + '/info/refs?service=git-upload-pack');
    assert.equal(refs.status, 200);
    assert.match(await refs.text(), /refs\/heads\/main/);
    assert.equal((await fetch(urls.GIT_DEMO_URL + '/info/refs?service=git-receive-pack')).status, 403);
    assert.equal((await fetch('http://127.0.0.1:15468/demo.git/config')).status, 403);
  } finally { await server.close(); }
  assert.equal(allowed('POST', '/demo.git/git-receive-pack', ''), false);
  assert.equal(allowed('GET', '/../etc/passwd', ''), false);
});

test('dependency seeding is an argument list with stdin, and a step can log in with basic auth instead of the run credential', async () => {
  const recipe = validateRecipe({ ...RECIPE, dependencies: [{ ...RECIPE.dependencies[0], init: { command: ['psql', '-c', 'select 1'], stdin: '-- ${TOKEN}' } }] });
  assert.deepEqual(recipe.dependencies[0].init.command, ['psql', '-c', 'select 1']);
  assert.throws(() => validateRecipe({ ...RECIPE, dependencies: [{ ...RECIPE.dependencies[0], init: { command: [] } }] }), (e) => e.code === 'RECIPE_DEPENDENCY_INVALID');
  const headers = [];
  const fetcher = async (url, init) => { headers.push(init.headers.authorization); return { status: 200, headers: new Headers(), text: async () => '' }; };
  await exploreApi({ baseUrl: 'http://app.test', credential: { header: 'Authorization', value: 'Bearer run-token' }, variables: { PW: 'ldap-pw' },
    scenarios: [{ name: 's', steps: [{ method: 'GET', path: '/whoami', basic_auth: { username: 'user', password: '${PW}' } }, { method: 'GET', path: '/next' }] }] }, fetcher);
  assert.deepEqual(headers, ['Basic ' + Buffer.from('user:ldap-pw').toString('base64'), 'Bearer run-token']);
});
