import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { serverGetJson } from "@/lib/session/server";
import { PARTIES_PATH, partyListQuery } from "./api";
import { partyListKey, partyListParams, partyListQueryKey, partyListStateFrom } from "./list-state";
import { parsePartyPage } from "./parse";
import { PartyList } from "./party-list";

export type PartiesSearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Server part of /sales/parties: prefetches the page the URL describes with the browser's
 * cookies so rows are in the HTML; the same query key hydrates the client list. A failed or
 * unreadable response prefetches nothing, and the client fetches again and reports it.
 */
export async function PartiesPage({ searchParams }: { searchParams: PartiesSearchParams }) {
  const state = partyListStateFrom(await searchParams);
  const queryClient = new QueryClient();
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(partyListQuery(partyListParams(state)))) {
    if (value !== undefined) query.set(key, String(value));
  }
  const raw = await serverGetJson(`${PARTIES_PATH}?${query.toString()}` as `/api/v1/${string}`);
  if (raw !== null) {
    try {
      queryClient.setQueryData(partyListQueryKey(state), parsePartyPage(raw));
    } catch {
      // Unreadable: the client fetches again and reports it.
    }
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <PartyList key={partyListKey(state)} state={state} />
    </HydrationBoundary>
  );
}
