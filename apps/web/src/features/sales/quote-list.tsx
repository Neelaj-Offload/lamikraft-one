"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate, Money, RelativeTime } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { RadioGroup } from "@/components/ui/choice";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { salesMessages as m } from "@/messages/sales";
import { fetchQuotes, QUOTES_PAGE_SIZE, type QuoteListParams } from "./api";
import { quoteListHref, type QuoteListState } from "./list-state";
import { QUOTE_STATUSES, type QuoteStatus, type QuoteSummary } from "./types";

export { quoteListHref, quoteListStateFrom, type QuoteListState } from "./list-state";

export const QUOTE_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  internal_review: "warning",
  sent: "info",
  revised: "info",
  won: "success",
  lost: "danger",
  cancelled: "neutral",
  archived: "neutral",
};

export function QuoteStatusPill({ status }: { status: string }) {
  return <StatusPill tone={QUOTE_STATUS_TONE[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

export function quoteListParams(state: QuoteListState): QuoteListParams {
  return { q: state.q || null, status: state.status, scope: state.scope, offset: state.offset };
}

export function quoteColumns(): DataTableColumn<QuoteSummary>[] {
  return [
    {
      id: "number",
      header: m.list.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (quote) => quote.quote_number,
      cell: (quote) => (
        <RacLink href={quote.path} className={`${linkClasses} font-mono`}>
          {quote.quote_number}
        </RacLink>
      ),
    },
    { id: "party", header: m.list.columns.party, mobile: "key", cell: (quote) => quote.party.display_name },
    { id: "status", header: m.list.columns.status, mobile: "status", cell: (quote) => <QuoteStatusPill status={quote.status} /> },
    { id: "total", header: m.list.columns.total, numeric: true, mobile: "amount", cell: (quote) => <Money value={quote.grand_total} /> },
    { id: "valid", header: m.list.columns.validUntil, cell: (quote) => (quote.valid_until ? <LocalDate value={quote.valid_until} /> : <span className="text-ink-muted">—</span>) },
    { id: "updated", header: m.list.columns.updated, mobile: "meta", cell: (quote) => <RelativeTime value={quote.updated_at} className="text-ink-muted" /> },
  ];
}

export function QuoteList({ state }: { state: QuoteListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const query = useQuery({
    queryKey: queryKeys.sales.quotes(quoteListParams(state)),
    queryFn: ({ signal }) => fetchQuotes(quoteListParams(state), signal),
  });
  const go = (next: Partial<QuoteListState>) => router.push(quoteListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const canCreate = permissionKeys.has("sales.quote.create");

  useScreenContribution(
    query.data
      ? {
          lists: [
            {
              key: "quotes",
              rows: query.data.items.map((quote, index) => ({ type: "sales.quote", id: quote.id, version: quote.version, ordinal: state.offset + index + 1 })),
            },
          ],
          filters: { q: state.q, status: state.status ?? "", scope: state.scope },
        }
      : null,
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.list.title}</h1>
        {canCreate ? (
          <LinkButton href="/sales/quotes/new" variant="primary">
            {m.hub.newQuote}
          </LinkButton>
        ) : null}
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto] md:items-end">
        <SearchField
          label={m.list.search}
          placeholder={m.list.searchPlaceholder}
          defaultValue={state.q}
          onSubmit={(q) => go({ q })}
          onClear={() => go({ q: "" })}
        />
        <Select
          label={m.list.status}
          placeholder={m.list.anyStatus}
          options={[{ id: "", label: m.list.anyStatus }, ...QUOTE_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: (QUOTE_STATUSES.find((status) => status === value) ?? null) as QuoteStatus | null })}
        />
        <RadioGroup
          label={m.list.scope}
          orientation="horizontal"
          options={[
            { value: "mine", label: m.list.mine },
            { value: "all", label: m.list.all },
          ]}
          value={state.scope}
          onChange={(scope) => go({ scope: scope === "all" ? "all" : "mine" })}
        />
      </div>
      {query.isPending ? (
        <Loading label="quotes" />
      ) : query.isError ? (
        <ErrorState error={query.error} what="the quotes" onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.list.caption}
          hideCaption
          columns={quoteColumns()}
          rows={query.data.items}
          rowId={(quote) => quote.id}
          rowHref={(quote) => quote.path}
          empty={<EmptyState title={m.list.emptyTitle}>{m.list.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.list.pages}
              total={query.data.total}
              limit={query.data.limit || QUOTES_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: quoteListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
