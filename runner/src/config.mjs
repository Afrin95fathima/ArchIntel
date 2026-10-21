// Runner settings come from the environment only. The token is required; there is no default.
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function chrome() {
  const candidates = [process.env.RUNNER_CHROME, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'];
  return candidates.find((c) => c && existsSync(c)) || null;
}

function java() {
  const home = process.env.RUNNER_JAVA_HOME || process.env.JAVA_HOME || '/opt/homebrew/opt/openjdk@21';
  const bin = join(home, 'bin', 'java');
  return existsSync(bin) ? bin : null;
}

export const config = {
  root,
  token: process.env.RUNNER_TOKEN || '',
  host: process.env.RUNNER_HOST || '127.0.0.1',
  port: Number(process.env.RUNNER_PORT || 8790),
  workDir: process.env.RUNNER_WORK_DIR || join(root, '.work'),
  chromePath: chrome(),
  javaPath: java(),
  otelAgentJar: process.env.RUNNER_OTEL_AGENT || '',
  // Exact local REA install pinned by package-lock.json; tests replace it with a fake.
  reaCommand: process.env.RUNNER_REA_COMMAND ? JSON.parse(process.env.RUNNER_REA_COMMAND)
    : [process.execPath, join(root, 'node_modules', 'rea-agents', 'scripts', 'rea.mjs')],
  appPorts: [Number(process.env.RUNNER_APP_PORT_FROM || 18080), Number(process.env.RUNNER_APP_PORT_TO || 18099)],
  maxArtifactBytes: 200 * 1024 * 1024,
};
