"use client";

import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Quantity } from "@/components/ui/format";
import { linkClasses } from "@/components/ui/styles";
import { ErrorState, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { problemDescription } from "@/features/sales/use-quote-command";
import { createIdempotencyKey } from "@/lib/api/client";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { productionMessages as m } from "@/messages/production";

export const OPERATIONS_LEADING = [{ id: "operations", label: "Overview", href: "/operations" }] as const;
const OFFLINE = "You're offline. Changes can't be saved until the connection is back.";

export const dash = <span className="text-ink-muted">{m.dash}</span>;

export function qty(value: string | null | undefined, uom: string | null | undefined) {
  return value != null && uom ? <Quantity value={{ value, uom }} /> : dash;
}

export function failure(error: unknown, what: string, retry: () => void) {
  if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
  if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={what} />;
  return <ErrorState error={error} what={what} onRetry={retry} />;
}

const WO_TONES: Record<string, Tone> = {
  draft: "neutral",
  released: "info",
  in_progress: "forest",
  completed: "success",
  closed: "neutral",
  cancelled: "neutral",
};

export function WorkOrderStatus({ status, blocked }: { status: string; blocked?: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <StatusPill tone={WO_TONES[status] ?? "neutral"}>{m.statuses[status] ?? status}</StatusPill>
      {blocked ? <StatusPill tone="warning">{m.blocked}</StatusPill> : null}
    </span>
  );
}

export function MasterStatus({ status }: { status: string }) {
  const tone: Tone = status === "approved" ? "success" : status === "draft" ? "info" : "neutral";
  return <StatusPill tone={tone}>{m.masterStatuses[status] ?? status}</StatusPill>;
}

type Tab = "workOrders" | "boms" | "routings" | "workCentres" | "capacity";

/** The production sub-navigation (work orders is the Operations context route; the rest are its pages). */
export function ProductionTabs({ current }: { current: Tab }) {
  const tabs: readonly { id: Tab; href: string; label: string }[] = [
    { id: "workOrders", href: "/operations/production/work-orders", label: m.nav.workOrders },
    { id: "boms", href: "/operations/production/boms", label: m.nav.boms },
    { id: "routings", href: "/operations/production/routings", label: m.nav.routings },
    { id: "workCentres", href: "/operations/production/work-centres", label: m.nav.workCentres },
    { id: "capacity", href: "/operations/production/capacity", label: m.nav.capacity },
  ];
  return (
    <nav aria-label={m.nav.workOrders} className="flex flex-wrap gap-4 text-sm">
      {tabs.map((t) => (
        <RacLink key={t.id} href={t.href} aria-current={t.id === current ? "page" : undefined} className={`${linkClasses} ${t.id === current ? "font-semibold" : ""}`}>
          {t.label}
        </RacLink>
      ))}
    </nav>
  );
}

/**
 * One production command at a time: a fresh Idempotency-Key per attempt, the answer written into the record's cache,
 * everything a stock or reservation change touches refreshed (`invalidationMap["production.changed"]`), failures
 * shown with the server's problem detail (never silent) and a 409 reloading the record instead of overwriting it.
 */
export function useProductionCommand<T>(recordKey: QueryKey) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [pending, setPending] = useState<string | null>(null);
  const offline = online ? null : OFFLINE;
  const run = useCallback(
    async <R,>(name: string, call: (key: string) => Promise<R>, options: { done?: string; failed: string; write?: (result: R) => T | null }): Promise<R | null> => {
      if (offline) {
        toast.error(options.failed, { description: offline });
        return null;
      }
      setPending(name);
      try {
        const result = await call(createIdempotencyKey());
        const record = options.write ? options.write(result) : null;
        if (record) queryClient.setQueryData(recordKey, record);
        await Promise.all(invalidationMap["production.changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey, refetchType: "active" })));
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
