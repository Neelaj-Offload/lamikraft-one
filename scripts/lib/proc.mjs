// Windows-safe process helpers: executable lookup without a shell, npm via node + npm-cli.js,
// argument-array spawning (the repository path contains a space) and whole-tree termination.

import { spawn, spawnSync } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { createServer } from 'node:net';
import { basename, delimiter, dirname, join } from 'node:path';

export const IS_WINDOWS = process.platform === 'win32';
const HAS_CONSOLE = Boolean(process.stdin.isTTY || process.stdout.isTTY || process.stderr.isTTY);

/** Absolute path of a real executable on PATH (never .cmd/.bat: Node cannot spawn those without a shell). */
export function which(name) {
  const dirs = (process.env.PATH ?? process.env.Path ?? '').split(delimiter).filter(Boolean);
  const exts = IS_WINDOWS ? ['.exe', '.com'] : [''];
  for (const dir of dirs) {
    for (const ext of exts) {
      const candidate = join(dir.replace(/^"(.*)"$/, '$1'), name + ext);
      try {
        if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
      } catch {
        // unreadable PATH entry
      }
    }
  }
  return null;
}

function npmCliScript(name) {
  const execpath = process.env.npm_execpath;
  if (execpath && /\.(c|m)?js$/.test(execpath) && existsSync(execpath)) {
    const sibling = join(dirname(execpath), name);
    if (basename(execpath) === name) return execpath;
    if (existsSync(sibling)) return sibling;
  }
  const nodeDir = dirname(process.execPath);
  const candidates = [
    join(nodeDir, 'node_modules', 'npm', 'bin', name),
    join(nodeDir, '..', 'lib', 'node_modules', 'npm', 'bin', name),
  ];
  // Like the npm.cmd shim installed with Node on Windows, prefer an npm upgraded into the
  // global prefix (%APPDATA%\npm) over the copy bundled with node.exe.
  if (IS_WINDOWS && process.env.APPDATA) {
    candidates.unshift(join(process.env.APPDATA, 'npm', 'node_modules', 'npm', 'bin', name));
  }
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/** [command, prefixArgs] that runs npm (or npx) through the current node binary. */
export function npmCommand(tool = 'npm') {
  const script = npmCliScript(tool === 'npx' ? 'npx-cli.js' : 'npm-cli.js');
  if (!script) {
    throw new Error(`cannot locate ${tool}-cli.js next to ${process.execPath}; reinstall Node.js 24 with npm`);
  }
  return [process.execPath, [script]];
}

/** Run to completion with inherited stdio. Resolves to the exit code (signals map to 1). */
export function run(cmd, args, { cwd, env, stdio = 'inherit' } = {}) {
  return new Promise((resolvePromise) => {
    const child = spawn(cmd, args, { cwd, env, stdio, windowsHide: true });
    child.on('error', (error) => {
      process.stderr.write(`failed to start ${cmd}: ${error.message}\n`);
      resolvePromise(127);
    });
    child.on('exit', (code, signal) => resolvePromise(code ?? (signal ? 1 : 0)));
  });
}

/** Run and capture output (for probes such as `docker info`). */
export function capture(cmd, args, { cwd, env, timeoutMs = 15000 } = {}) {
  return new Promise((resolvePromise) => {
    let stdout = '';
    let stderr = '';
    let settled = false;
    const finish = (result) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolvePromise(result);
      }
    };
    const child = spawn(cmd, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    const timer = setTimeout(() => {
      killTree(child.pid);
      finish({ code: 124, stdout, stderr: `${stderr}\ntimed out after ${timeoutMs} ms` });
    }, timeoutMs);
    child.stdout.setEncoding('utf8').on('data', (chunk) => (stdout += chunk));
    child.stderr.setEncoding('utf8').on('data', (chunk) => (stderr += chunk));
    child.on('error', (error) => finish({ code: 127, stdout, stderr: error.message }));
    child.on('close', (code) => finish({ code: code ?? 1, stdout, stderr }));
  });
}

/** Forcefully terminate a process and all of its descendants. */
export function killTree(pid, signal = 'SIGKILL') {
  if (!pid) return;
  if (IS_WINDOWS) {
    const taskkill = join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'taskkill.exe');
    spawnSync(existsSync(taskkill) ? taskkill : 'taskkill', ['/pid', String(pid), '/T', '/F'], {
      stdio: 'ignore',
      windowsHide: true,
    });
    return;
  }
  for (const target of [-pid, pid]) {
    try {
      process.kill(target, signal);
      return;
    } catch {
      // not a process-group leader, or already gone
    }
  }
}

export function isAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

/** Resolves true when nothing is listening on 127.0.0.1:port. */
export function portFree(port) {
  return new Promise((resolvePromise) => {
    const server = createServer();
    server.once('error', () => resolvePromise(false));
    server.listen({ port, host: '127.0.0.1', exclusive: true }, () => server.close(() => resolvePromise(true)));
  });
}

export const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));

/** Poll an HTTP URL until it answers below 500, the deadline passes, or `abort()` returns true. */
export async function waitForHttp(url, { timeoutMs = 90000, abort = () => false } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (abort()) return { ok: false, reason: 'process exited' };
    try {
      const response = await fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(5000) });
      if (response.status < 500) return { ok: true, status: response.status };
    } catch {
      // not listening yet
    }
    await sleep(500);
  }
  return { ok: false, reason: `no answer within ${Math.round(timeoutMs / 1000)}s` };
}

/**
 * Runs long-lived processes side by side, prefixing every output line with the process name.
 * Stopping is graceful first (Ctrl+C reaches Windows console children directly; POSIX process
 * groups get SIGINT), then the remaining trees are killed.
 */
export class Supervisor {
  constructor({ colors = false } = {}) {
    this.children = new Map();
    this.colors = colors;
    this.palette = ['\x1b[36m', '\x1b[35m', '\x1b[33m', '\x1b[32m', '\x1b[34m'];
    this.width = 8;
    this.stopping = false;
    this.exitListeners = [];
  }

  prefix(name, index) {
    const label = `[${name}]`.padEnd(this.width);
    return this.colors ? `${this.palette[index % this.palette.length]}${label}\x1b[0m ` : `${label} `;
  }

  start(name, cmd, args, { cwd, env } = {}) {
    const index = this.children.size;
    this.width = Math.max(this.width, name.length + 3);
    const child = spawn(cmd, args, {
      cwd,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      // With every stdio piped, windowsHide makes libuv pass CREATE_NO_WINDOW, which detaches the
      // child from our console so Ctrl+C never reaches it. Share the console when we have one.
      windowsHide: !HAS_CONSOLE,
      detached: !IS_WINDOWS,
    });
    const entry = { name, child, exited: false, code: null };
    this.children.set(name, entry);
    const pipe = (stream, target) => {
      let pending = '';
      stream.setEncoding('utf8');
      stream.on('data', (chunk) => {
        pending += chunk;
        const lines = pending.split('\n');
        pending = lines.pop() ?? '';
        for (const line of lines) target.write(`${this.prefix(name, index)}${line.replace(/\r$/, '')}\n`);
      });
      stream.on('end', () => {
        if (pending) target.write(`${this.prefix(name, index)}${pending}\n`);
        pending = '';
      });
    };
    pipe(child.stdout, process.stdout);
    pipe(child.stderr, process.stderr);
    child.on('error', (error) => {
      process.stderr.write(`${this.prefix(name, index)}failed to start: ${error.message}\n`);
      entry.exited = true;
      entry.code = 127;
      for (const listener of this.exitListeners) listener(entry);
    });
    child.on('exit', (code, signal) => {
      if (entry.exited) return;
      entry.exited = true;
      entry.code = code ?? (signal ? 1 : 0);
      for (const listener of this.exitListeners) listener(entry);
    });
    return entry;
  }

  onExit(listener) {
    this.exitListeners.push(listener);
  }

  running() {
    return [...this.children.values()].filter((entry) => !entry.exited);
  }

  async stop({ graceful = true, timeoutMs = 8000 } = {}) {
    this.stopping = true;
    if (graceful && !IS_WINDOWS) {
      for (const entry of this.running()) killTree(entry.child.pid, 'SIGINT');
    }
    if (graceful) {
      const deadline = Date.now() + timeoutMs;
      while (this.running().length && Date.now() < deadline) await sleep(100);
    }
    for (const entry of this.running()) killTree(entry.child.pid);
    const deadline = Date.now() + 5000;
    while (this.running().length && Date.now() < deadline) await sleep(100);
  }

  /** Synchronous last resort for process 'exit' handlers. */
  killAllNow() {
    for (const entry of this.running()) killTree(entry.child.pid);
  }
}
