import EmbeddedPostgres from '../.runtime/postgres/node_modules/embedded-postgres/dist/index.js';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const databaseDir = path.join(root, '.data', 'postgres');
mkdirSync(path.dirname(databaseDir), { recursive: true });
// PowerShell and some editors save UTF-8 files with a BOM. Strip it so the
// first environment variable is parsed the same way as subsequent lines.
const envText = readFileSync(path.join(root, '.env'), 'utf8').replace(/^\uFEFF/, '');
const password = envText.match(/^POSTGRES_PASSWORD=(.+)$/m)?.[1].trim();
if (!password) throw new Error('POSTGRES_PASSWORD missing from .env');
const databaseUrl = envText.match(/^DATABASE_URL=(.+)$/m)?.[1].trim();
if (!databaseUrl) throw new Error('DATABASE_URL missing from .env');
const port = Number(new URL(databaseUrl).port || 5432);
const pg = new EmbeddedPostgres({
  databaseDir, user: 'archintel', password, port,
  persistent: true, authMethod: 'scram-sha-256',
  postgresFlags: ['-h', '127.0.0.1'], onLog: () => {}, onError: () => {}
});
if (!existsSync(path.join(databaseDir, 'PG_VERSION'))) await pg.initialise();
await pg.start();
const client = pg.getPgClient();
await client.connect();
const exists = await client.query("SELECT 1 FROM pg_database WHERE datname='archintel'");
if (!exists.rowCount) await client.query('CREATE DATABASE archintel');
await client.end();
console.log(`ArchIntel PostgreSQL ready on 127.0.0.1:${port}`);
for (const signal of ['SIGINT','SIGTERM']) process.on(signal, async () => { await pg.stop(); process.exit(0); });
setInterval(() => {}, 60000);
