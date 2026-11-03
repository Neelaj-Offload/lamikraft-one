import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { serverGetJson } from "@/lib/session/server";
import { challanListUrl, challanSummaryUrl } from "./api";
import { ChallanList } from "./challan-list";
import {
  challanListKey,
  challanListParams,
  challanListQueryKey,
  challanListStateFrom,
  challanSummaryParams,
  challanSummaryQueryKey,
} from "./list-state";
import { parseChallanPage, parseChallanSummary } from "./parse";

export type ChallansSearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Server part of /operations/challans: prefetches the page and the summary the URL describes with the browser's
 * cookies, so rows and figures are in the HTML; the same query keys hydrate the client list. A failed or unreadable
 * response prefetches nothing and the client fetches again and reports it.
 */
export async function ChallansPage({ searchParams }: { searchParams: ChallansSearchParams }) {
  const state = challanListStateFrom(await searchParams);
  const queryClient = new QueryClient();
  const [page, summary] = await Promise.all([
    serverGetJson(challanListUrl(challanListParams(state))),
    serverGetJson(challanSummaryUrl(challanSummaryParams(state))),
  ]);
  try {
    if (page !== null) queryClient.setQueryData(challanListQueryKey(state), parseChallanPage(page));
    if (summary !== null) queryClient.setQueryData(challanSummaryQueryKey(state), parseChallanSummary(summary));
  } catch {
    // Unreadable: the client fetches again and reports it.
  }
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ChallanList key={challanListKey(state)} state={state} />
    </HydrationBoundary>
  );
}
