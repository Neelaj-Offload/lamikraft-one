"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchReceipts, PAGE_SIZE, type GrnSummary } from "@/features/procurement/api";
import { receiptListHref, type ReceiptListState } from "@/features/procurement/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, type Column } from "~/ui";
import { count, receiptStatus } from "./labels";
import { ListFooter, PurchasingSwitch, stagger, StatusBadge } from "./parts";
import { asRoute } from "./views";

const COLUMNS: Column<GrnSummary>[] = [
  {
    key: "number",
    header: "Receipt",
    primary: true,
    cell: (g) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <Code>{g.grn_number}</Code>
        <span className="t-caption text-ink-3">{count(g.line_count, "line", "lines")}</span>
      </span>
    ),
  },
  {
    key: "vendor",
    header: "From",
    cell: (g) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-ink" title={g.vendor.display_name}>
          {g.vendor.display_name}
        </span>
        <span className="t-caption text-ink-3">
          Against <span className="lk-mono">{g.purchase_order.number}</span>
        </span>
      </span>
    ),
  },
  { key: "received", header: "Received", cell: (g) => <DateText value={g.received_on} style="business" /> },
  { key: "warehouse", header: "Into", hideOnMobile: true, cell: (g) => <span title={g.warehouse.name}>{g.warehouse.code}</span> },
  {
    key: "status",
    header: "Status",
    cell: (g) => (
      <span className="flex flex-wrap items-center gap-1.5">
        <StatusBadge look={receiptStatus(g.status)} />
        {g.awaiting_qc > 0 ? (
          <Badge tone="amber" icon="flask">
            {g.awaiting_qc} in QC
          </Badge>
        ) : null}
      </span>
    ),
  },
];

/** Goods receipts: every delivery that arrived against a purchase order. "Waiting for QC" and the page live in the URL. */
export function ReceiptList({ state }: { state: ReceiptListState }) {
  const query = useQuery({
    queryKey: queryKeys.procurement.receipts({ awaitingQc: state.awaitingQc, offset: state.offset }),
    queryFn: ({ signal }) => fetchReceipts(state, signal),
  });
  const href = (next: Partial<ReceiptListState>) => asRoute(receiptListHref({ ...state, offset: 0, ...next }));

  return (
    <Page>
      <PageHeader eyebrow="Purchasing" title="Goods receipts" lead="Every delivery that arrived from a vendor, and the goods still waiting for a quality check." />

      <div className="rise flex min-w-0 flex-col gap-4" style={stagger(1)}>
        <PurchasingSwitch current="receipts" />
        <ChipGroup label="Filter goods receipts">
          <ChipLink href={href({ awaitingQc: false })} selected={!state.awaitingQc} scroll={false}>
            All receipts
          </ChipLink>
          <ChipLink href={href({ awaitingQc: true })} selected={state.awaitingQc} icon="flask" scroll={false}>
            Waiting for QC
          </ChipLink>
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Goods receipts" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Goods receipts"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(g) => g.id}
            rowHref={(g) => asRoute(g.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              state.awaitingQc ? (
                <EmptyState
                  compact
                  icon="checkCircle"
                  title="Nothing is waiting for QC"
                  text="Every received line that needs a quality check has been inspected."
                  actions={
                    <ButtonLink href="/operations/purchasing/receipts" variant="secondary" size="sm">
                      Show all receipts
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="packageOpen"
                  title="No goods received yet"
                  text="Goods are received from a purchase order once it is with the vendor. Open the order and choose Receive goods."
                  actions={
                    <ButtonLink href={asRoute("/operations/purchasing/orders?status=issued")} variant="secondary" iconRight="arrowRight">
                      See orders with vendors
                    </ButtonLink>
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      <ListFooter page={query.data} noun="goods receipts" label="Goods receipt pages" pageSize={PAGE_SIZE} hrefFor={(offset) => asRoute(receiptListHref({ ...state, offset }))} />
    </Page>
  );
}
