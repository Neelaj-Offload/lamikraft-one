"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { PROFORMA_PAGE_SIZE, useProformas, type ProformaSummary } from "~/data/proforma";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  ChipGroup,
  ChipLink,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Money,
  PageSummary,
  Pagination,
  SearchField,
  TableFooter,
  type Column,
} from "~/ui";
import { PROFORMA_STATUS_LABEL, PROFORMA_STATUS_TONE, PROFORMA_STATUSES } from "./labels";
import { proformaListHref, proformaQueryOf, type ProformaListState } from "./list-state";

const href = (state: Partial<ProformaListState>) => proformaListHref(state) as Route;

const COLUMNS: Column<ProformaSummary>[] = [
  {
    key: "number",
    header: "Proforma invoice",
    primary: true,
    cell: (pi) => (
      <span className="flex min-w-0 flex-col">
        <span className="t-label lk-mono truncate text-ink">{pi.pi_number ?? pi.draft_ref}</span>
        <span className="t-caption truncate text-ink-3">
          {pi.party.display_name}
          {pi.backfilled ? " · entered from history" : ""}
        </span>
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    cell: (pi) => (
      <Badge tone={PROFORMA_STATUS_TONE[pi.status]} dot>
        {PROFORMA_STATUS_LABEL[pi.status]}
      </Badge>
    ),
  },
  { key: "quote", header: "Quotation", hideOnMobile: true, cell: (pi) => <span className="lk-mono">{pi.quote_number}</span> },
  { key: "date", header: "Date", mobileLabel: "Date", cell: (pi) => (pi.pi_date ? <DateText value={pi.pi_date} /> : <span className="text-ink-3">Not issued</span>) },
  {
    key: "total",
    header: "Total",
    numeric: true,
    cell: (pi) => (pi.grand_total ? <Money value={{ amount: pi.grand_total, currency: pi.currency }} /> : <span className="text-ink-3">Not priced</span>),
  },
];

/** Every proforma invoice sent to clients, newest first. */
export function ProformaList({ state }: { state: ProformaListState }) {
  const router = useRouter();
  const query = useProformas(proformaQueryOf(state));
  const go = (next: Partial<ProformaListState>) => router.push(href({ ...state, offset: 0, ...next }));
  const limit = query.data?.limit || PROFORMA_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;
  const filtered = Boolean(state.q || state.status);

  return (
    <Page>
      <PageHeader
        eyebrow="Sales"
        title="Proforma invoices"
        lead="What you have sent clients to pay against, made from their quotations. Create one from a sent quotation."
      />
      <div className="rise flex min-w-0 flex-col gap-3" style={{ "--i": 1 } as React.CSSProperties}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SearchField
            key={state.q}
            className="min-w-0 flex-1 basis-64"
            label="Search proforma invoices"
            placeholder="Number, customer or quotation"
            defaultValue={state.q}
            onSubmit={(q) => go({ q })}
            onChange={(q) => {
              if (q === "" && state.q !== "") go({ q: "" });
            }}
          />
        </div>
        <ChipGroup label="Status">
          {PROFORMA_STATUSES.map((s) => (
            <ChipLink key={s} href={href({ ...state, status: state.status === s ? null : s, offset: 0 })} selected={state.status === s}>
              {PROFORMA_STATUS_LABEL[s]}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>
      {query.isError ? (
        <ErrorBlock error={query.error} what="Proforma invoices" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={{ "--i": 2 } as React.CSSProperties}>
          <DataTable
            label="Proforma invoices"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(pi) => pi.id}
            rowHref={(pi) => pi.path as Route}
            loading={query.isPending}
            skeletonRows={6}
            empty={
              filtered ? (
                <EmptyState compact icon="search" title="Nothing matches" text="No proforma invoice fits this search and status." />
              ) : (
                <EmptyState
                  icon="receipt"
                  title="No proforma invoices yet"
                  text="Open a sent quotation and choose Create proforma invoice. Past PIs can be entered there with their original number."
                />
              )
            }
            footer={
              query.data && total > 0 ? (
                <TableFooter
                  left={<PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="proforma invoices" />}
                  right={pages > 1 ? <Pagination label="Proforma invoice pages" page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </Page>
  );
}
