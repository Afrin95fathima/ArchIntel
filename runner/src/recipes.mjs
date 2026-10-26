// Launch recipes: run an application distributed as a .tar.gz (classpath + main class) next to disposable dependency
// containers, instead of `java -jar`. A recipe is data only: every value is validated and every command is built here.
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import { createConnection, createServer } from 'node:net';
import { join, normalize, sep } from 'node:path';
import { config } from './config.mjs';
import { serveRepositories } from './git_http.mjs';

export class RecipeError extends Error {
  constructor(code, detail) { super(code); this.code = code; this.detail = detail; }
}

const SHA = /^[0-9a-f]{64}$/;
const NAME = /^[a-z][a-z0-9-]{0,30}$/;
const VARIABLE = /^[A-Z][A-Z0-9_]{0,40}$/;
const CLASS = /^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)+$/;
const PROPERTY = /^[A-Za-z][\w.-]{0,120}$/;
const PLACEHOLDER = /\$\{([A-Z][A-Z0-9_]{0,40}|FILE:[a-z0-9][a-z0-9._-]{0,60})\}/g;
// JVM options that would change what runs or where telemetry goes are reserved for the runner.
const RESERVED_JVM = /^-(javaagent|agentlib|agentpath|cp$|classpath|jar$|Dotel\.|XX:OnError|XX:OnOutOfMemoryError)/i;

function run(command, args, timeoutMs) {
  return new Promise((resolve) => {
    execFile(command, args, { timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024 }, (error, stdout, stderr) =>
      resolve({ code: error ? (typeof error.code === 'number' ? error.code : 1) : 0, stdout, stderr }));
  });
}

/** Store and unpack a distribution. Absolute paths, `..`, links and devices are rejected before anything is extracted. */
export async function storeDistribution(sha256, bytes) {
  if (!SHA.test(sha256)) throw new RecipeError('DISTRIBUTION_ID_INVALID');
  if (!bytes.length || bytes.length > config.maxDistributionBytes) throw new RecipeError('DISTRIBUTION_SIZE');
  if (createHash('sha256').update(bytes).digest('hex') !== sha256) throw new RecipeError('DISTRIBUTION_HASH_MISMATCH');
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) throw new RecipeError('DISTRIBUTION_NOT_TAR_GZ');
  const base = join(config.workDir, 'distributions');
  const target = join(base, sha256);
  if (existsSync(join(target, '.complete'))) return { sha256, bytes: bytes.length, reused: true };
  await mkdir(base, { recursive: true });
  const archive = join(base, `${sha256}.${randomUUID()}.tar.gz`);
  await writeFile(archive, bytes);
  try {
    const listing = await run('tar', ['-tvzf', archive], 120000);
    if (listing.code !== 0) throw new RecipeError('DISTRIBUTION_UNREADABLE', listing.stderr.slice(0, 500));
    const lines = listing.stdout.split('\n').filter(Boolean);
    if (lines.length > 20000) throw new RecipeError('DISTRIBUTION_TOO_MANY_ENTRIES');
    for (const line of lines) {
      if (!'-d'.includes(line[0])) throw new RecipeError('DISTRIBUTION_ENTRY_TYPE', line.slice(0, 200));
    }
    const names = await run('tar', ['-tzf', archive], 120000);
    for (const name of names.stdout.split('\n').filter(Boolean)) {
      const clean = normalize(name);
      if (name.startsWith('/') || clean.startsWith('..') || clean.split(sep).includes('..')) throw new RecipeError('DISTRIBUTION_PATH_UNSAFE', name);
    }
    const temp = `${target}.${randomUUID()}`;
    await mkdir(temp, { recursive: true });
    const extracted = await run('tar', ['-xzf', archive, '-C', temp, '--no-same-owner', '--no-same-permissions'], 300000);
    if (extracted.code !== 0) throw new RecipeError('DISTRIBUTION_EXTRACT_FAILED', extracted.stderr.slice(0, 500));
    await writeFile(join(temp, '.complete'), sha256);
    await rm(target, { recursive: true, force: true });
    await rename(temp, target);
    return { sha256, bytes: bytes.length, entries: lines.length, reused: false };
  } finally {
    await rm(archive, { force: true });
  }
}

export function distributionDir(sha256) {
  if (!SHA.test(sha256 || '')) throw new RecipeError('DISTRIBUTION_ID_INVALID');
  const dir = join(config.workDir, 'distributions', sha256);
  if (!existsSync(join(dir, '.complete'))) throw new RecipeError('DISTRIBUTION_NOT_UPLOADED');
  return dir;
}

function text(value, max, code) {
  if (typeof value !== 'string' || value.length > max) throw new RecipeError(code);
  return value;
}

function strings(value, max, each, code) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > max) throw new RecipeError(code);
  return value.map((v) => text(v, each, code));
}

function mapping(value, keyPattern, max, code) {
  if (value === undefined) return {};
  if (typeof value !== 'object' || value === null || Array.isArray(value) || Object.keys(value).length > max) throw new RecipeError(code);
  return Object.fromEntries(Object.entries(value).map(([k, v]) => {
    if (!keyPattern.test(k)) throw new RecipeError(code, k);
    return [k, text(v, 4000, code)];
  }));
}

/** What every started JVM shares: main class, classpath inside its distribution, JVM options, properties and environment. */
function processSpec(input) {
  if (!CLASS.test(input.main_class || '')) throw new RecipeError('RECIPE_MAIN_CLASS_INVALID');
  const classpath = strings(input.classpath, 20, 200, 'RECIPE_CLASSPATH_INVALID');
  if (!classpath.length) throw new RecipeError('RECIPE_CLASSPATH_INVALID');
  for (const entry of classpath) {
    const clean = normalize(entry);
    if (entry.startsWith('/') || clean.startsWith('..') || clean.split(sep).includes('..') || entry.includes(':')) throw new RecipeError('RECIPE_CLASSPATH_INVALID', entry);
  }
  const jvmArgs = strings(input.jvm_args, 40, 300, 'RECIPE_JVM_ARGS_INVALID');
  for (const arg of jvmArgs) if (!arg.startsWith('-') && !/^[\w.=/,-]+$/.test(arg) || RESERVED_JVM.test(arg)) throw new RecipeError('RECIPE_JVM_ARGS_INVALID', arg);
  return { main_class: input.main_class, classpath, jvm_args: jvmArgs, args: strings(input.args, 20, 300, 'RECIPE_ARGS_INVALID'),
    system_properties: mapping(input.system_properties, PROPERTY, 40, 'RECIPE_PROPERTIES_INVALID'), env: mapping(input.env, VARIABLE, 40, 'RECIPE_ENV_INVALID') };
}

/** Strict recipe check; returns a normalised copy. */
export function validateRecipe(recipe) {
  if (typeof recipe !== 'object' || recipe === null) throw new RecipeError('RECIPE_INVALID');
  const name = text(recipe.name, 60, 'RECIPE_NAME_INVALID');
  if (!/^[a-z][a-z0-9-]{0,59}$/.test(name)) throw new RecipeError('RECIPE_NAME_INVALID');
  const main = processSpec(recipe);
  const secrets = (recipe.generated_secrets || []).map((s) => {
    if (!VARIABLE.test(s?.name || '') || !['base64', 'password'].includes(s?.kind)) throw new RecipeError('RECIPE_SECRET_INVALID');
    return { name: s.name, kind: s.kind };
  });
  if (secrets.length > 20) throw new RecipeError('RECIPE_SECRET_INVALID');
  const ports = strings(recipe.ports, 5, 41, 'RECIPE_PORTS_INVALID');
  if (ports.some((p) => !VARIABLE.test(p) || ['PORT', 'HOST'].includes(p))) throw new RecipeError('RECIPE_PORTS_INVALID');
  const files = (recipe.config_files || []).map((f) => {
    if (!/^[a-z0-9][a-z0-9._-]{0,60}$/.test(f?.name || '')) throw new RecipeError('RECIPE_CONFIG_FILE_INVALID');
    return { name: f.name, content: text(f.content, 200000, 'RECIPE_CONFIG_FILE_INVALID') };
  });
  if (files.length > 10) throw new RecipeError('RECIPE_CONFIG_FILE_INVALID');
  const dependencies = (recipe.dependencies || []).map((d) => {
    if (!NAME.test(d?.name || '')) throw new RecipeError('RECIPE_DEPENDENCY_INVALID');
    const image = text(d.image, 200, 'RECIPE_DEPENDENCY_INVALID');
    if (!config.allowedImages.some((prefix) => image.startsWith(prefix))) throw new RecipeError('RECIPE_IMAGE_NOT_ALLOWED', image);
    const port = Number(d.port);
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new RecipeError('RECIPE_DEPENDENCY_INVALID');
    // Optional seeding inside the container once it is ready (no shell: an argument list run with docker exec, plus stdin).
    const init = d.init ? { command: strings(d.init.command, 20, 300, 'RECIPE_DEPENDENCY_INVALID'), stdin: text(d.init.stdin || '', 65536, 'RECIPE_DEPENDENCY_INVALID') } : null;
    if (init && !init.command.length) throw new RecipeError('RECIPE_DEPENDENCY_INVALID');
    return { name: d.name, image, port, env: mapping(d.env, VARIABLE, 30, 'RECIPE_DEPENDENCY_INVALID'), init,
      ready_log: text(d.ready_log || '', 200, 'RECIPE_DEPENDENCY_INVALID'), ready_log_count: Math.min(Math.max(Number(d.ready_log_count) || 1, 1), 5) };
  });
  if (dependencies.length > 4) throw new RecipeError('RECIPE_DEPENDENCY_INVALID');
  // Companion processes (for example a worker that executes jobs) start once the main process is ready, each from its
  // own distribution, and count as ready when their log shows ready_log.
  const companions = (recipe.companions || []).map((c) => {
    if (!NAME.test(c?.name || '') || c.name === 'app' || !NAME.test(c.distribution || '')) throw new RecipeError('RECIPE_COMPANION_INVALID');
    return { name: c.name, distribution: c.distribution, ...processSpec(c), ready_log: text(c.ready_log || '', 200, 'RECIPE_COMPANION_INVALID'),
      ready_timeout_ms: Math.min(Math.max(Number(c.ready_timeout_ms) || 120000, 5000), 600000) };
  });
  if (companions.length > 3 || new Set(companions.map((c) => c.name)).size !== companions.length) throw new RecipeError('RECIPE_COMPANION_INVALID');
  // Git repositories the runner creates for the run (one commit each), served read-only over loopback HTTP, so an application can be
  // exercised with repository features without an external Git server.
  const repositories = (recipe.git_repositories || []).map((r) => {
    if (!NAME.test(r?.name || '') || !/^[A-Za-z0-9._/-]{1,60}$/.test(r.branch || 'main') || typeof r.files !== 'object' || r.files === null) throw new RecipeError('RECIPE_GIT_INVALID');
    const entries = Object.entries(r.files);
    if (!entries.length || entries.length > 50) throw new RecipeError('RECIPE_GIT_INVALID');
    for (const [path, content] of entries) {
      const clean = normalize(path);
      if (path.startsWith('/') || clean.startsWith('..') || clean.split(sep).includes('..') || clean.split(sep).includes('.git') || typeof content !== 'string' || content.length > 200000) throw new RecipeError('RECIPE_GIT_INVALID', path);
    }
    return { name: r.name, branch: r.branch || 'main', files: Object.fromEntries(entries) };
  });
  if (repositories.length > 3) throw new RecipeError('RECIPE_GIT_INVALID');
  // Generated values a scenario may use (for example an LDAP user's password for a basic-auth login); never returned.
  const scenarioVariables = strings(recipe.scenario_variables, 10, 41, 'RECIPE_SCENARIO_VARIABLES_INVALID');
  if (scenarioVariables.some((name) => !secrets.some((s) => s.name === name) && !ports.includes(name))) throw new RecipeError('RECIPE_SCENARIO_VARIABLES_INVALID');
  const readyPath = text(recipe.ready?.path || '/', 200, 'RECIPE_READY_INVALID');
  if (!readyPath.startsWith('/')) throw new RecipeError('RECIPE_READY_INVALID');
  const credential = recipe.credential ? { header: text(recipe.credential.header, 60, 'RECIPE_CREDENTIAL_INVALID'), value: text(recipe.credential.value, 300, 'RECIPE_CREDENTIAL_INVALID') } : null;
  if (credential && !/^[A-Za-z][A-Za-z0-9-]{0,59}$/.test(credential.header)) throw new RecipeError('RECIPE_CREDENTIAL_INVALID');
  return {
    name, ...main, generated_secrets: secrets, ports, config_files: files, dependencies, companions, git_repositories: repositories, scenario_variables: scenarioVariables,
    ready: { path: readyPath, timeout_ms: Math.min(Math.max(Number(recipe.ready?.timeout_ms) || 300000, 10000), 900000) }, credential,
  };
}

export function generateSecrets(secrets) {
  return Object.fromEntries(secrets.map((s) => [s.name, s.kind === 'base64' ? randomBytes(24).toString('base64') : randomBytes(18).toString('base64url')]));
}

/** Replace ${NAME} and ${FILE:name}; an unknown placeholder is an error, never left in place. */
export function interpolate(value, variables, files = {}) {
  return value.replace(PLACEHOLDER, (_, key) => {
    if (key.startsWith('FILE:')) {
      const path = files[key.slice(5)];
      if (!path) throw new RecipeError('RECIPE_PLACEHOLDER_UNKNOWN', key);
      return path;
    }
    if (!(key in variables)) throw new RecipeError('RECIPE_PLACEHOLDER_UNKNOWN', key);
    return String(variables[key]);
  });
}

function free(port) {
  return new Promise((resolve) => {
    const s = createServer().once('error', () => resolve(false)).once('listening', () => s.close(() => resolve(true)));
    s.listen(port, '127.0.0.1');
  });
}

export async function freePort(from, to, used = new Set()) {
  for (let p = from; p <= to; p += 1) if (!used.has(p) && await free(p)) return p;
  throw new RecipeError('NO_FREE_PORT');
}

function reachable(port) {
  return new Promise((resolve) => {
    const socket = createConnection({ host: '127.0.0.1', port }).once('connect', () => { socket.destroy(); resolve(true); }).once('error', () => resolve(false));
    socket.setTimeout(2000, () => { socket.destroy(); resolve(false); });
  });
}

/** Start each dependency in a fresh, labelled container on a loopback port; removed again by stopDependencies. */
export async function startDependencies(runId, dependencies, variables, usedPorts) {
  const started = [];
  try {
    for (const dep of dependencies) {
      const port = await freePort(config.dependencyPorts[0], config.dependencyPorts[1], usedPorts);
      usedPorts.add(port);
      variables[`${dep.name.toUpperCase().replaceAll('-', '_')}_PORT`] = port;
      const container = `archintel-dep-${runId.slice(0, 8)}-${dep.name}`;
      const env = Object.entries(dep.env).flatMap(([k, v]) => ['-e', `${k}=${interpolate(v, variables)}`]);
      const result = await run('docker', ['run', '-d', '--rm', '--name', container, '--label', 'archintel.runner=dependency', '--label', `archintel.run=${runId}`,
        '-p', `127.0.0.1:${port}:${dep.port}`, '--memory', '1g', '--pids-limit', '512', ...env, dep.image], 300000);
      if (result.code !== 0) throw new RecipeError('DEPENDENCY_START_FAILED', `${dep.name}: ${result.stderr.slice(0, 500)}`);
      started.push({ name: dep.name, container, port });
      const deadline = Date.now() + 180000;
      let ready = false;
      while (Date.now() < deadline && !ready) {
        await new Promise((r) => setTimeout(r, 1000));
        const logs = dep.ready_log ? await run('docker', ['logs', container], 15000) : { stdout: '', stderr: '' };
        const seen = dep.ready_log ? (logs.stdout + logs.stderr).split(dep.ready_log).length - 1 : dep.ready_log_count;
        ready = seen >= dep.ready_log_count && await reachable(port);
      }
      if (!ready) throw new RecipeError('DEPENDENCY_NOT_READY', dep.name);
      if (dep.init) {
        // Services such as OpenLDAP restart once after first-time setup, so seeding is retried for a short while.
        let result = null;
        for (let attempt = 0; attempt < 10; attempt += 1) {
          result = await execIn(container, dep.init.command.map((a) => interpolate(a, variables)), interpolate(dep.init.stdin, variables));
          if (result.code === 0) break;
          await new Promise((r) => setTimeout(r, 2000));
        }
        if (result.code !== 0) throw new RecipeError('DEPENDENCY_INIT_FAILED', `${dep.name}: exit ${result.code}`);
      }
    }
    return started;
  } catch (error) {
    await stopDependencies(started);
    throw error;
  }
}

function execIn(container, command, stdin) {
  return new Promise((resolve) => {
    const child = execFile('docker', ['exec', '-i', container, ...command], { timeout: 60000, maxBuffer: 4 * 1024 * 1024 },
      (error) => resolve({ code: error ? (typeof error.code === 'number' ? error.code : 1) : 0 }));
    child.stdin.end(stdin || '');
  });
}

export async function stopDependencies(started) {
  for (const dep of started || []) await run('docker', ['rm', '-f', dep.container], 60000);
}

/**
 * Create each recipe repository under the run folder with one commit and serve them read-only over smart HTTP on a loopback
 * port (some Git clients refuse file:// URLs); returns {urls: {GIT_<NAME>_URL}, server}.
 */
export async function createRepositories(dir, repositories, port) {
  if (!repositories.length) return { urls: {}, server: null };
  if (!config.gitPath) throw new RecipeError('GIT_UNAVAILABLE');
  const env = { ...process.env, GIT_AUTHOR_NAME: 'ArchIntel', GIT_AUTHOR_EMAIL: 'exploration@archintel.invalid', GIT_COMMITTER_NAME: 'ArchIntel',
    GIT_COMMITTER_EMAIL: 'exploration@archintel.invalid', GIT_CONFIG_NOSYSTEM: '1', HOME: dir };
  const git = (args, cwd) => new Promise((resolve, reject) => execFile(config.gitPath, args, { cwd, env, timeout: 60000 }, (error, stdout, stderr) =>
    error ? reject(new RecipeError('GIT_FAILED', `${args[0]}: ${stderr.slice(0, 300)}`)) : resolve(stdout)));
  const urls = {};
  for (const repo of repositories) {
    const work = join(dir, 'git-work', repo.name);
    const bare = join(dir, 'git', `${repo.name}.git`);
    await mkdir(work, { recursive: true });
    await mkdir(join(dir, 'git'), { recursive: true });
    for (const [path, content] of Object.entries(repo.files)) {
      await mkdir(join(work, path, '..'), { recursive: true });
      await writeFile(join(work, path), content);
    }
    await git(['init', '-q', '-b', repo.branch], work);
    await git(['add', '-A'], work);
    await git(['commit', '-q', '-m', 'ArchIntel exploration fixture'], work);
    await git(['clone', '-q', '--bare', work, bare], dir);
    urls[`GIT_${repo.name.toUpperCase().replaceAll('-', '_')}_URL`] = `http://127.0.0.1:${port}/${repo.name}.git`;
  }
  const server = await serveRepositories(join(dir, 'git'), port);
  return { urls, server };
}
