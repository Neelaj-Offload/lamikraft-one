import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import type { Metadata } from "next";
import { AUDIT_PATH, auditSearch } from "@/features/settings/api";
import { auditListStateFrom, auditQueryFrom } from "@/features/settings/list-state";
import { parseAuditPage } from "@/features/settings/parse";
import { queryKeys } from "@/lib/api/query-keys";
import { serverGetJson } from "@/lib/session/server";
import { AuditLog } from "~/screens/settings-data/audit";

export const metadata: Metadata = { title: "Audit log · Settings" };

/**
 * The audit log: filters and the keyset cursor live in the URL. An undated page is fetched on the
 * server (with the browser's cookies) and hydrates the client under the same key; a dated range
 * depends on the person's time zone, so it is left to the client, as is any failed prefetch.
 */
export default async function AuditPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = auditListStateFrom(await searchParams);
  const queryClient = new QueryClient();
  if (!state.occurred_from && !state.occurred_to) {
    const query = auditSearch(auditQueryFrom(state, "UTC"));
    const raw = await serverGetJson(`${AUDIT_PATH}?${query.toString()}` as `/api/v1/${string}`);
    if (raw !== null) {
      try {
        queryClient.setQueryData(queryKeys.audit.entries(Object.fromEntries(query.entries())), parseAuditPage(raw));
      } catch {
        // Unreadable: the client fetches again and reports it.
      }
    }
  }
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <AuditLog state={state} />
    </HydrationBoundary>
  );
}
