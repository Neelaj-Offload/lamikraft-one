"use client";

import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "@/components/ui/toast";
import { problemDescription } from "@/features/sales/use-quote-command";
import { createIdempotencyKey } from "@/lib/api/client";
import { conflictFromError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";

const OFFLINE = "You're offline. Changes can't be saved until the connection is back.";

/**
 * Runs one inventory or order command at a time: a fresh Idempotency-Key per attempt, the answer written into the
 * record's cache, the related queries refreshed (`invalidationMap["inventory.changed"]`), failures shown as toasts
 * with the server's problem detail (never silent) and a 409 reloading the record instead of overwriting it.
 */
export function useCommand<T>(recordKey: QueryKey) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [pending, setPending] = useState<string | null>(null);
  const offline = online ? null : OFFLINE;

  const run = useCallback(
    async <R>(name: string, call: (key: string) => Promise<R>, options: { done?: string; failed: string; write?: (result: R) => T | null }): Promise<R | null> => {
      if (offline) {
        toast.error(options.failed, { description: offline });
        return null;
      }
      setPending(name);
      try {
        const result = await call(createIdempotencyKey());
        const record = options.write ? options.write(result) : null;
        if (record) queryClient.setQueryData(recordKey, record);
        await Promise.all(invalidationMap["inventory.changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
        if (!record) await queryClient.invalidateQueries({ queryKey: recordKey });
        if (options.done) toast.success(options.done);
        return result;
      } catch (error) {
        if (conflictFromError(error)) await queryClient.invalidateQueries({ queryKey: recordKey });
        toast.error(options.failed, { description: problemDescription(error) });
        return null;
      } finally {
        setPending(null);
      }
    },
    [offline, queryClient, recordKey],
  );

  return { run, pending, offline };
}
