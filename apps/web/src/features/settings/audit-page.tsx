import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/api/query-keys";
import { serverGetJson } from "@/lib/session/server";
import { AUDIT_PATH, auditSearch } from "./api";
import { AuditLog } from "./audit-log";
import { auditListStateFrom, auditQueryFrom } from "./list-state";
import { parseAuditPage } from "./parse";

export type AuditSearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Server part of /settings/audit: prefetches the page with the browser's cookies so rows are in
 * the HTML; the same key hydrates the client. Date filters depend on the user's zone (which only
 * the layout's bootstrap knows, and a second bootstrap would rotate the CSRF secret), so a dated
 * range is left to the client. A 403, a failure or an unreadable body prefetches nothing, and the
 * client fetches again and reports it.
 */
export async function AuditPage({ searchParams }: { searchParams: AuditSearchParams }) {
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
