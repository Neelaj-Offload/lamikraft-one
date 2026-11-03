#!/usr/bin/env node
// Lamikraft One developer entry point behind the root npm scripts (zero dependencies).
//
//   node scripts/dev.mjs <command> [options]      e.g. npm run dev, npm run check -- --keep-going
//
// Processes are spawned with argument arrays and never through a shell, because the repository
// path contains a space; npm runs as `node npm-cli.js` (Node 24 on Windows cannot spawn .cmd
// files without a shell); uv and docker run as real executables found on PATH.

import { existsSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  BACKEND,
  COMPOSE_FILE,
  ENV_FILE,
  ROOT,
  WEB,
  childEnv,
  devHome,
  readDotenv,
  readJson,
  settings,
  sharedSecretsFile,
  webScripts,
} from './lib/env.mjs';
import {
  IS_WINDOWS,
  Supervisor,
  capture,
  npmCommand,
  portFree,
  run,
  sleep,
  waitForHttp,
  which,
} from './lib/proc.mjs';
import { LockBusyError, acquireLock } from './lib/lock.mjs';
import { bold, colorsEnabled, dim, fail, green, heading, info, red, seconds, summaryTable, warn } from './lib/ui.mjs';

const EXIT_UNAVAILABLE = 3; // same meaning as in app.cli: a command or prerequisite is not installed yet
const CLI_UNAVAILABLE_NOTE = 'not available yet (exit 3)';

class StepError extends Error {
  constructor(message, { code = 1, hint } = {}) {
    super(message);
    this.code = code;
    this.hint = hint;
  }
}

const FIX = {
  node: 'install Node.js 24 LTS from https://nodejs.org/ (or: winget install OpenJS.NodeJS.LTS), then open a new terminal',
  uv: 'install uv 0.13 (pip install --user uv==0.13.0, or: winget install --id astral-sh.uv), then open a new terminal',
  docker: 'install Docker Desktop (https://www.docker.com/products/docker-desktop/) so docker.exe is on PATH',
  daemon: 'start Docker Desktop and wait until it reports "Engine running", then re-run this command',
};

// ---------------------------------------------------------------------------------------------
// tool invocations

function tool(name, fix) {
  const path = which(name);
  if (!path) throw new StepError(`${name} was not found on PATH`, { hint: fix });
  return path;
}

const uvPath = () => tool('uv', FIX.uv);
const dockerPath = () => tool('docker', FIX.docker);

function uv(args, { env } = {}) {
  return run(uvPath(), ['run', '--locked', ...args], { cwd: BACKEND, env: env ?? childEnv() });
}

function lk(args, { env } = {}) {
  return uv(['python', '-m', 'app.cli', ...args], { env });
}

async function lkOrThrow(args, { env, what } = {}) {
  const code = await lk(args, { env });
  if (code === EXIT_UNAVAILABLE) throw new StepError(`${what ?? `lk ${args.join(' ')}`} is ${CLI_UNAVAILABLE_NOTE}`, { code });
  if (code !== 0) throw new StepError(`lk ${args.join(' ')} failed (exit ${code})`, { code });
}

function npm(args, { cwd = ROOT, env } = {}) {
  const [node, prefix] = npmCommand('npm');
  return run(node, [...prefix, ...args], { cwd, env: env ?? childEnv() });
}

function compose(args) {
  return run(dockerPath(), ['compose', '--project-directory', ROOT, '-f', COMPOSE_FILE, ...args], {
    cwd: ROOT,
    env: childEnv(),
  });
}

async function dockerServerVersion() {
  const result = await capture(dockerPath(), ['info', '--format', '{{.ServerVersion}}'], { timeoutMs: 20000 });
  return result.code === 0 && result.stdout.trim() ? result.stdout.trim() : null;
}

async function waitHealthy(container, timeoutMs = 120000) {
  const started = Date.now();
  let last = null;
  while (Date.now() - started < timeoutMs) {
    const result = await capture(dockerPath(), [
      'inspect',
      '--format',
      '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}',
      container,
    ]);
    const status = result.code === 0 ? result.stdout.trim() : 'missing';
    if (status === 'healthy') {
      info(`${container} is healthy (${seconds(Date.now() - started)})`);
      return;
    }
    if (['unhealthy', 'exited', 'dead'].includes(status)) {
      throw new StepError(`${container} is ${status}`, { hint: `see its log: docker logs ${container}` });
    }
    if (status !== last) info(`waiting for ${container} (${status || 'starting'})...`);
    last = status;
    await sleep(1000);
  }
  throw new StepError(`${container} did not become healthy within ${timeoutMs / 1000}s`, {
    hint: `see its log: docker logs ${container}`,
  });
}

async function servicesUp({ s3 = false } = {}) {
  if (!(await dockerServerVersion())) throw new StepError('the Docker daemon is not reachable', { hint: FIX.daemon });
  if (!childEnv().LK_PG_SUPERUSER_PASSWORD) {
    throw new StepError('LK_PG_SUPERUSER_PASSWORD is not set', { hint: 'run npm run setup (it writes .env via lk env init)' });
  }
  const args = [...(s3 ? ['--profile', 's3'] : []), 'up', '-d', 'postgres', ...(s3 ? ['minio'] : [])];
  if ((await compose(args)) !== 0) {
    throw new StepError('docker compose up failed', {
      hint: 'if 127.0.0.1:54329 (or 9000/9001) is taken by another program, stop it; see docs/runbooks/local-dev.md',
    });
  }
  await waitHealthy('lk-postgres');
  if (s3) await waitHealthy('lk-minio');
}

function assertLoopbackUrls(s) {
  for (const [key, value] of [
    ['LK_PUBLIC_ORIGIN', s.publicOrigin],
    ['LK_API_INTERNAL_URL', s.apiInternalUrl],
  ]) {
    if (/localhost|\[::1\]/i.test(value)) {
      throw new StepError(`${key}=${value} uses localhost`, {
        hint: 'use http://127.0.0.1:<port>; localhost can resolve to ::1 and breaks the Origin/CSRF checks and cookies',
      });
    }
  }
}

async function assertPortsFree(ports) {
  for (const [label, port] of ports) {
    if (!(await portFree(port))) {
      throw new StepError(`${label} port 127.0.0.1:${port} is already in use`, {
        hint: 'stop the other process (another worktree on the same slot?) or give this worktree its own slot: lk env init --slot N --force',
      });
    }
  }
}

function parseFlags(argv, spec, { passthrough = false } = {}) {
  const flags = {};
  const rest = [];
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (item === '--') {
      rest.push(...argv.slice(i + 1));
      break;
    }
    const eq = item.indexOf('=');
    const name = eq === -1 ? item : item.slice(0, eq);
    if (spec[name] === 'boolean' && eq === -1) {
      flags[name] = true;
    } else if (spec[name] === 'value') {
      const value = eq === -1 ? argv[(i += 1)] : item.slice(eq + 1);
      if (value === undefined) throw new StepError(`${name} needs a value`, { code: 2 });
      flags[name] = value;
    } else if (passthrough) {
      rest.push(item);
    } else {
      throw new StepError(`unknown option ${item}`, { code: 2, hint: 'run: node scripts/dev.mjs help' });
    }
  }
  return { flags, rest };
}

/** Run steps in order; stop at the first failure unless keepGoing. Prints a summary table. */
async function pipeline(title, steps, { keepGoing = false } = {}) {
  const rows = [];
  let failed = false;
  for (const step of steps) {
    if (failed && !keepGoing) {
      rows.push({ name: step.name, status: 'SKIPPED' });
      continue;
    }
    heading(step.name);
    const started = Date.now();
    let result;
    try {
      const value = await step.run();
      if (value === undefined || value === 0) result = { status: 'PASS' };
      else if (typeof value === 'number') {
        result = value === EXIT_UNAVAILABLE ? { status: 'MISSING', note: CLI_UNAVAILABLE_NOTE } : { status: 'FAIL', note: `exit ${value}` };
      } else result = value;
    } catch (error) {
      if (!(error instanceof StepError)) throw error;
      result = { status: error.code === EXIT_UNAVAILABLE ? 'MISSING' : 'FAIL', note: error.message, hint: error.hint };
    }
    rows.push({ name: step.name, ms: Date.now() - started, ...result });
    if (result.status !== 'PASS') {
      failed = true;
      fail(`${step.name}: ${result.note ?? result.status}`);
      if (result.hint) process.stderr.write(`  fix: ${result.hint}\n`);
    }
  }
  summaryTable(title, rows);
  return failed ? 1 : 0;
}

// ---------------------------------------------------------------------------------------------
// prerequisites

async function versionOf(cmd, args) {
  const result = await capture(cmd, args, { timeoutMs: 20000 });
  return result.code === 0 ? result.stdout.trim().split(/\r?\n/)[0] : null;
}

async function prerequisites() {
  const rows = [];
  const fixes = [];
  const nodeMajor = Number(process.versions.node.split('.')[0]);
  rows.push(['node', process.versions.node, nodeMajor === 24 ? null : 'Node 24 is required']);
  if (nodeMajor !== 24) fixes.push(FIX.node);

  try {
    const [node, prefix] = npmCommand('npm');
    rows.push(['npm', (await versionOf(node, [...prefix, '--version'])) ?? '?', null]);
  } catch (error) {
    rows.push(['npm', 'missing', error.message]);
    fixes.push(FIX.node);
  }

  const uvExe = which('uv');
  if (uvExe) rows.push(['uv', (await versionOf(uvExe, ['--version'])) ?? '?', null]);
  else {
    rows.push(['uv', 'missing', 'not on PATH']);
    fixes.push(FIX.uv);
  }

  const dockerExe = which('docker');
  if (!dockerExe) {
    rows.push(['docker', 'missing', 'not on PATH']);
    fixes.push(FIX.docker);
  } else {
    rows.push(['docker cli', (await versionOf(dockerExe, ['version', '--format', '{{.Client.Version}}'])) ?? '?', null]);
    const compose = await versionOf(dockerExe, ['compose', 'version', '--short']);
    rows.push(['docker compose', compose ?? 'missing', compose ? null : 'the compose plugin is required']);
    if (!compose) fixes.push(FIX.docker);
    const server = await dockerServerVersion();
    rows.push(['docker daemon', server ?? 'unreachable', server ? null : 'Docker Desktop is not running']);
    if (!server) fixes.push(FIX.daemon);
  }

  for (const [name, value, problem] of rows) {
    process.stdout.write(`  ${name.padEnd(15)} ${(problem ? red : green)(value)}${problem ? `  ${problem}` : ''}\n`);
  }
  if (fixes.length) {
    throw new StepError('missing prerequisites (nothing is installed automatically)', {
      hint: [...new Set(fixes)].join('\n  fix: '),
    });
  }
}

// ---------------------------------------------------------------------------------------------
// commands

async function setup(argv) {
  const { flags } = parseFlags(argv, { '--with-browsers': 'boolean', '--slot': 'value' });
  const slot = flags['--slot'] ?? '0';
  const steps = [
    { name: 'prerequisites', run: prerequisites },
    { name: 'backend dependencies (uv sync --locked)', run: () => run(uvPath(), ['sync', '--locked'], { cwd: BACKEND }) },
    {
      name: '.env (lk env init)',
      run: async () => {
        if (existsSync(ENV_FILE)) {
          info(`.env exists (slot ${readDotenv(ENV_FILE).LK_SLOT ?? '?'}); leaving it unchanged`);
          return 0;
        }
        return lk(['env', 'init', '--slot', slot]);
      },
    },
    { name: 'postgres (docker compose)', run: () => servicesUp() },
    { name: 'database roles', run: () => lk(['db', 'ensure-roles']) },
    { name: 'dev database', run: () => lk(['db', 'create']) },
    { name: 'test database', run: () => lk(['db', 'create', '--test']) },
    { name: 'node dependencies (npm install)', run: () => npm(['install']) },
    { name: 'migrations (lk db migrate)', run: () => lk(['db', 'migrate']) },
  ];
  if (flags['--with-browsers']) {
    steps.push({
      name: 'playwright chromium',
      run: () => {
        const [node, prefix] = npmCommand('npx');
        return run(node, [...prefix, '--no', 'playwright', 'install', 'chromium'], {
          cwd: existsSync(WEB) ? WEB : ROOT,
          env: childEnv(),
        });
      },
    });
  }
  const code = await pipeline('npm run setup', steps);
  if (code === 0) {
    const s = settings();
    info(`${bold('setup complete.')} Start everything with ${bold('npm run dev')}`);
    info(`web ${s.publicOrigin}  api ${s.apiInternalUrl}  database ${s.dbName} on 127.0.0.1:54329`);
  }
  return code;
}

async function doctor() {
  heading('prerequisites');
  await prerequisites();
  info(`repository  ${ROOT}`);
  info(`.env        ${existsSync(ENV_FILE) ? ENV_FILE : `${ENV_FILE} (missing: run npm run setup)`}`);
  info(`secrets     ${existsSync(sharedSecretsFile()) ? sharedSecretsFile() : `${sharedSecretsFile()} (missing)`}`);
  return 0;
}

async function dbUp(argv) {
  const { flags } = parseFlags(argv, { '--s3': 'boolean' });
  await servicesUp({ s3: Boolean(flags['--s3']) });
  if (flags['--s3']) info('MinIO: S3 API http://127.0.0.1:9000, console http://127.0.0.1:9001 (credentials in the shared secrets file)');
  return 0;
}

async function dbMigrate(argv) {
  await servicesUp();
  return lk(['db', 'migrate', ...argv]);
}

async function seedDemo(argv) {
  const code = await lk(['seed', 'demo', ...argv]);
  if (code === EXIT_UNAVAILABLE) {
    fail("'lk seed demo' is not available yet; the seed lane adds it as backend/app/cli/commands/seed.py");
  }
  return code;
}

async function testApi(argv) {
  return uv(['pytest', ...argv], { env: childEnv({ LK_ENV: 'test' }) });
}

async function exportOpenapi(out) {
  return lk(['api', 'export-openapi', '--out', out]);
}

async function apiGenerate() {
  const code = await exportOpenapi('openapi.json');
  if (code !== 0) return code;
  const scripts = webScripts();
  if (!scripts?.['gen:api']) {
    fail('backend/openapi.json was written, but apps/web has no gen:api script yet, so the TypeScript client types were not regenerated');
    return EXIT_UNAVAILABLE;
  }
  return npm(['run', 'gen:api', '-w', 'apps/web']);
}

async function apiCheckStep() {
  const committed = join(BACKEND, 'openapi.json');
  const temporary = join(tmpdir(), `lk-openapi-${process.pid}-${Date.now()}.json`);
  try {
    const code = await exportOpenapi(temporary);
    if (code === EXIT_UNAVAILABLE) return { status: 'MISSING', note: 'app.main is not importable yet' };
    if (code !== 0) return { status: 'FAIL', note: `export failed (exit ${code})` };
    if (!existsSync(committed)) {
      return { status: 'FAIL', note: 'backend/openapi.json does not exist', hint: 'run npm run api:generate and commit the result' };
    }
    const normalize = (path) => readFileSync(path, 'utf8').replace(/\r\n/g, '\n');
    const expected = normalize(temporary);
    const actual = normalize(committed);
    if (expected === actual) return { status: 'PASS', note: 'backend/openapi.json matches the app' };
    const a = actual.split('\n');
    const b = expected.split('\n');
    let line = 0;
    while (line < Math.max(a.length, b.length) && a[line] === b[line]) line += 1;
    process.stdout.write(`first difference at backend/openapi.json line ${line + 1}:\n`);
    process.stdout.write(`  committed: ${dim(a[line] ?? '<end of file>')}\n  generated: ${dim(b[line] ?? '<end of file>')}\n`);
    return {
      status: 'FAIL',
      note: 'backend/openapi.json is out of date',
      hint: 'run npm run api:generate (regenerates openapi.json and the web client types), then commit both',
    };
  } finally {
    rmSync(temporary, { force: true });
  }
}

async function apiCheck() {
  return pipeline('npm run api:check', [{ name: 'api:check', run: apiCheckStep }]);
}

function webScriptStep(name, candidates) {
  return {
    name,
    run: async () => {
      const scripts = webScripts();
      if (!scripts) return { status: 'MISSING', note: 'apps/web/package.json does not exist yet' };
      const script = candidates.find((candidate) => scripts[candidate]);
      if (!script) return { status: 'MISSING', note: `apps/web has no ${candidates.join(' or ')} script` };
      return npm(['run', script, '-w', 'apps/web']);
    },
  };
}

async function check(argv) {
  const { flags } = parseFlags(argv, { '--keep-going': 'boolean' });
  const steps = [
    { name: 'backend: ruff check', run: () => uv(['ruff', 'check', '.']) },
    {
      name: 'backend: pytest unit + contract',
      run: async () => {
        const code = await uv(['pytest', 'tests/unit', 'tests/contract'], { env: childEnv({ LK_ENV: 'test' }) });
        return code === 5 ? { status: 'FAIL', note: 'no tests collected' } : code;
      },
    },
    { name: 'alembic heads == 1', run: () => lk(['db', 'heads']) },
    { name: 'api:check', run: apiCheckStep },
    webScriptStep('web: lint', ['lint']),
    webScriptStep('web: typecheck', ['typecheck']),
    webScriptStep('web: vitest', ['test:unit', 'test']),
  ];
  return pipeline('npm run check', steps, { keepGoing: Boolean(flags['--keep-going']) });
}

function installShutdown(supervisor, onStop = () => {}) {
  let stopping = false;
  const stop = async (reason, code) => {
    if (stopping) {
      supervisor.killAllNow();
      onStop();
      process.exit(code);
    }
    stopping = true;
    info(`stopping (${reason})...`);
    // On Windows, Ctrl+C already reached every console child; anything else needs a hard kill.
    await supervisor.stop({ graceful: reason === 'Ctrl+C' || !IS_WINDOWS });
    onStop();
    process.exit(code);
  };
  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK']) {
    try {
      process.on(signal, () => stop(signal === 'SIGINT' ? 'Ctrl+C' : signal, 130));
    } catch {
      // signal not supported on this platform
    }
  }
  process.on('exit', () => {
    supervisor.killAllNow();
    onStop();
  });
  return stop;
}

function pythonEnv(overrides = {}) {
  return childEnv({ PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', ...overrides });
}

async function dev(argv) {
  const { flags } = parseFlags(argv, { '--no-migrate': 'boolean', '--no-web': 'boolean', '--no-worker': 'boolean' });
  if (!existsSync(ENV_FILE)) throw new StepError(`${ENV_FILE} is missing`, { hint: 'run npm run setup' });
  const s = settings();
  assertLoopbackUrls(s);
  await servicesUp();
  if ((await run(uvPath(), ['sync', '--locked', '--quiet'], { cwd: BACKEND })) !== 0) {
    throw new StepError('uv sync --locked failed', { hint: 'the lockfile may be out of date; ask the integrator to relock' });
  }
  if (!flags['--no-migrate']) {
    const code = await lk(['db', 'migrate']);
    if (code === EXIT_UNAVAILABLE) warn('migrations are not set up yet; starting without them');
    else if (code !== 0) throw new StepError(`lk db migrate failed (exit ${code})`, { hint: 'fix the migration, or start with --no-migrate' });
  }

  const wanted = {
    api: existsSync(join(BACKEND, 'app', 'main.py')),
    worker: !flags['--no-worker'] && existsSync(join(BACKEND, 'app', 'worker.py')),
    web: !flags['--no-web'] && Boolean(webScripts()?.dev),
  };
  if (!wanted.api) warn('backend/app/main.py does not exist yet; the API is not started');
  if (!flags['--no-worker'] && !wanted.worker) warn('backend/app/worker.py does not exist yet; the worker is not started');
  if (!flags['--no-web'] && !wanted.web) warn('apps/web has no dev script yet; the web app is not started');
  if (!Object.values(wanted).some(Boolean)) throw new StepError('nothing to start', { code: EXIT_UNAVAILABLE });
  await assertPortsFree([
    ...(wanted.api ? [['api', s.apiPort]] : []),
    ...(wanted.web ? [['web', s.webPort]] : []),
  ]);

  const supervisor = new Supervisor({ colors: colorsEnabled });
  const stop = installShutdown(supervisor);
  supervisor.onExit((entry) => {
    if (supervisor.stopping) return;
    fail(`${entry.name} exited with code ${entry.code}; stopping the others`);
    stop(`${entry.name} exited`, entry.code || 1);
  });

  const started = {};
  if (wanted.api) {
    started.api = supervisor.start(
      'api',
      uvPath(),
      ['run', '--no-sync', 'python', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(s.apiPort), '--no-proxy-headers', '--reload', '--reload-dir', 'app'],
      { cwd: BACKEND, env: pythonEnv() },
    );
  }
  if (wanted.worker) {
    started.worker = supervisor.start('worker', uvPath(), ['run', '--no-sync', 'python', '-m', 'app.worker'], {
      cwd: BACKEND,
      env: pythonEnv(),
    });
  }
  if (wanted.web) {
    const [node, prefix] = npmCommand('npm');
    started.web = supervisor.start('web', node, [...prefix, 'run', 'dev', '-w', 'apps/web'], {
      cwd: ROOT,
      env: childEnv({
        PORT: s.webPort,
        HOSTNAME: '127.0.0.1',
        LK_API_INTERNAL_URL: s.apiInternalUrl,
        LK_PUBLIC_ORIGIN: s.publicOrigin,
        FORCE_COLOR: colorsEnabled ? '1' : undefined,
      }),
    });
  }

  const waits = [];
  if (started.api) {
    waits.push(
      waitForHttp(`${s.apiInternalUrl}/api/v1/health/live`, { timeoutMs: 120000, abort: () => started.api.exited }).then(
        async (result) => {
          if (!result.ok) return warn(`api did not become live: ${result.reason}`);
          const ready = await fetch(`${s.apiInternalUrl}/api/v1/health/ready`, { signal: AbortSignal.timeout(5000) }).then(
            (response) => response.status,
            () => 'unreachable',
          );
          info(`api ready on ${s.apiInternalUrl} (live 200, ready ${ready})`);
        },
      ),
    );
  }
  if (started.worker) info('worker started (polling the job queue)');
  if (started.web) {
    waits.push(
      waitForHttp(`${s.publicOrigin}/`, { timeoutMs: 240000, abort: () => started.web.exited }).then((result) =>
        result.ok ? info(`web ready on ${s.publicOrigin}`) : warn(`web did not answer: ${result.reason}`),
      ),
    );
  }
  await Promise.all(waits);
  if (!supervisor.stopping) {
    info(`${bold('Lamikraft One is running')}${started.web ? `: open ${s.publicOrigin}` : ''}. Ctrl+C stops everything.`);
  }
  return new Promise(() => {}); // runs until a signal or a child exit calls stop()
}

function acquireE2eLock() {
  const path = join(devHome(), 'e2e.lock');
  try {
    return acquireLock(path, {
      root: ROOT,
      onStale: (holder) => warn(`removing a stale e2e lock (pid ${holder?.pid ?? 'unknown'})`),
    });
  } catch (error) {
    if (!(error instanceof LockBusyError)) throw error;
    throw new StepError(`another e2e run is in progress: ${error.message}`, {
      hint: `wait for it to finish; if no e2e run is active any more, delete ${path}`,
    });
  }
}

async function testE2e(argv) {
  const { flags, rest } = parseFlags(argv, { '--no-build': 'boolean' }, { passthrough: true });
  const scripts = webScripts();
  if (!scripts) throw new StepError('apps/web/package.json does not exist yet', { code: EXIT_UNAVAILABLE });
  for (const script of ['build', 'start']) {
    if (!scripts[script]) throw new StepError(`apps/web has no ${script} script`, { code: EXIT_UNAVAILABLE });
  }
  const lock = acquireE2eLock();
  const supervisor = new Supervisor({ colors: colorsEnabled });
  installShutdown(supervisor, () => lock.release());
  try {
    const base = settings();
    // Own database, rebuilt and seeded at D0 on every run: sharing lk_wt<N>_test with the pytest suite
    // left e2e rows behind that broke the next `npm run test:api`, and a reused database accumulates
    // quotes across runs.
    const testDb = `${base.dbName.replace(/_test$/, '')}_e2e`;
    const apiUrl = `http://127.0.0.1:${base.e2eApiPort}`;
    const webUrl = `http://127.0.0.1:${base.e2eWebPort}`;
    const overrides = {
      LK_ENV: 'test',
      LK_DB_NAME: testDb,
      LK_API_PORT: base.e2eApiPort,
      LK_WEB_PORT: base.e2eWebPort,
      LK_PUBLIC_ORIGIN: webUrl,
      LK_API_INTERNAL_URL: apiUrl,
      LK_STORAGE_DIR: `${base.storageDir}-e2e`,
      PORT: base.e2eWebPort,
      HOSTNAME: '127.0.0.1',
      LK_E2E_API_PORT: base.e2eApiPort,
      LK_E2E_WEB_PORT: base.e2eWebPort,
      LK_E2E_API_URL: apiUrl,
      // apps/web/playwright.config.ts skips its own webServer when this is set.
      LK_E2E_EXTERNAL_WEB: '1',
    };
    info(`e2e: database ${testDb}, api ${apiUrl}, web ${webUrl} (lock ${lock.path})`);
    await servicesUp();
    await lkOrThrow(['db', 'drop', '--yes'], { env: childEnv(overrides) });
    await lkOrThrow(['db', 'create'], { env: childEnv(overrides) });
    await lkOrThrow(['db', 'migrate'], { env: childEnv(overrides) });
    await lkOrThrow(['seed', 'demo', '--anchor-date', '2026-10-12', '--slice', '2'], { env: childEnv(overrides) });
    await assertPortsFree([
      ['e2e api', base.e2eApiPort],
      ['e2e web', base.e2eWebPort],
    ]);
    if (flags['--no-build']) {
      // Next bakes the /api rewrite target into the build, so an old build may point elsewhere.
      const target = readJson(join(WEB, '.next', 'routes-manifest.json'))?.rewrites?.beforeFiles?.find((rule) =>
        rule.source.startsWith('/api'),
      )?.destination;
      if (!target?.startsWith(`${apiUrl}/`)) {
        throw new StepError(`the existing web build sends /api to ${target ?? 'nowhere (no build found)'}, not ${apiUrl}`, {
          hint: 'run npm run test:e2e without --no-build',
        });
      }
    } else {
      heading('next build (apps/web)');
      const code = await npm(['run', 'build', '-w', 'apps/web'], { env: childEnv(overrides) });
      if (code !== 0) throw new StepError(`web build failed (exit ${code})`, { code });
    }

    supervisor.onExit((entry) => {
      if (!supervisor.stopping) fail(`${entry.name} exited with code ${entry.code} during the e2e run`);
    });
    const api = supervisor.start(
      'api',
      uvPath(),
      ['run', '--locked', 'python', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(base.e2eApiPort), '--no-proxy-headers'],
      { cwd: BACKEND, env: pythonEnv(overrides) },
    );
    if (existsSync(join(BACKEND, 'app', 'worker.py'))) {
      supervisor.start('worker', uvPath(), ['run', '--locked', 'python', '-m', 'app.worker'], {
        cwd: BACKEND,
        env: pythonEnv(overrides),
      });
    }
    const [node, prefix] = npmCommand('npm');
    const web = supervisor.start('web', node, [...prefix, 'run', 'start', '-w', 'apps/web'], {
      cwd: ROOT,
      env: childEnv(overrides),
    });
    const [apiReady, webReady] = await Promise.all([
      waitForHttp(`${apiUrl}/api/v1/health/live`, { timeoutMs: 120000, abort: () => api.exited }),
      waitForHttp(`${webUrl}/`, { timeoutMs: 120000, abort: () => web.exited }),
    ]);
    if (!apiReady.ok) throw new StepError(`e2e api did not start: ${apiReady.reason}`);
    if (!webReady.ok) throw new StepError(`e2e web did not start: ${webReady.reason}`);
    info('e2e servers ready; running playwright');

    const [npxNode, npxPrefix] = npmCommand('npx');
    return await run(npxNode, [...npxPrefix, '--no', 'playwright', 'test', ...rest], { cwd: WEB, env: childEnv(overrides) });
  } finally {
    await supervisor.stop({ graceful: false });
    lock.release();
  }
}

async function lkPassthrough(argv) {
  return lk(argv);
}

const COMMANDS = {
  setup: [setup, 'prerequisites, .env, postgres, roles, databases, dependencies, migrations [--slot N] [--with-browsers]'],
  dev: [dev, 'postgres + migrations, then API, worker and web with prefixed logs [--no-migrate] [--no-web] [--no-worker]'],
  check: [check, 'ruff, pytest unit+contract, alembic heads, api:check, web lint/typecheck/vitest [--keep-going]'],
  'test-api': [testApi, 'full pytest suite with LK_ENV=test (extra args go to pytest)'],
  'test-e2e': [testE2e, 'API + web on the e2e ports against the test DB, then playwright [--no-build] (extra args go to playwright)'],
  'api-generate': [apiGenerate, 'export backend/openapi.json and regenerate the web client types'],
  'api-check': [apiCheck, 'fail if backend/openapi.json differs from the app'],
  'db-up': [dbUp, 'start postgres (and MinIO with --s3) and wait until healthy'],
  'db-migrate': [dbMigrate, 'lk db migrate (extra args such as --test are passed on)'],
  'seed-demo': [seedDemo, 'lk seed demo'],
  doctor: [doctor, 'check prerequisites and show where configuration lives'],
  lk: [lkPassthrough, 'run the backend CLI: node scripts/dev.mjs lk db status'],
  help: [help, 'this list'],
};

function help() {
  process.stdout.write(`${bold('Lamikraft One dev script')}  ${dim(ROOT)}\n\nusage: node scripts/dev.mjs <command> [options]\n\n`);
  for (const [name, [, description]] of Object.entries(COMMANDS)) {
    process.stdout.write(`  ${name.padEnd(13)} ${description}\n`);
  }
  return 0;
}

async function main() {
  const [name = 'help', ...argv] = process.argv.slice(2);
  const entry = COMMANDS[name === '--help' || name === '-h' ? 'help' : name];
  if (!entry) {
    fail(`unknown command: ${name}`);
    help();
    return 2;
  }
  try {
    return await entry[0](argv);
  } catch (error) {
    if (!(error instanceof StepError)) throw error;
    fail(error.message);
    if (error.hint) process.stderr.write(`  fix: ${error.hint}\n`);
    return error.code;
  }
}

main().then(
  (code) => {
    process.exitCode = code ?? 0;
  },
  (error) => {
    fail(error?.stack ?? String(error));
    process.exitCode = 1;
  },
);
