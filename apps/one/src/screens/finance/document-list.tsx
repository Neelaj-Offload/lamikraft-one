"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { documentsCsvHref, PAGE_SIZE, type InvoiceSummary } from "@/features/finance/api";
import { docBase, docHref, DOC_STATUSES, type DocKind, type DocListState } from "@/features/finance/list-state";
import { asRoute, documentStatus, useFinanceDocuments } from "~/data/finance";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, Money, PageSummary, Pagination, SearchField, type Column } from "~/ui";
import { stagger, StatusBadge } from "./parts";

const COPY = {
  invoice: {
    title: "Invoices",
    lead: "Every invoice from draft to paid, with what each customer still owes.",
    noun: "invoices",
    search: "Search invoices",
  },
  credit_note: {
    title: "Credit notes",
    lead: "Credits raised against issued invoices. An issued credit note settles its invoice first.",
    noun: "credit notes",
    search: "Search credit notes",
  },
} as const;

function columns(kind: DocKind): Column<InvoiceSummary>[] {
  const credit = kind === "credit_note";
  return [
    {
      key: "number",
      header: credit ? "Credit note" : "Invoice",
      primary: true,
      cell: (doc) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{doc.document_number ?? doc.draft_ref}</Code>
          {doc.label ? <span className="t-caption text-ink-3">{doc.label}</span> : doc.document_date ? <DateText value={doc.document_date} style="business" className="t-caption text-ink-3" /> : null}
        </span>
      ),
    },
    {
      key: "customer",
      header: "Customer",
      cell: (doc) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-ink" title={doc.party.display_name}>
            {doc.party.display_name}
          </span>
          {doc.owner?.display_name ? <span className="t-caption text-ink-3">Owner: {doc.owner.display_name}</span> : null}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (doc) =>
        doc.is_overdue ? (
          <Badge tone="ember" icon="clock">
            Overdue
          </Badge>
        ) : (
          <StatusBadge look={documentStatus(doc.status)} />
        ),
    },
    { key: "due", header: credit ? "Dated" : "Due", hideOnMobile: credit, cell: (doc) => <DateText value={credit ? doc.document_date : doc.due_date} style="business" /> },
    { key: "total", header: "Total", numeric: true, cell: (doc) => <Money value={doc.total} className="t-label text-ink" /> },
    { key: "outstanding", header: "Outstanding", numeric: true, cell: (doc) => <Money value={doc.outstanding} /> },
  ];
}

/** Invoices or credit notes. Search, status, the open and overdue switches and the page all live in the URL. */
export function DocumentList({ kind, state }: { kind: DocKind; state: DocListState }) {
  const router = useRouter();
  const [text, setText] = useState(state.q);
  const query = useFinanceDocuments(kind, state);
  const copy = COPY[kind];
  const credit = kind === "credit_note";
  const href = (next: Partial<DocListState>) => asRoute(docHref(kind, { ...state, offset: 0, ...next }));
  const filtered = Boolean(state.q.trim() || state.status || state.open || state.overdue);
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;

  return (
    <Page>
      <PageHeader
        eyebrow="Finance"
        title={copy.title}
        lead={copy.lead}
        actions={
          <ButtonLink external href={documentsCsvHref(kind, state)} download variant="ghost" iconLeft="download">
            Download CSV
          </ButtonLink>
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <SearchField
          className="min-w-0 md:max-w-xl"
          label={copy.search}
          placeholder="Number, customer or reference"
          value={text}
          onChange={(value) => {
            setText(value);
            if (value === "" && state.q) router.push(href({ q: "" }));
          }}
          onSubmit={(value) => router.push(href({ q: value }))}
        />
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-3">
          <ChipGroup label="Filter by status">
            <ChipLink href={href({ status: null })} selected={state.status === null} scroll={false}>
              All
            </ChipLink>
            {DOC_STATUSES.map((status) => (
              <ChipLink key={status} href={href({ status })} selected={state.status === status} scroll={false}>
                {documentStatus(status).label}
              </ChipLink>
            ))}
          </ChipGroup>
          <ChipGroup label="Narrow to what is outstanding">
            <ChipLink href={href({ open: !state.open })} selected={state.open} aria-pressed={state.open} icon="circleDot" scroll={false}>
              {credit ? "Still open" : "Still owed"}
            </ChipLink>
            {credit ? null : (
              <ChipLink href={href({ overdue: !state.overdue })} selected={state.overdue} aria-pressed={state.overdue} icon="clock" scroll={false}>
                Overdue
              </ChipLink>
            )}
          </ChipGroup>
        </div>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what={copy.title} onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label={copy.title}
            columns={columns(kind)}
            rows={query.data?.items ?? []}
            rowKey={(doc) => doc.id}
            rowHref={(doc) => asRoute(`${docBase(kind)}/${doc.id}`)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title={`No ${copy.noun} match`}
                  text="Nothing fits this search and these filters."
                  actions={
                    <ButtonLink href={docBase(kind)} variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : credit ? (
                <EmptyState
                  icon="undo"
                  title="No credit notes yet"
                  text="A credit note starts from an issued invoice. Open the invoice and choose Create credit note."
                  actions={
                    <ButtonLink href={asRoute("/finance/invoices?status=issued")} variant="secondary" iconRight="arrowRight">
                      See issued invoices
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="receipt"
                  title="No invoices yet"
                  text="An invoice starts from an issued delivery challan. Deliveries waiting for one are listed on the finance overview."
                  actions={
                    <ButtonLink href="/finance" variant="secondary" iconRight="arrowRight">
                      See deliveries to invoice
                    </ButtonLink>
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun={copy.noun} />
          {total > limit ? (
            <Pagination
              label={`${copy.title} pages`}
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(docHref(kind, { ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
