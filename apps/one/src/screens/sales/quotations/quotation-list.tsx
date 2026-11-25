"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchQuotes, fetchQuoteStatusCounts, QUOTES_PAGE_SIZE, quotesExportHref, type QuoteListParams } from "@/features/sales/api";
import { quoteListHref, type QuoteListState } from "@/features/sales/list-state";
import { QUOTE_STATUSES, type QuoteSummary } from "@/features/sales/types";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { asRoute, quotationStatus } from "~/data/sales-deals";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  ButtonLink,
  ChipGroup,
  ChipLink,
  Code,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Money,
  PageSummary,
  Pagination,
  SearchField,
  SegmentedLinks,
  type Column,
} from "~/ui";
import { StatusBadge } from "./parts";

function listParams(state: QuoteListState): QuoteListParams {
  return { q: state.q || null, status: state.status, scope: state.scope, offset: state.offset };
}

function columns(scope: QuoteListState["scope"]): Column<QuoteSummary>[] {
  return [
    {
      key: "number",
      header: "Quotation",
      primary: true,
      cell: (quote) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{quote.quote_number}</Code>
          <span className="t-caption text-ink-3">
            {quote.line_count === 1 ? "1 line" : `${quote.line_count} lines`}
            {quote.revision_no > 0 ? ` · revision ${quote.revision_no}` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "customer",
      header: "Customer",
      cell: (quote) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-ink" title={quote.party.display_name}>
            {quote.party.display_name}
          </span>
          {quote.customer_reference ? <span className="t-caption truncate text-ink-3">Their ref. {quote.customer_reference}</span> : null}
        </span>
      ),
    },
    { key: "status", header: "Status", cell: (quote) => <StatusBadge look={quotationStatus(quote.status)} /> },
    { key: "total", header: "Total", numeric: true, cell: (quote) => <Money value={quote.grand_total} className="t-label text-ink" /> },
    { key: "valid", header: "Valid until", cell: (quote) => <DateText value={quote.valid_until} style="business" /> },
    scope === "all"
      ? { key: "owner", header: "Owner", hideOnMobile: true, cell: (quote) => quote.owner.display_name ?? "" }
      : { key: "updated", header: "Updated", hideOnMobile: true, cell: (quote) => <DateText value={quote.updated_at} style="relative" className="text-ink-3" /> },
  ];
}

/** Quotations: every price offered. Search, status, scope and page all live in the URL. */
export function QuotationList({ state }: { state: QuoteListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const [text, setText] = useState(state.q);
  const params = listParams(state);
  const query = useQuery({ queryKey: queryKeys.sales.quotes(params), queryFn: ({ signal }) => fetchQuotes(params, signal) });
  const counts = useQuery({
    queryKey: [...queryKeys.sales.statusCounts(), { scope: state.scope }],
    queryFn: ({ signal }) => fetchQuoteStatusCounts({ scope: state.scope }, signal),
    staleTime: 30_000,
  });

  const href = (next: Partial<QuoteListState>) => asRoute(quoteListHref({ ...state, offset: 0, ...next }));
  const canCreate = permissionKeys.has("sales.quote.create");
  const filtered = Boolean(state.q.trim() || state.status);
  const limit = query.data?.limit || QUOTES_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const allCount = counts.data ? Object.values(counts.data).reduce((sum, n) => sum + (n ?? 0), 0) : undefined;
  // Statuses with nothing in them stay out of the row unless they are the one selected.
  const statuses = QUOTE_STATUSES.filter((status) => status === state.status || !counts.data || (counts.data[status] ?? 0) > 0);

  return (
    <Page>
      <PageHeader
        eyebrow="Sales"
        title="Quotations"
        lead={state.scope === "all" ? "Every price the team has offered, newest first." : "Every price you have offered, newest first."}
        actions={
          <>
            {permissionKeys.has("sales.quote.export") ? (
              <ButtonLink external href={quotesExportHref(params)} download variant="ghost" iconLeft="download">
                Export CSV
              </ButtonLink>
            ) : null}
            {canCreate ? (
              <ButtonLink href="/sales/quotes/new" iconLeft="plus">
                Create quotation
              </ButtonLink>
            ) : null}
          </>
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={{ "--i": 1 } as React.CSSProperties}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SearchField
            className="min-w-0 flex-1 basis-64"
            label="Search quotations"
            placeholder="Number, customer or country"
            value={text}
            onChange={(value) => {
              setText(value);
              if (value === "" && state.q) router.push(href({ q: "" }));
            }}
            onSubmit={(value) => router.push(href({ q: value }))}
          />
          <SegmentedLinks
            label="Whose quotations"
            value={state.scope}
            options={[
              { value: "mine", label: "Mine", href: href({ scope: "mine" }) },
              { value: "all", label: "Everyone's", href: href({ scope: "all" }) },
            ]}
          />
        </div>
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={state.status === null} count={allCount} scroll={false}>
            All
          </ChipLink>
          {statuses.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={state.status === status} count={counts.data?.[status]} scroll={false}>
              {quotationStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Quotations" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={{ "--i": 2 } as React.CSSProperties}>
          <DataTable
            label="Quotations"
            columns={columns(state.scope)}
            rows={query.data?.items ?? []}
            rowKey={(quote) => quote.id}
            rowHref={(quote) => asRoute(quote.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No quotations match"
                  text="Nothing fits this search and status. Clear them to see the full list."
                  actions={
                    <ButtonLink href={asRoute(quoteListHref({ scope: state.scope }))} variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="fileText"
                  title={state.scope === "mine" ? "You have no quotations yet" : "No quotations yet"}
                  text="A quotation starts with a customer. Lines, terms and the PDF follow in its workspace."
                  actions={
                    canCreate ? (
                      <ButtonLink href="/sales/quotes/new" iconLeft="plus">
                        Create your first quotation
                      </ButtonLink>
                    ) : state.scope === "mine" ? (
                      <ButtonLink href={href({ scope: "all" })} variant="secondary">
                        See everyone&apos;s
                      </ButtonLink>
                    ) : undefined
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="quotations" />
          {total > limit ? (
            <Pagination
              label="Quotation pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(quoteListHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
