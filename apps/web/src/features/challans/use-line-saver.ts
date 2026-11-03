"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { conflictFromError, isNetworkError, ProblemError } from "@/lib/api/errors";
import { challansMessages as m } from "@/messages/challans";
import { createDebouncedSaver, normalisedQuantity, quantityProblem, type DebouncedSaver, type SaveState } from "./line-save";

/** The inline message for a failed save: the server's field message (422), a conflict, offline, or the problem text. */
export function saveFailureText(error: unknown): string {
  if (error instanceof ProblemError && error.status === 422) return error.validationIssues[0]?.msg ?? error.detail ?? error.title;
  if (conflictFromError(error)) return m.workspace.save.conflict;
  if (isNetworkError(error)) return m.workspace.save.offline;
  if (error instanceof ProblemError) return [error.detail ?? error.title, error.request_id ? `Reference: ${error.request_id}` : null].filter(Boolean).join(" ");
  return error instanceof Error ? error.message : m.workspace.save.failed;
}

/**
 * React wrapper of `createDebouncedSaver`: the saver lives in an effect (created on mount, a pending value flushed on
 * unmount), the handlers are stable, the latest `save` is always used, and the browser warns before leaving while a
 * value is pending, saving or failed.
 */
export function useDebouncedSaver<T>(save: (value: T) => Promise<void>, options: { delayMs?: number; validate?: (value: T) => string | null } = {}) {
  const [state, setState] = useState<SaveState<T>>({ status: "idle" });
  const saveRef = useRef(save);
  const validateRef = useRef(options.validate);
  const saver = useRef<DebouncedSaver<T> | null>(null);
  const delayMs = options.delayMs;
  useEffect(() => {
    saveRef.current = save;
    validateRef.current = options.validate;
  });
  useEffect(() => {
    const created = createDebouncedSaver<T>({
      delayMs,
      validate: (value) => validateRef.current?.(value) ?? null,
      save: (value) => saveRef.current(value),
      onState: setState,
    });
    saver.current = created;
    const warn = (event: BeforeUnloadEvent) => {
      if (created.hasUnsaved()) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      // Leaving the page inside the app: send a pending value now rather than dropping it.
      void created.flush();
    };
  }, [delayMs]);

  const change = useCallback((value: T) => saver.current?.change(value), []);
  const flush = useCallback(() => saver.current?.flush() ?? Promise.resolve(), []);
  const retry = useCallback(() => saver.current?.retry() ?? Promise.resolve(), []);
  return { state, change, flush, retry };
}

/** A line quantity: 600 ms debounce, the client rule first (`quantityProblem`), then the server's. */
export function useQuantitySaver(save: (quantity: string) => Promise<void>) {
  return useDebouncedSaver<string>((raw) => save(normalisedQuantity(raw)), {
    validate: (raw) => {
      const problem = quantityProblem(raw);
      return problem ? (m.workspace.save.invalid[problem] ?? problem) : null;
    },
  });
}
