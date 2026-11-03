"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "@/components/ui/toast";
import { problemDescription } from "@/features/sales/use-quote-command";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { challansMessages as m } from "@/messages/challans";
import type { ChallanDetail } from "./types";

export type CommandOutcome = { ok: true; challan: ChallanDetail | null } | { ok: false; error: unknown };

export interface RunOptions {
  /** Toast after success. */
  done?: string;
  /** Toast title on failure; `null` when the caller shows the failure inline itself (line autosave). */
  failed: string | null;
  conflictMessage?: string;
  invalidation?: "challans.challan_changed" | "challans.challan_transition";
}

/**
 * Runs challan commands one at a time (a line autosave never races another edit of the same document): each call
 * reads the latest cached version when it starts, keeps one Idempotency-Key per command signature across retries
 * after an unknown outcome, writes the answer into the challan's cache and refreshes the list and summary. A 409
 * reloads the latest version, never overwrites it.
 */
export function useChallanCommand(challanId: string) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [commandKeys] = useState(() => createCommandKeys());
  const [pending, setPending] = useState<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const offline = online ? null : m.offline;
  const key = useMemo(() => queryKeys.challans.challan(challanId), [challanId]);

  const reload = useCallback(() => queryClient.invalidateQueries({ queryKey: key }), [queryClient, key]);

  const run = useCallback(
    (
      name: string,
      parts: readonly (string | number | null)[],
      call: (idempotencyKey: string, current: Pick<ChallanDetail, "id" | "version">) => Promise<ChallanDetail | null>,
      options: RunOptions,
    ): Promise<CommandOutcome> => {
      if (offline) {
        const error = new Error(offline);
        if (options.failed) toast.error(options.failed, { description: offline });
        return Promise.resolve({ ok: false, error });
      }
      const task = queue.current.then(async (): Promise<CommandOutcome> => {
        const cached = queryClient.getQueryData<ChallanDetail>(key);
        const current = { id: challanId, version: cached?.version ?? 0 };
        const signature = commandSignature(challanId, name, current.version, ...parts);
        const attempt = commandKeys.attempt(signature, () => null);
        setPending(name);
        try {
          const challan = await call(attempt.key, current);
          commandKeys.settle(signature);
          if (challan) queryClient.setQueryData(key, challan);
          const keys = invalidationMap[options.invalidation ?? "challans.challan_changed"];
          await Promise.all([
            challan ? Promise.resolve() : reload(),
            ...keys.filter((prefix) => !(prefix.length === 1 && prefix[0] === "challans")).map((queryKey) => queryClient.invalidateQueries({ queryKey })),
            queryClient.invalidateQueries({ queryKey: ["challans", "list"] }),
            queryClient.invalidateQueries({ queryKey: ["challans", "summary"] }),
          ]);
          if (options.done) toast.success(options.done);
          return { ok: true, challan };
        } catch (error) {
          commandKeys.settle(signature, error);
          if (conflictFromError(error) && error instanceof ProblemError) {
            await reload();
            if (options.failed) toast.warning(options.conflictMessage ?? m.workspace.conflict, { description: error.detail ?? undefined });
          } else if (options.failed) {
            toast.error(options.failed, { description: problemDescription(error) });
          }
          return { ok: false, error };
        } finally {
          setPending(null);
        }
      });
      queue.current = task.catch(() => undefined);
      return task;
    },
    [commandKeys, offline, queryClient, challanId, key, reload],
  );

  return { run, pending, offline, reload };
}

export type ChallanCommands = ReturnType<typeof useChallanCommand>;
