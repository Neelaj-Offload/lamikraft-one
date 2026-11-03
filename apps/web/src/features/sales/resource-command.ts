"use client";

/**
 * Commands on commercial records other than the quote workspace (custom products, samples, price lists, FX rates,
 * settings): one Idempotency-Key per command signature (kept across retries after an unknown outcome), the related
 * queries refreshed, a 409 shown as "changed by someone else" with a reload (never a silent overwrite) and a 422
 * mapped to the form fields the server named.
 */

import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "@/components/ui/toast";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { useOnline } from "@/lib/hooks";
import { briefingMessages } from "@/messages/briefing";
import { problemDescription } from "./use-quote-command";

export type ResourceOutcome<T> = { ok: true; value: T } | { ok: false; error: unknown; conflict: boolean; fieldErrors: Record<string, string> };

/** `{field: message}` from a 422 problem's `errors` (the last segment of `loc`, body fields only). */
export function fieldErrorsOf(error: unknown): Record<string, string> {
  if (!(error instanceof ProblemError) || error.status !== 422) return {};
  const issues = (error.problem as { errors?: unknown }).errors;
  const out: Record<string, string> = {};
  if (!Array.isArray(issues)) return out;
  for (const issue of issues) {
    if (issue === null || typeof issue !== "object") continue;
    const loc = (issue as { loc?: unknown }).loc;
    const msg = (issue as { msg?: unknown }).msg;
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    const field = loc.filter((part) => typeof part === "string" && part !== "body" && part !== "query").at(-1);
    if (typeof field === "string" && !(field in out)) out[field] = msg;
  }
  return out;
}

/** How a failed command is shown: a 409 reloads the record ("changed by someone else"), a 422 maps onto fields. */
export function classifyFailure(error: unknown): { conflict: boolean; fieldErrors: Record<string, string> } {
  return { conflict: conflictFromError(error) !== null, fieldErrors: fieldErrorsOf(error) };
}

export interface ResourceRunOptions {
  done?: string;
  failed: string;
  /** Shown when the record changed meanwhile (409); the record is reloaded. */
  conflictMessage?: string;
}

export function useResourceCommand(scope: string, invalidate: readonly QueryKey[]) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [keys] = useState(() => createCommandKeys());
  const [pending, setPending] = useState<string | null>(null);
  const offline = online ? null : briefingMessages.offlineActions;

  const refresh = useCallback(
    () => Promise.all(invalidate.map((queryKey) => queryClient.invalidateQueries({ queryKey }))),
    [invalidate, queryClient],
  );

  const run = useCallback(
    async <T>(
      name: string,
      parts: readonly (string | number | null)[],
      call: (idempotencyKey: string) => Promise<T>,
      options: ResourceRunOptions,
    ): Promise<ResourceOutcome<T>> => {
      if (offline) return { ok: false, error: new Error(offline), conflict: false, fieldErrors: {} };
      const signature = commandSignature(scope, name, ...parts);
      const attempt = keys.attempt(signature, () => null);
      setPending(name);
      try {
        const value = await call(attempt.key);
        keys.settle(signature);
        await refresh();
        if (options.done) toast.success(options.done);
        return { ok: true, value };
      } catch (error) {
        keys.settle(signature, error);
        const { conflict, fieldErrors } = classifyFailure(error);
        if (conflict) {
          await refresh();
          toast.warning(options.conflictMessage ?? options.failed, { description: error instanceof ProblemError ? (error.detail ?? undefined) : undefined });
        } else if (Object.keys(fieldErrors).length === 0) {
          toast.error(options.failed, { description: problemDescription(error) });
        }
        return { ok: false, error, conflict, fieldErrors };
      } finally {
        setPending(null);
      }
    },
    [keys, offline, refresh, scope],
  );

  return { run, pending, offline, refresh };
}

// ---- tiny readers shared by the commercial adapters (the API is the source of truth; these only guard shapes) ----
export function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export class CommercialShapeError extends Error {
  override readonly name = "CommercialShapeError";
}

/** A `Page{items,total,limit,offset}` whose items are records with an `id`. */
export function pageFrom<T>(raw: unknown, what: string): { items: T[]; total: number; limit: number; offset: number } {
  if (!isObject(raw) || !Array.isArray(raw.items)) throw new CommercialShapeError(`The ${what} could not be read.`);
  const items = raw.items.filter((item): item is T => isObject(item) && typeof item.id === "string");
  const num = (value: unknown, fallback: number) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);
  return { items, total: num(raw.total, items.length), limit: num(raw.limit, items.length), offset: num(raw.offset, 0) };
}

/** A single record with an `id` and a `version`. */
export function recordFrom<T>(raw: unknown, what: string): T {
  if (!isObject(raw) || typeof raw.id !== "string") throw new CommercialShapeError(`The ${what} could not be read.`);
  return raw as T;
}
