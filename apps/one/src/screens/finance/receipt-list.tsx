"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PAGE_SIZE, type ReceiptSummary } from "@/features/finance/api";
import { receiptHref, type ReceiptListState } from "@/features/finance/list-state";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, METHOD_LABEL, receiptStatus, useFinanceSummary, useReceipts } from "~/data/finance";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Button, ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, Money, PageSummary, Pagination, SearchField, type Column } from "~/ui";
import { stagger, StatusBadge } from "./parts";
import { RecordReceiptDialog } from "./record-receipt-dialog";

const COLUMNS: Column<ReceiptSummary>[] = [
  {
    key: "number",
    header: "Receipt",
    primary: true,
    cell: (receipt) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <Code>{receipt.receipt_number}</Code>
        <span className="t-caption text-ink-3">
          Received <DateText value={receipt.received_on} style="business" />
        </span>
      </span>
    ),
  },
  {
    key: "customer",
    header: "Customer",
    cell: (receipt) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-ink" title={receipt.party.display_name}>
          {receipt.party.display_name}
        </span>
        <span className="t-caption truncate text-ink-3">{[METHOD_LABEL[receipt.method] ?? receipt.method, receipt.reference].filter(Boolean).join(" · ")}</span>
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (receipt) => <StatusBadge look={receiptStatus(receipt.status)} /> },
  { key: "amount", header: "Amount", numeric: true, cell: (receipt) => <Money value={receipt.amount} className="t-label text-ink" /> },
  { key: "allocated", header: "Allocated", numeric: true, hideOnMobile: true, cell: (receipt) => <Money value={receipt.allocated} /> },
  {
    key: "unallocated",
    header: "Still to allocate",
    numeric: true,
    cell: (receipt) => <Money value={receipt.unallocated} className={isPositiveDecimalStr(receipt.unallocated.amount) ? "t-label text-ink" : "text-ink-3"} />,
  },
];

/** Receipts: money received from customers. Search, the unallocated switch and the page live in the URL. */
export function ReceiptList({ state }: { state: ReceiptListState }) {
  const router = useRouter();
  const [text, setText] = useState(state.q);
  const [recording, setRecording] = useState(false);
  const summary = useFinanceSummary();
  const query = useReceipts(state);
  const canRecord = Boolean(summary.data?.capabilities?.record_receipt?.allowed);
  const href = (next: Partial<ReceiptListState>) => asRoute(receiptHref({ ...state, offset: 0, ...next }));
  const filtered = Boolean(state.q.trim() || state.unallocated);
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;

  return (
    <Page>
      <PageHeader
        eyebrow="Finance"
        title="Receipts"
        lead="Money received from customers, and how much of each receipt is matched to an invoice."
        actions={
          canRecord ? (
            <Button iconLeft="plus" onPress={() => setRecording(true)}>
              Record receipt
            </Button>
          ) : null
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <SearchField
          className="min-w-0 md:max-w-xl"
          label="Search receipts"
          placeholder="Number, customer or reference"
          value={text}
          onChange={(value) => {
            setText(value);
            if (value === "" && state.q) router.push(href({ q: "" }));
          }}
          onSubmit={(value) => router.push(href({ q: value }))}
        />
        <ChipGroup label="Filter receipts">
          <ChipLink href={href({ unallocated: false })} selected={!state.unallocated} scroll={false}>
            All
          </ChipLink>
          <ChipLink href={href({ unallocated: true })} selected={state.unallocated} icon="circleDot" scroll={false}>
            Still to allocate
          </ChipLink>
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Receipts" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Receipts"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(receipt) => receipt.id}
            rowHref={(receipt) => asRoute(`/finance/receipts/${receipt.id}`)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No receipts match"
                  text={state.unallocated && !state.q.trim() ? "Every receipt is fully matched to invoices." : "Nothing fits this search and filter."}
                  actions={
                    <ButtonLink href="/finance/receipts" variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="banknote"
                  title="No receipts yet"
                  text="Record a receipt when a customer's money arrives, then allocate it to the invoices it pays."
                  actions={
                    canRecord ? (
                      <Button iconLeft="plus" variant="secondary" onPress={() => setRecording(true)}>
                        Record your first receipt
                      </Button>
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
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="receipts" />
          {total > limit ? (
            <Pagination
              label="Receipt pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(receiptHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}

      {canRecord ? <RecordReceiptDialog isOpen={recording} onClose={() => setRecording(false)} /> : null}
    </Page>
  );
}
