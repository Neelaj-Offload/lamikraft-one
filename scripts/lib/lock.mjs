// A machine-wide lock file (one e2e run at a time across all worktrees).

import { mkdirSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { hostname } from 'node:os';
import { dirname } from 'node:path';

import { readJson } from './env.mjs';
import { isAlive } from './proc.mjs';

export class LockBusyError extends Error {
  constructor(path, holder) {
    super(`${path} is held by pid ${holder.pid} (${holder.root ?? 'unknown worktree'}, since ${holder.startedAt ?? '?'})`);
    this.path = path;
    this.holder = holder;
  }
}

/**
 * Create `path` exclusively. A lock left by a dead process on this host is replaced (`onStale`
 * is told); a live holder raises LockBusyError. Returns `{ path, release }`.
 */
export function acquireLock(path, { root, onStale = () => {} } = {}) {
  mkdirSync(dirname(path), { recursive: true });
  const mine = { pid: process.pid, host: hostname(), root, startedAt: new Date().toISOString() };
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      writeFileSync(path, `${JSON.stringify(mine)}\n`, { flag: 'wx' });
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const holder = readJson(path);
      if (holder && (holder.host !== hostname() || isAlive(holder.pid))) throw new LockBusyError(path, holder);
      onStale(holder);
      rmSync(path, { force: true });
      continue;
    }
    let released = false;
    return {
      path,
      release() {
        if (released) return;
        released = true;
        if (readJson(path)?.pid === process.pid) {
          try {
            unlinkSync(path);
          } catch {
            // already removed
          }
        }
      },
    };
  }
  throw new Error(`could not acquire ${path}`);
}
