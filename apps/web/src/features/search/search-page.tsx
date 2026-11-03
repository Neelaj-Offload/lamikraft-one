"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Link as RacLink } from "react-aria-components";
import { LinkButton } from "@/components/ui/link";
import { SearchField } from "@/components/ui/search-field";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { api, requestUntyped } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { parseSearchResponse } from "./parse";
import { rememberSearch, SEARCH_MIN_CHARS } from "./search-dialog";
import type { SearchResponse } from "./types";
import { PAGE_SIZE, searchPageHref, type SearchPageState } from "./page-state";

export { PAGE_SIZE, searchPageStateFrom, searchPageHref, type SearchPageState } from "./page-state";

export async function fetchSearchPage(state: SearchPageState, signal?: AbortSignal): Promise<SearchResponse> {
  const raw = await requestUntyped<unknown>(api, "get", "/api/v1/search", {
    params: { query: { q: state.q, limit: state.type ? PAGE_SIZE : 5, types: state.type ?? undefined, offset: state.type ? state.offset : undefined } },
    signal,
  });
  return parseSearchResponse(raw, state.q);
}

/** The full results page (PARITY LM-96 / UI-08 "See all"): grouped, permission-filtered, one group paged. */
export function SearchPage({ state }: { state: SearchPageState }) {
  const router = useRouter();
  const enabled = state.q.length >= SEARCH_MIN_CHARS;
  const query = useQuery({
    queryKey: [...queryKeys.search.query(state.q), { type: state.type, offset: state.offset }],
    queryFn: ({ signal }) => fetchSearchPage(state, signal),
    enabled,
  });
  useEffect(() => {
    if (enabled) rememberSearch(state.q);
  }, [enabled, state.q]);
  const go = (next: Partial<SearchPageState>) => router.push(searchPageHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">Search</h1>
      <SearchField label="Search" placeholder="Customers, quotes, products, people…" defaultValue={state.q} onSubmit={(q) => go({ q, type: null })} onClear={() => go({ q: "", type: null })} />
      {state.type ? (
        <p>
          <RacLink className={linkClasses} href={searchPageHref({ q: state.q, type: null, offset: 0 })}>
            ← All result groups
          </RacLink>
        </p>
      ) : null}
      {!enabled ? (
        <EmptyState title="Type at least 2 characters">Search finds only what you are allowed to open.</EmptyState>
      ) : query.isPending ? (
        <Loading label="search results" />
      ) : query.isError ? (
        <ErrorState error={query.error} what="search results" onRetry={() => void query.refetch()} />
      ) : query.data.groups.length === 0 ? (
        <EmptyState title={`Nothing matches “${state.q}”`}>Only records you can open are searched. Try fewer or different words.</EmptyState>
      ) : (
        <div className="flex flex-col gap-6" role="region" aria-label="Search results" aria-live="polite">
          {query.data.groups.map((group) => (
            <section key={group.resource_type} aria-labelledby={`grp-${group.resource_type}`} className="flex flex-col gap-2">
              <h2 id={`grp-${group.resource_type}`} className="flex items-baseline justify-between text-lg font-semibold">
                <span>{group.group}</span>
                <span className="text-sm font-normal text-ink-muted">{group.total} found</span>
              </h2>
              <ul className="divide-y rounded-xl border bg-surface">
                {group.items.map((hit) => (
                  <li key={hit.resource_id} className="px-4 py-2">
                    <RacLink href={hit.path} className={`${linkClasses} font-medium`}>
                      {hit.title}
                    </RacLink>
                    {hit.subtitle ? <p className="text-sm text-ink-muted">{hit.subtitle}</p> : null}
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                {state.type && state.offset > 0 ? (
                  <LinkButton size="sm" href={searchPageHref({ ...state, offset: Math.max(0, state.offset - PAGE_SIZE) })}>
                    Previous
                  </LinkButton>
                ) : null}
                {group.hasMore ? (
                  <LinkButton size="sm" href={searchPageHref({ q: state.q, type: group.resource_type, offset: state.type ? state.offset + PAGE_SIZE : 0 })}>
                    {state.type ? "Next" : `See all ${group.group.toLowerCase()}`}
                  </LinkButton>
                ) : null}
              </div>
            </section>
          ))}
          {query.data.unavailable?.length ? <p className="text-sm text-ink-muted">Not available right now: {query.data.unavailable.join(", ")}.</p> : null}
        </div>
      )}
    </div>
  );
}
