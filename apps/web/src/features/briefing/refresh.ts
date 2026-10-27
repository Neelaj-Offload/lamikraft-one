import type { QueryClient, QueryKey } from "@tanstack/react-query";
import type { BriefingView } from "./types";

/**
 * Refetches today's briefing on the person's request (after their own action, Refresh or Try
 * again) and resolves to the briefing that this refetch returned, or null when it failed.
 *
 * Today's list is a snapshot that only the person replaces (briefing.md §7). A version that
 * was already cached before the call (for example one the UI poll fetched and the
 * "N updates · Show" pill offers) is never returned: invalidation cancels any fetch in flight
 * and starts a new one, and only data stored by that fetch counts (the cache's data-update
 * counter must have moved; timestamps are not used because two fetches can land in the same
 * millisecond). Nothing is left pending afterwards, so a later background version can never
 * be applied without asking.
 */
export async function refetchBriefing(
  queryClient: QueryClient,
  todayKey: QueryKey,
  alsoInvalidate: readonly QueryKey[] = [],
): Promise<BriefingView | null> {
  const before = queryClient.getQueryState<BriefingView>(todayKey)?.dataUpdateCount ?? 0;
  // One invalidation per key: a second one for the same key would cancel the first refetch.
  const keys = new Map([todayKey, ...alsoInvalidate].map((queryKey) => [JSON.stringify(queryKey), queryKey]));
  await Promise.all([...keys.values()].map((queryKey) => queryClient.invalidateQueries({ queryKey }, { cancelRefetch: true })));
  const state = queryClient.getQueryState<BriefingView>(todayKey);
  // A failed refetch keeps the old data and does not move the counter.
  if (!state || state.data === undefined || state.dataUpdateCount === before) return null;
  return state.data;
}
