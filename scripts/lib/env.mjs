// Repository paths and environment loading for scripts/dev.mjs (no dependencies).
//
// The dotenv parser mirrors backend/app/cli/dotenv.py, which writes .env and the shared
// dev-secrets file: unquoted values, single-quoted literals and double-quoted values with
// \n \r \t \" \\ escapes. Precedence for child processes matches pydantic-settings: real
// environment variables win over .env, which wins over the machine-shared secrets.

import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
export const BACKEND = join(ROOT, 'backend');
export const WEB = join(ROOT, 'apps', 'web');
export const ENV_FILE = join(ROOT, '.env');
export const COMPOSE_FILE = join(ROOT, 'docker-compose.yml');

export function devHome() {
  return process.env.LK_DEV_HOME ? resolve(process.env.LK_DEV_HOME) : join(homedir(), '.lamikraft-dev');
}

export function sharedSecretsFile() {
  return join(devHome(), 'dev-secrets.env');
}

const KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ESCAPES = { n: '\n', r: '\r', t: '\t', '"': '"', '\\': '\\', "'": "'" };

function parseValue(raw) {
  if (raw.startsWith("'")) {
    const end = raw.indexOf("'", 1);
    return end === -1 ? raw.slice(1) : raw.slice(1, end);
  }
  if (raw.startsWith('"')) {
    let out = '';
    for (let i = 1; i < raw.length; i += 1) {
      const ch = raw[i];
      if (ch === '\\' && i + 1 < raw.length) {
        const next = raw[i + 1];
        out += ESCAPES[next] ?? `\\${next}`;
        i += 1;
        continue;
      }
      if (ch === '"') break;
      out += ch;
    }
    return out;
  }
  const comment = raw.search(/\s#/);
  return (comment === -1 ? raw : raw.slice(0, comment)).trimEnd();
}

export function parseDotenv(text) {
  const values = {};
  for (const rawLine of text.split(/\r?\n/)) {
    let line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('export ')) line = line.slice(7).trimStart();
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    if (!KEY.test(key)) continue;
    values[key] = parseValue(line.slice(eq + 1).trim());
  }
  return values;
}

export function readDotenv(path) {
  return existsSync(path) ? parseDotenv(readFileSync(path, 'utf8')) : {};
}

/** Environment for child processes: shared secrets < .env < real environment < overrides. */
export function childEnv(overrides = {}) {
  const env = { ...readDotenv(sharedSecretsFile()), ...readDotenv(ENV_FILE) };
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) env[key] = value;
  }
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined || value === null) delete env[key];
    else env[key] = String(value);
  }
  return env;
}

/** The effective LK_* settings this worktree runs with (what the backend would see). */
export function settings(overrides = {}) {
  const env = childEnv(overrides);
  const int = (key, fallback) => {
    const parsed = Number.parseInt(env[key] ?? '', 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const slot = int('LK_SLOT', 0);
  const apiPort = int('LK_API_PORT', 8000 + 10 * slot);
  const webPort = int('LK_WEB_PORT', 3000 + 10 * slot);
  return {
    env,
    slot,
    lkEnv: env.LK_ENV ?? 'development',
    dbName: env.LK_DB_NAME ?? `lk_wt${slot}`,
    apiPort,
    webPort,
    e2eApiPort: int('LK_E2E_API_PORT', 8100 + 10 * slot),
    e2eWebPort: int('LK_E2E_WEB_PORT', 3100 + 10 * slot),
    apiInternalUrl: env.LK_API_INTERNAL_URL ?? `http://127.0.0.1:${apiPort}`,
    publicOrigin: env.LK_PUBLIC_ORIGIN ?? `http://127.0.0.1:${webPort}`,
    storageDir: env.LK_STORAGE_DIR ?? join(BACKEND, 'var', `storage-slot${slot}`),
  };
}

export function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

/** Scripts declared by apps/web/package.json (empty when the web app does not exist yet). */
export function webScripts() {
  return readJson(join(WEB, 'package.json'))?.scripts ?? null;
}
