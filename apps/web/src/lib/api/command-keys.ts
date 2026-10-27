/**
 * Idempotency-Keys for commands the person starts (api-conventions §6, frontend_verification
 * §3 and §5): a key is minted when the person initiates a command and reused on every retry of
 * that same command, so a request that committed but whose answer was lost is replayed by the
 * server instead of being executed twice (or rejected as a conflict).
 *
 * A command is identified by a signature built from everything that goes into its request
 * (target, action, briefing version, fingerprint, reason, note …). Its key and payload are
 * kept while the outcome is unknown, that is after a network failure or a gateway error
 * (502/503/504), and retired once the server has answered definitively. A retry with the same
 * signature therefore sends the same key and the same body; a changed command gets a new key.
 */

import { createIdempotencyKey } from "./client";
import { isNetworkError, ProblemError } from "./errors";

export interface CommandAttempt<P> {
  key: string;
  payload: P;
}

export interface CommandKeys {
  /**
   * The key and payload for this command: the kept ones when an earlier attempt ended with an
   * unknown outcome, otherwise a new key and `payload()`.
   */
  attempt<P>(signature: string, payload: () => P): CommandAttempt<P>;
  /** Records how an attempt ended (no error: success). Only an unknown outcome keeps the key. */
  settle(signature: string, error?: unknown): void;
  /** Forgets kept attempts whose signature starts with `prefix` (all when omitted), e.g. when a dialog is cancelled. */
  discard(prefix?: string): void;
}

const UNKNOWN_OUTCOME_STATUSES = new Set([502, 503, 504]);

/** Whether the server may or may not have executed the command (so a retry must reuse its key). */
export function isUnknownOutcome(error: unknown): boolean {
  if (isNetworkError(error)) return true;
  return error instanceof ProblemError && UNKNOWN_OUTCOME_STATUSES.has(error.status);
}

export function createCommandKeys(mint: () => string = createIdempotencyKey): CommandKeys {
  const kept = new Map<string, CommandAttempt<unknown>>();
  return {
    attempt<P>(signature: string, payload: () => P): CommandAttempt<P> {
      const previous = kept.get(signature);
      if (previous) return previous as CommandAttempt<P>;
      const attempt: CommandAttempt<P> = { key: mint(), payload: payload() };
      kept.set(signature, attempt);
      return attempt;
    },
    settle(signature: string, error?: unknown) {
      if (error !== undefined && isUnknownOutcome(error)) return;
      kept.delete(signature);
    },
    discard(prefix?: string) {
      if (prefix === undefined) {
        kept.clear();
        return;
      }
      for (const signature of [...kept.keys()]) if (signature.startsWith(prefix)) kept.delete(signature);
    },
  };
}

type Part = string | number | null | undefined;

/** A signature from the parts of a command; parts are JSON-encoded so separators cannot collide. */
export function commandSignature(...parts: readonly Part[]): string {
  return JSON.stringify(parts.map((part) => (part === undefined ? null : part)));
}

/** The prefix shared by every signature that starts with these parts (for `discard`). */
export function commandPrefix(...parts: readonly Part[]): string {
  return commandSignature(...parts).slice(0, -1);
}
