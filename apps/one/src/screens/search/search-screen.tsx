"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, type CSSProperties, type ReactNode } from "react";
import { PAGE_SIZE, searchPageHref, type SearchPageState } from "@/features/search/page-state";
import type { SearchGroup, SearchHit } from "@/features/search/types";
import { isEndpointUnavailable } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { riseIndex } from "~/lib/motion";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Banner,
  Button,
  ButtonLink,
  ChipGroup,
  ChipLink,
  EmptyState,
  GlassPanel,
  Icon,
  PageSummary,
  Pagination,
  SearchField,
  Skeleton,
  type IconName,
} from "~/ui";
import { fetchRecentSearches, fetchSearchPage, rememberSearch, SEARCH_MIN_CHARS, searchPageKey } from "~/data/entry";

/** The server pages one type up to this offset (backend MAX_OFFSET); the URL parser caps it the same way. */
const MAX_OFFSET = 200;

/** The team's words for what the server calls each group (docs/meetings: customer, quotation). */
const GROUP_WORDS: Record<string, { label: string; icon: IconName }> = {
  "parties.party": { label: "Customers and leads", icon: "users" },
  "sales.quote": { label: "Quotations", icon: "fileText" },
  "sales.sample": { label: "Samples", icon: "packageOpen" },
  "sales.custom_product": { label: "Custom products", icon: "shapes" },
  "catalogue.product": { label: "Products", icon: "box" },
  "challans.challan": { label: "Challans", icon: "fileCheck" },
};

function wordsFor(group: Pick<SearchGroup, "group" | "resource_type">): { label: string; icon: IconName } {
  const known = GROUP_WORDS[group.resource_type];
  if (known) return known;
  return { label: group.group, icon: group.group === "People" ? "user" : "file" };
}

/** The server's group names that need the team's word when it lists them as unavailable. */
const SERVER_NAMES: Record<string, string> = { Parties: "Customers and leads", Quotes: "Quotations" };

/**
 * A group's count is exact when its provider can count. When it cannot, the parser only knows
 * "at least one more": that is shown as "5+", never as a made-up total.
 */
function exactTotal(group: SearchGroup): number | null {
  const shown = (group.offset ?? 0) + group.items.length;
  return group.hasMore && group.total <= shown + 1 ? null : group.total;
}

function hrefOf(state: SearchPageState): Route {
  return searchPageHref(state) as Route;
}

/**
 * The full results screen behind the top bar's search field. The query, one type and the page
 * offset live in the URL. Without a type every group shows its best five matches; choosing a group
 * pages through that group alone. Only records the person may open are ever searched.
 */
export function SearchScreen({ state }: { state: SearchPageState }) {
  const router = useRouter();
  const client = useQueryClient();
  const enabled = state.q.length >= SEARCH_MIN_CHARS;
  const everything: SearchPageState = { q: state.q, type: null, offset: 0 };

  // Every group's best matches: the grouped view, and the source of the group chips in the paged view.
  const overview = useQuery({
    queryKey: searchPageKey(everything),
    queryFn: ({ signal }) => fetchSearchPage(everything, signal),
    enabled,
    staleTime: 30_000,
  });
  const paged = useQuery({
    queryKey: searchPageKey(state),
    queryFn: ({ signal }) => fetchSearchPage(state, signal),
    enabled: enabled && state.type !== null,
    staleTime: 30_000,
  });
  const recent = useQuery({
    queryKey: queryKeys.searchRecent.all(),
    queryFn: ({ signal }) => fetchRecentSearches(signal),
    enabled: !enabled,
    staleTime: 10_000,
  });

  useEffect(() => {
    if (!enabled) return;
    // Deferred one tick: on a full page load the session's CSRF value is seeded by a parent effect,
    // which runs after this one, and a write sent before it is refused once and retried.
    const timer = window.setTimeout(() => {
      void rememberSearch(state.q).then(() => client.invalidateQueries({ queryKey: queryKeys.searchRecent.all() }));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [enabled, state.q, client]);

  const active = state.type ? paged : overview;
  const switchedOff = isEndpointUnavailable(enabled ? active.error : recent.error);
  const chips = overview.data?.groups ?? [];

  return (
    <Page width="reading">
      <PageHeader
        title="Search"
        lead={
          enabled ? (
            <>
              Results for <span className="font-medium text-ink">“{state.q}”</span>, from the records you are allowed to open.
            </>
          ) : (
            "Find a customer, a quotation, a sample or a product by name, number or code."
          )
        }
      />

      <div className="rise" style={riseIndex(1) as CSSProperties} role="search">
        <SearchField
          key={state.q}
          label="Search Lamikraft One"
          placeholder="A name, a document number, a product code"
          size="lg"
          defaultValue={state.q}
          autoFocus={!enabled}
          isPending={enabled && active.isFetching}
          isDisabled={switchedOff}
          onSubmit={(value) => {
            const q = value.trim().slice(0, 200);
            if (q !== state.q || state.type) router.push(hrefOf({ q, type: null, offset: 0 }));
          }}
        />
      </div>

      {enabled && !switchedOff && (chips.length > 1 || (state.type !== null && chips.length > 0)) ? (
        <ChipGroup label="Show one kind of result" className="rise">
          <ChipLink href={hrefOf(everything)} selected={state.type === null} scroll={false}>
            All
          </ChipLink>
          {chips.map((group) => (
            <ChipLink
              key={group.resource_type}
              href={hrefOf({ q: state.q, type: group.resource_type, offset: 0 })}
              selected={state.type === group.resource_type}
              count={exactTotal(group) ?? undefined}
              icon={wordsFor(group).icon}
              scroll={false}
            >
              {wordsFor(group).label}
            </ChipLink>
          ))}
        </ChipGroup>
      ) : null}

      {switchedOff ? (
        <GlassPanel padding="lg" className="rise">
          <EmptyState
            icon="search"
            title="Search is not switched on"
            text="This workspace has not enabled search yet. Until it does, open records from their lists."
            actions={
              <ButtonLink href="/work" variant="inverse">
                Browse by area
              </ButtonLink>
            }
          />
        </GlassPanel>
      ) : !enabled ? (
        <Idle typed={state.q.length > 0} recent={recent.data ?? []} loading={recent.isPending} />
      ) : active.isPending ? (
        <ResultsLoading groups={state.type ? 1 : 3} />
      ) : active.isError || !active.data ? (
        <ErrorBlock error={active.error} what="Search results" onRetry={() => void active.refetch()} />
      ) : active.data.groups.length === 0 ? (
        <>
          <GlassPanel padding="lg" className="rise">
            <EmptyState
              icon="search"
              title={`Nothing matches “${state.q}”`}
              text={
                state.type
                  ? "There is nothing of this kind for these words. Look across everything instead."
                  : "Only records you can open are searched. Try fewer words, or a document number."
              }
              actions={
                state.type ? (
                  <ButtonLink href={hrefOf(everything)} variant="inverse">
                    Search everything
                  </ButtonLink>
                ) : undefined
              }
            />
          </GlassPanel>
          <Unavailable names={active.data.unavailable} onRetry={() => void active.refetch()} />
        </>
      ) : (
        <div className="stack" role="region" aria-label="Search results" aria-live="polite">
          {active.data.groups.map((group, index) => (
            <ResultGroup key={group.resource_type} group={group} state={state} index={index} />
          ))}
          <Unavailable names={active.data.unavailable} onRetry={() => void active.refetch()} />
        </div>
      )}
    </Page>
  );
}

function Idle({ typed, recent, loading }: { typed: boolean; recent: readonly { id: string; query: string }[]; loading: boolean }) {
  const headingId = useId();
  if (loading) {
    return (
      <div className="flex flex-wrap gap-2" role="status" aria-label="Loading your recent searches">
        {[112, 148, 96, 132].map((width) => (
          <Skeleton key={width} width={width} height={36} className="rounded-pill" />
        ))}
      </div>
    );
  }
  return (
    <>
      {typed ? (
        <Banner tone="neutral" icon="search">
          Type at least {SEARCH_MIN_CHARS} characters, then press Enter.
        </Banner>
      ) : null}
      {recent.length > 0 ? (
        <section className="rise flex flex-col gap-3" style={riseIndex(2) as CSSProperties} aria-labelledby={headingId}>
          <h2 id={headingId} className="t-overline px-1 text-ink-3">
            Your recent searches
          </h2>
          <ChipGroup label="Your recent searches">
            {recent.map((entry) => (
              <ChipLink key={entry.id} href={hrefOf({ q: entry.query, type: null, offset: 0 })} icon="history">
                {entry.query}
              </ChipLink>
            ))}
          </ChipGroup>
        </section>
      ) : (
        <GlassPanel padding="lg" className="rise" style={riseIndex(2) as CSSProperties}>
          <EmptyState
            icon="search"
            title="Look for anything you can open"
            text="A customer's name, a quotation number, a product code or a colleague. Your recent searches will wait here."
          />
        </GlassPanel>
      )}
    </>
  );
}

function ResultGroup({ group, state, index }: { group: SearchGroup; state: SearchPageState; index: number }) {
  const headingId = useId();
  const words = wordsFor(group);
  const total = exactTotal(group);
  const offset = group.offset ?? 0;
  const paging = state.type !== null;
  const noun = words.label.toLowerCase();
  const pages = total === null ? null : Math.min(Math.ceil(total / PAGE_SIZE), MAX_OFFSET / PAGE_SIZE + 1);

  return (
    <section className="rise flex flex-col gap-3" style={riseIndex(index + 2) as CSSProperties} aria-labelledby={headingId}>
      <GlassPanel padding="none" className="overflow-hidden">
        <div className="flex items-center gap-3 px-5 pt-5 pb-3">
          <span className="grid size-9 flex-none place-items-center rounded-sm bg-sand-soft text-ink" aria-hidden>
            <Icon name={words.icon} size={18} />
          </span>
          <h2 id={headingId} className="t-h3 min-w-0 flex-1 truncate">
            {words.label}
          </h2>
          <p className="t-body-sm lk-tnum text-ink-3">
            {total === null ? `${formatCount(offset + group.items.length)}+ found` : `${formatCount(total)} found`}
          </p>
        </div>
        <ul className="m-0 list-none divide-y divide-line p-0">
          {group.items.map((hit) => (
            <HitRow key={hit.resource_id} hit={hit} q={state.q} />
          ))}
        </ul>
        {!paging && group.hasMore ? (
          <div className="hairline-top px-5 py-3">
            <Link href={hrefOf({ q: state.q, type: group.resource_type, offset: 0 })} className="lk-link t-label inline-flex min-h-8 items-center gap-1">
              {total === null ? `See all ${noun}` : `See all ${formatCount(total)} ${noun}`}
              <Icon name="arrowRight" size={14} />
            </Link>
          </div>
        ) : null}
      </GlassPanel>

      {paging && (offset > 0 || group.hasMore) ? (
        <div className="flex flex-wrap items-center justify-between gap-3 px-1">
          {total === null || pages === null ? (
            <>
              <p className="lk-page-summary">
                Results {formatCount(offset + 1)}–{formatCount(offset + group.items.length)}
              </p>
              <div className="flex gap-2">
                {offset > 0 ? (
                  <ButtonLink href={hrefOf({ ...state, offset: Math.max(0, offset - PAGE_SIZE) })} variant="secondary" size="sm" iconLeft="chevronLeft">
                    Previous
                  </ButtonLink>
                ) : null}
                {group.hasMore && offset + PAGE_SIZE <= MAX_OFFSET ? (
                  <ButtonLink href={hrefOf({ ...state, offset: offset + PAGE_SIZE })} variant="secondary" size="sm" iconRight="chevronRight">
                    Next
                  </ButtonLink>
                ) : null}
              </div>
            </>
          ) : (
            <>
              <PageSummary from={offset + 1} to={offset + group.items.length} total={total} noun={noun} />
              <Pagination
                label={`${words.label} pages`}
                page={Math.floor(offset / PAGE_SIZE) + 1}
                pages={pages}
                hrefFor={(page) => hrefOf({ ...state, offset: (page - 1) * PAGE_SIZE })}
              />
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

function HitRow({ hit, q }: { hit: SearchHit; q: string }) {
  return (
    <li>
      <Link href={hit.path as Route} className="flex min-h-14 items-center gap-4 px-5 py-3 no-underline transition-colors hover:bg-sand-soft">
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="t-body break-words text-ink-2">
            <Marked text={hit.title} q={q} />
          </span>
          {hit.subtitle ? <span className="t-body-sm break-words text-ink-3">{hit.subtitle}</span> : null}
        </span>
        <Icon name="chevronRight" size={16} className="flex-none text-ink-4" />
      </Link>
    </li>
  );
}

/** Sets the words the person typed in ink and weight, so the eye lands on why a row matched. */
function Marked({ text, q }: { text: string; q: string }): ReactNode {
  const terms = q
    .split(/\s+/)
    .filter((term) => term.length >= 2)
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (terms.length === 0) return <span className="font-medium text-ink">{text}</span>;
  const parts = text.split(new RegExp(`(${terms.join("|")})`, "gi"));
  if (parts.length === 1) return <span className="font-medium text-ink">{text}</span>;
  return parts.map((part, index) =>
    index % 2 === 1 ? (
      <b key={index} className="font-semibold text-ink">
        {part}
      </b>
    ) : (
      part
    ),
  );
}

function Unavailable({ names, onRetry }: { names: readonly string[] | undefined; onRetry: () => void }) {
  if (!names || names.length === 0) return null;
  const list = names.map((name) => GROUP_WORDS[name]?.label ?? SERVER_NAMES[name] ?? name).join(", ");
  return (
    <Banner
      tone="amber"
      title="Part of the search did not answer."
      action={
        <Button variant="secondary" size="sm" iconLeft="refresh" onPress={onRetry}>
          Search again
        </Button>
      }
    >
      Not searched this time: {list}. These results may be incomplete.
    </Banner>
  );
}

function ResultsLoading({ groups }: { groups: number }) {
  return (
    <div className="stack" role="status" aria-label="Searching">
      {Array.from({ length: groups }, (_, group) => (
        <GlassPanel key={group} padding="none" className="overflow-hidden">
          <div className="flex items-center gap-3 px-5 pt-5 pb-3">
            <Skeleton width={36} height={36} className="rounded-sm" />
            <Skeleton width={140} height={16} />
          </div>
          <div className="divide-y divide-line">
            {Array.from({ length: groups === 1 ? 6 : 3 }, (_, row) => (
              <div key={row} className="flex min-h-14 flex-col justify-center gap-2 px-5 py-3">
                <Skeleton width={`${[52, 38, 46, 60, 42, 55][row % 6]}%`} height={14} />
                <Skeleton width={`${[30, 24, 34, 28, 22, 32][row % 6]}%`} height={10} />
              </div>
            ))}
          </div>
        </GlassPanel>
      ))}
    </div>
  );
}
