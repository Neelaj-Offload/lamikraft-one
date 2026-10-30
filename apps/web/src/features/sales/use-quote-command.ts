"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "@/components/ui/toast";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { briefingMessages } from "@/messages/briefing";
import type { QuoteDetail } from "./types";

export type CommandOutcome = { ok: true; quote: QuoteDetail | null } | { ok: false; error: unknown };

export interface RunOptions {
  /** Toast after success. */
  done?: string;
  /** Toast title on failure ("Mark as sent didn't go through"). */
  failed: string;
  /** Handles a 409 itself (the header's three-way merge); otherwise the quote is reloaded with `conflictMessage`. */
  onConflict?: (error: ProblemError) => void | Promise<void>;
  conflictMessage?: string;
  invalidation?: keyof typeof invalidationMap;
}

/** Problem text plus the request id, for an error toast. */
export function problemDescription(error: unknown): string | undefined {
  if (!(error instanceof ProblemError)) return undefined;
  return [error.detail ?? error.title, error.request_id ? `Reference: ${error.request_id}` : null].filter(Boolean).join(" ");
}

/**
 * Runs a quote command: one Idempotency-Key per command signature (kept across retries after
 * an unknown outcome), the answer written into the quote's cache, the related queries
 * refreshed, and a 409 turned into a reload of the latest version (never a silent overwrite).
 */
export function useQuoteCommand(quoteId: string) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [commandKeys] = useState(() => createCommandKeys());
  const [pending, setPending] = useState<string | null>(null);
  const offline = online ? null : briefingMessages.offlineActions;

  const reload = useCallback(
    () => queryClient.invalidateQueries({ queryKey: queryKeys.sales.quote(quoteId) }),
    [queryClient, quoteId],
  );

  const run = useCallback(
    async (
      name: string,
      parts: readonly (string | number | null)[],
      call: (idempotencyKey: string) => Promise<QuoteDetail | null>,
      options: RunOptions,
    ): Promise<CommandOutcome> => {
      if (offline) return { ok: false, error: new Error(offline) };
      const signature = commandSignature(quoteId, name, ...parts);
      const attempt = commandKeys.attempt(signature, () => null);
      setPending(name);
      try {
        const quote = await call(attempt.key);
        commandKeys.settle(signature);
        if (quote) queryClient.setQueryData(queryKeys.sales.quote(quoteId), quote);
        const keys = invalidationMap[options.invalidation ?? "sales.quote_changed"];
        await Promise.all([
          quote ? Promise.resolve() : reload(),
          ...keys.filter((key) => !(key.length === 1 && key[0] === "sales")).map((queryKey) => queryClient.invalidateQueries({ queryKey })),
          queryClient.invalidateQueries({ queryKey: ["sales", "quotes"] }),
          queryClient.invalidateQueries({ queryKey: queryKeys.sales.quoteHistory(quoteId) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.sales.quoteRevisions(quoteId) }),
        ]);
        if (options.done) toast.success(options.done);
        return { ok: true, quote };
      } catch (error) {
        commandKeys.settle(signature, error);
        if (conflictFromError(error) && error instanceof ProblemError) {
          if (options.onConflict) await options.onConflict(error);
          else {
            await reload();
            toast.warning(options.conflictMessage ?? options.failed, { description: error.detail ?? undefined });
          }
        } else {
          toast.error(options.failed, { description: problemDescription(error) });
        }
        return { ok: false, error };
      } finally {
        setPending(null);
      }
    },
    [commandKeys, offline, queryClient, quoteId, reload],
  );

  return { run, pending, offline, reload };
}
