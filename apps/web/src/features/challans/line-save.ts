/**
 * Debounced, never-silent saving of a challan line field (UI-83, BUG-14). Plain module (no React), so the rules are
 * unit-tested with fake timers:
 *
 * - every keystroke reschedules one save `delayMs` (600 ms) after the last change; nothing is sent while typing;
 * - one save runs at a time per field; a value typed during a save is sent after it, never in parallel;
 * - a value that fails the client rule is reported as `invalid` and not sent;
 * - a failed save is reported as `failed` with the value kept, and stays failed until `retry()` or a new value;
 *   the caller shows it inline next to the field (and the page warns before leaving);
 * - `flush()` sends a pending value at once (blur, Enter).
 */

import { normaliseDecimalInput } from "@/lib/format/decimal";

export const LINE_SAVE_DELAY_MS = 600;

export type SaveState<T> =
  | { status: "idle" }
  | { status: "pending"; value: T }
  | { status: "saving"; value: T }
  | { status: "saved"; value: T }
  | { status: "invalid"; value: T; reason: string }
  | { status: "failed"; value: T; error: unknown };

export interface DebouncedSaverOptions<T> {
  delayMs?: number;
  /** A reason the value cannot be sent, or null when it can. */
  validate?: (value: T) => string | null;
  /** Sends the value; rejects on failure. */
  save: (value: T) => Promise<void>;
  onState: (state: SaveState<T>) => void;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
}

export interface DebouncedSaver<T> {
  change: (value: T) => void;
  flush: () => Promise<void>;
  retry: () => Promise<void>;
  /** Drops a pending value (the field was reset to the saved value). */
  cancel: () => void;
  /** True while a value is pending, saving or failed: leaving the page would lose it. */
  hasUnsaved: () => boolean;
  /** Stops a pending timer (unmount); a later `change` starts again (React Strict Mode remounts). */
  dispose: () => void;
}

export function createDebouncedSaver<T>(options: DebouncedSaverOptions<T>): DebouncedSaver<T> {
  const delay = options.delayMs ?? LINE_SAVE_DELAY_MS;
  const setTimer = options.setTimer ?? ((fn: () => void, ms: number) => setTimeout(fn, ms));
  const clearTimer = options.clearTimer ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  let timer: unknown = null;
  let queued: { value: T } | null = null;
  let running: Promise<void> | null = null;
  let state: SaveState<T> = { status: "idle" };

  const set = (next: SaveState<T>) => {
    state = next;
    options.onState(next);
  };

  const stopTimer = () => {
    if (timer !== null) clearTimer(timer);
    timer = null;
  };

  const send = async (): Promise<void> => {
    if (running) return running;
    if (!queued) return;
    const { value } = queued;
    queued = null;
    const reason = options.validate?.(value) ?? null;
    if (reason) {
      set({ status: "invalid", value, reason });
      return;
    }
    set({ status: "saving", value });
    running = (async () => {
      try {
        await options.save(value);
        if (!queued) set({ status: "saved", value });
      } catch (error) {
        if (!queued) set({ status: "failed", value, error });
      } finally {
        running = null;
      }
    })();
    await running;
    // A value typed during the save goes next, once its own debounce has run out.
    if (queued && timer === null) await send();
  };

  return {
    change(value: T) {
      queued = { value };
      set({ status: "pending", value });
      stopTimer();
      timer = setTimer(() => {
        timer = null;
        void send();
      }, delay);
    },
    async flush() {
      stopTimer();
      await send();
      if (running) await running;
    },
    async retry() {
      if (state.status !== "failed" && state.status !== "invalid") return;
      queued = { value: state.value };
      stopTimer();
      await send();
    },
    cancel() {
      stopTimer();
      queued = null;
      if (state.status !== "saving") set({ status: "idle" });
    },
    hasUnsaved() {
      return queued !== null || state.status === "pending" || state.status === "saving" || state.status === "failed" || state.status === "invalid";
    },
    dispose() {
      stopTimer();
    },
  };
}

/** The client rule for a line quantity: a positive decimal with at most 4 places. The unit's own rule (whole numbers
 * for pcs, sheets, …) is the server's and comes back as a 422 shown on the field. */
export function quantityProblem(raw: string): "required" | "invalid" | "not_positive" | null {
  const result = normaliseDecimalInput(raw, { maxFractionDigits: 4 });
  if (!result.ok) return "invalid";
  if (result.value === null) return "required";
  if (/^0+(\.0+)?$/.test(result.value)) return "not_positive";
  return null;
}

/** The DecimalStr sent for a typed quantity (call after `quantityProblem` returned null). */
export function normalisedQuantity(raw: string): string {
  const result = normaliseDecimalInput(raw, { maxFractionDigits: 4 });
  return result.ok && result.value !== null ? result.value : raw.trim();
}
