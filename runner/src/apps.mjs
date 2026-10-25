// Start and stop target applications on runner-owned ports, with the OpenTelemetry Java agent when a session is given.
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createWriteStream, existsSync } from 'node:fs';
import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { join } from 'node:path';
import { config } from './config.mjs';
import { createRepositories, distributionDir, freePort, generateSecrets, interpolate, startDependencies, stopDependencies, validateRecipe } from './recipes.mjs';

export class AppError extends Error {
  constructor(code, detail) { super(code); this.code = code; this.detail = detail; }
}

const runs = new Map();
const SHA = /^[0-9a-f]{64}$/;
const PROFILE = /^[A-Za-z0-9_-]{1,40}$/;

export async function storeArtifact(sha256, bytes) {
  if (!SHA.test(sha256)) throw new AppError('ARTIFACT_ID_INVALID');
  if (bytes.length === 0 || bytes.length > config.maxArtifactBytes) throw new AppError('ARTIFACT_SIZE');
  if (createHash('sha256').update(bytes).digest('hex') !== sha256) throw new AppError('ARTIFACT_HASH_MISMATCH');
  if (bytes[0] !== 0x50 || bytes[1] !== 0x4b) throw new AppError('ARTIFACT_NOT_A_JAR');   // JAR/WAR are ZIP files
  const dir = join(config.workDir, 'artifacts');
  await mkdir(dir, { recursive: true });
  const target = join(dir, `${sha256}.jar`);
  const temp = `${target}.${randomUUID()}.tmp`;
  await writeFile(temp, bytes);
  await rename(temp, target);
  return { sha256, bytes: bytes.length };
}

function free(port) {
  return new Promise((resolve) => {
    const s = createServer().once('error', () => resolve(false)).once('listening', () => s.close(() => resolve(true)));
    s.listen(port, '127.0.0.1');
  });
}

async function pickPort() {
  const used = new Set([...runs.values()].map((r) => r.port));
  for (let p = config.appPorts[0]; p <= config.appPorts[1]; p += 1) {
    if (!used.has(p) && await free(p)) return p;
  }
  throw new AppError('NO_FREE_PORT');
}

const HEADER = /^[A-Za-z0-9-]{1,64}=[^\r\n,]{1,512}$/;

/** Environment for the OpenTelemetry agent. Only an http(s) endpoint and one bearer header are accepted. */
export function otelEnvironment(otel) {
  if (!otel) return {};
  const endpoint = new URL(otel.endpoint);
  if (!['http:', 'https:'].includes(endpoint.protocol)) throw new AppError('OTEL_ENDPOINT_INVALID');
  if (otel.headers && !HEADER.test(otel.headers)) throw new AppError('OTEL_HEADERS_INVALID');
  const env = {
    OTEL_SERVICE_NAME: String(otel.service_name || 'archintel-target').slice(0, 120),
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: endpoint.toString(),
    OTEL_EXPORTER_OTLP_PROTOCOL: 'http/protobuf',
    OTEL_METRICS_EXPORTER: 'none',
    OTEL_LOGS_EXPORTER: 'none',
    OTEL_TRACES_SAMPLER: 'parentbased_always_on',
  };
  if (otel.headers) env.OTEL_EXPORTER_OTLP_TRACES_HEADERS = otel.headers;
  if (otel.resource_attributes) env.OTEL_RESOURCE_ATTRIBUTES = String(otel.resource_attributes).slice(0, 2000);
  if (otel.methods_include) env.OTEL_INSTRUMENTATION_METHODS_INCLUDE = String(otel.methods_include).slice(0, 65536);
  return env;
}

async function waitReady(run, timeoutMs, path = '/') {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (run.exit !== null) throw new AppError('APP_EXITED', `exit ${run.exit}`);
    try {
      const response = await fetch(run.base_url + path, { redirect: 'manual', signal: AbortSignal.timeout(3000) });
      if (response.status < 500) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new AppError('APP_START_TIMEOUT');
}

export async function start({ artifact_sha256, otel = null, profile = null, ready_timeout_ms = 180000 }) {
  if (!SHA.test(artifact_sha256 || '')) throw new AppError('ARTIFACT_ID_INVALID');
  const jar = join(config.workDir, 'artifacts', `${artifact_sha256}.jar`);
  if (!existsSync(jar)) throw new AppError('ARTIFACT_NOT_UPLOADED');
  if (!config.javaPath) throw new AppError('JAVA_UNAVAILABLE');
  if (otel && !config.otelAgentJar) throw new AppError('OTEL_AGENT_UNAVAILABLE');
  if (profile !== null && !PROFILE.test(profile)) throw new AppError('PROFILE_INVALID');
  const port = await pickPort();
  const id = randomUUID();
  const dir = join(config.workDir, 'runs', id);
  await mkdir(dir, { recursive: true });
  const args = [...(otel ? [`-javaagent:${config.otelAgentJar}`] : []), '-jar', jar, `--server.port=${port}`, '--server.address=127.0.0.1',
    ...(profile ? [`--spring.profiles.active=${profile}`] : [])];
  const log = createWriteStream(join(dir, 'app.log'), { mode: 0o600 });
  const child = spawn(config.javaPath, args, { cwd: dir, env: { PATH: process.env.PATH, HOME: process.env.HOME, ...otelEnvironment(otel) }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log);
  const run = { id, port, base_url: `http://127.0.0.1:${port}`, artifact_sha256, otel: !!otel, started_at: new Date().toISOString(), exit: null, child, dir };
  child.on('exit', (code, signal) => { run.exit = code ?? signal; });
  runs.set(id, run);
  try { await waitReady(run, ready_timeout_ms); } catch (error) { await stop(id); throw error; }
  return view(run);
}

/** Spawn one JVM of a recipe (the main process or a companion) with its classpath resolved inside its distribution. */
function spawnJava(spec, home, variables, files, otel, dir, logName) {
  const properties = Object.entries(spec.system_properties).map(([k, v]) => `-D${k}=${interpolate(v, variables, files)}`);
  const classpath = spec.classpath.map((entry) => join(home, entry)).join(':');
  const args = [...spec.jvm_args.map((a) => interpolate(a, variables, files)), ...(otel ? [`-javaagent:${config.otelAgentJar}`] : []), ...properties,
    '-cp', classpath, spec.main_class, ...spec.args.map((a) => interpolate(a, variables, files))];
  const env = Object.fromEntries(Object.entries(spec.env).map(([k, v]) => [k, interpolate(v, variables, files)]));
  const log = createWriteStream(join(dir, logName), { mode: 0o600 });
  const child = spawn(config.javaPath, args, { cwd: dir, env: { PATH: process.env.PATH, HOME: process.env.HOME, ...env, ...otelEnvironment(otel) }, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log); child.stderr.pipe(log);
  return child;
}

async function waitForLog(file, pattern, process, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (process.exit !== null) throw new AppError('COMPANION_EXITED', `${process.name}: exit ${process.exit}`);
    const text = await readFile(file, 'utf8').catch(() => '');
    if (!pattern || text.includes(pattern)) return;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new AppError('COMPANION_NOT_READY', process.name);
}

/**
 * Start a distribution with a launch recipe: dependency containers first, then `java -cp <distribution classpath> <main class>`
 * with the OpenTelemetry agent, then any companion processes from their own distributions. Generated secrets and the
 * credential stay in this process; the view only says one exists. `${OTEL_JVM_ARG}` lets a process hand the agent to the
 * JVMs it starts itself (for example a worker that runs each job in a new JVM).
 */
export async function startRecipe({ distribution_sha256, distributions = {}, recipe: input, otel = null }) {
  const recipe = validateRecipe(input);
  const home = distributionDir(distribution_sha256);
  const homes = Object.fromEntries(recipe.companions.map((c) => {
    if (!distributions[c.distribution]) throw new AppError('COMPANION_DISTRIBUTION_MISSING', c.distribution);
    return [c.distribution, distributionDir(distributions[c.distribution])];
  }));
  if (!config.javaPath) throw new AppError('JAVA_UNAVAILABLE');
  if (otel && !config.otelAgentJar) throw new AppError('OTEL_AGENT_UNAVAILABLE');
  const port = await pickPort();
  const id = randomUUID();
  const dir = join(config.workDir, 'runs', id);
  await mkdir(dir, { recursive: true, mode: 0o700 });
  const secrets = generateSecrets(recipe.generated_secrets);
  const variables = { PORT: port, HOST: '127.0.0.1', RUN_DIR: dir, DIST_DIR: home, OTEL_JVM_ARG: otel ? `-javaagent:${config.otelAgentJar}` : '-Darchintel.otel=off',
    ...Object.fromEntries(Object.entries(homes).map(([key, path]) => [`DIST_DIR_${key.toUpperCase().replaceAll('-', '_')}`, path])),
    ...secrets };
  const run = { id, port, base_url: `http://127.0.0.1:${port}`, artifact_sha256: distribution_sha256, recipe: recipe.name, otel: !!otel,
    started_at: new Date().toISOString(), exit: null, child: null, dir, dependencies: [], companions: [], credential: null, removeDir: !config.keepRunDirs };
  runs.set(id, run);
  try {
    const used = new Set([...runs.values()].flatMap((r) => [...(r.dependencies || []).map((d) => d.port), ...(r.ports || [])]));
    run.dependencies = await startDependencies(id, recipe.dependencies, variables, used);
    run.ports = [];
    for (const name of recipe.ports) {
      variables[name] = await freePort(config.dependencyPorts[0], config.dependencyPorts[1], new Set([...used, ...run.dependencies.map((d) => d.port), ...run.ports]));
      run.ports.push(variables[name]);
    }
    // Repository URLs are no secret: they also reach the scenarios as ${GIT_<NAME>_URL}.
    const gitPort = recipe.git_repositories.length ? await freePort(config.dependencyPorts[0], config.dependencyPorts[1], new Set([...used, ...run.dependencies.map((d) => d.port), ...run.ports])) : null;
    if (gitPort) run.ports.push(gitPort);
    const repositories = await createRepositories(dir, recipe.git_repositories, gitPort);
    run.gitServer = repositories.server;
    run.exposed = { ...repositories.urls, ...Object.fromEntries(recipe.scenario_variables.map((name) => [name, variables[name]])) };
    Object.assign(variables, run.exposed);
    const files = {};
    for (const file of recipe.config_files) files[file.name] = join(dir, file.name);
    for (const file of recipe.config_files) await writeFile(files[file.name], interpolate(file.content, variables, files), { mode: 0o600 });
    const child = spawnJava(recipe, home, variables, files, otel, dir, 'app.log');
    run.child = child;
    child.on('exit', (code, signal) => { run.exit = code ?? signal; });
    if (recipe.credential) run.credential = { header: recipe.credential.header, value: interpolate(recipe.credential.value, variables, files) };
    await waitReady(run, recipe.ready.timeout_ms, recipe.ready.path);
    for (const spec of recipe.companions) {
      const companion = { name: spec.name, exit: null, child: null, log: `${spec.name}.log` };
      run.companions.push(companion);
      companion.child = spawnJava(spec, homes[spec.distribution], variables, files, otel, dir, companion.log);
      companion.child.on('exit', (code, signal) => { companion.exit = code ?? signal; });
      await waitForLog(join(dir, companion.log), spec.ready_log, companion, spec.ready_timeout_ms);
    }
  } catch (error) {
    if (run.child) {
      const failed = run.companions.find((c) => c.exit !== null || error.code?.startsWith('COMPANION'));
      const tail = await readFile(join(dir, failed ? failed.log : 'app.log')).then((b) => b.subarray(Math.max(0, b.length - 3000)).toString('utf8'), () => '');
      // Applications may print generated credentials at start-up (Concord prints its admin and agent tokens): never pass them on.
      error.detail = redact(`${error.detail ? error.detail + '\n' : ''}${tail}`, Object.values(secrets));
    }
    await stop(id);
    throw error;
  }
  return view(run);
}

export function redact(text, values) {
  return values.filter((v) => v && v.length >= 8).reduce((out, value) => out.split(value).join('[generated secret]'), text);
}

async function terminate(process) {
  if (!process.child || process.exit !== null) return;
  process.child.kill('SIGTERM');                            // lets the OpenTelemetry agent flush its last spans
  const deadline = Date.now() + 15000;
  while (process.exit === null && Date.now() < deadline) await new Promise((r) => setTimeout(r, 200));
  if (process.exit === null) process.child.kill('SIGKILL');
}

export async function stop(id) {
  const run = runs.get(id);
  if (!run) throw new AppError('RUN_NOT_FOUND');
  for (const companion of [...(run.companions || [])].reverse()) await terminate(companion);
  await terminate(run);
  await stopDependencies(run.dependencies);
  if (run.gitServer) await run.gitServer.close();
  // A recipe run folder holds generated secrets in its config files and logs; it does not outlive the run.
  if (run.removeDir) await rm(run.dir, { recursive: true, force: true });
  runs.delete(id);
  return { id, stopped: true, exit: run.exit, companions: (run.companions || []).map((c) => ({ name: c.name, exit: c.exit })) };
}

export async function logTail(id, bytes = 8000) {
  const run = runs.get(id);
  if (!run) throw new AppError('RUN_NOT_FOUND');
  const file = join(run.dir, 'app.log');
  const size = (await stat(file)).size;
  const text = (await readFile(file)).subarray(Math.max(0, size - bytes)).toString('utf8');
  return { id, text };
}

export function view(run) {
  return { id: run.id, base_url: run.base_url, port: run.port, artifact_sha256: run.artifact_sha256, otel: run.otel, started_at: run.started_at, running: run.exit === null,
    recipe: run.recipe || null, dependencies: (run.dependencies || []).map((d) => ({ name: d.name, port: d.port })), credential: !!run.credential,
    companions: (run.companions || []).map((c) => ({ name: c.name, running: c.exit === null })) };
}
export function list() { return [...runs.values()].map(view); }
export function get(id) { const r = runs.get(id); if (!r) throw new AppError('RUN_NOT_FOUND'); return r; }
export async function stopAll() { for (const id of [...runs.keys()]) await stop(id).catch(() => {}); }
export async function clean() { await rm(join(config.workDir, 'runs'), { recursive: true, force: true }); }
