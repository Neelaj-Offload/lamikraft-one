/**
 * Once-per-version gate for the Today greeting reveal (motion-system §2): the reveal plays the
 * first time a briefing version is seen in this tab, never again for the same version (polls,
 * revisits, reloads) and never when there is no version to key on.
 *
 * Peek and mark are separate so a React effect can check before loading GSAP and record the
 * version only when a timeline really starts (Strict Mode runs effects twice in development;
 * the first run is cleaned up before its import resolves and must not consume the version).
 */

export const REVEAL_STORAGE_KEY = "lk:today-reveal";

export type RevealStorage = Pick<Storage, "getItem" | "setItem">;

/** True when this version has not been revealed in this tab yet. Never writes. */
export function shouldReveal(revealKey: string | null, storage: RevealStorage | null): boolean {
  if (!revealKey || !storage) return false;
  try {
    return storage.getItem(REVEAL_STORAGE_KEY) !== revealKey;
  } catch {
    // Storage blocked (private mode, quota): play nothing rather than replay on every visit.
    return false;
  }
}

/** Records that the version's reveal has started. */
export function markRevealed(revealKey: string, storage: RevealStorage | null): void {
  try {
    storage?.setItem(REVEAL_STORAGE_KEY, revealKey);
  } catch {
    // Ignored: the next visit may replay, which is the lesser harm.
  }
}

export function sessionStorageOrNull(): RevealStorage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}
