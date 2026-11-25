"use client";

import type { Route } from "next";
import { useFactoryOrders, type FactoryOrderLine } from "~/data/stock-categories";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, DataTable, DateText, EmptyState, GlassPanel, type Column } from "~/ui";
import { StockViews } from "./parts";

const STATUS_LABEL: Record<string, string> = { approved: "Approved", issued: "Ordered", partially_received: "Part received" };

const COLUMNS: Column<FactoryOrderLine>[] = [
  {
    key: "product",
    header: "Product",
    primary: true,
    cell: (l) => (
      <span className="flex min-w-0 flex-col">
        <span className="t-label lk-mono truncate text-ink">{l.product_key}</span>
        <span className="t-caption truncate text-ink-3">{l.product_name}</span>
      </span>
    ),
  },
  { key: "vendor", header: "Factory", cell: (l) => l.vendor_name },
  { key: "po", header: "Order", hideOnMobile: true, cell: (l) => <span className="lk-mono">{l.po_number}</span> },
  { key: "status", header: "Status", cell: (l) => <Badge tone={l.status === "partially_received" ? "amber" : "cobalt"} dot>{STATUS_LABEL[l.status] ?? l.status}</Badge> },
  { key: "expected", header: "Expected", mobileLabel: "Expected", cell: (l) => <DateText value={l.expected_date} /> },
  { key: "outstanding", header: "Still to come", numeric: true, cell: (l) => <span className="lk-tnum">{`${Number(l.outstanding).toLocaleString()} of ${Number(l.quantity).toLocaleString()} ${l.uom_code}`}</span> },
];

/** Work in progress at the factories: finished pieces ordered and not yet received. */
export function FactoryOrders() {
  const query = useFactoryOrders();
  return (
    <Page>
      <PageHeader eyebrow="Operations" title="Factory orders" lead="Finished pieces ordered from the factories and not yet in stock, soonest first." />
      <StockViews current="factory-orders" />
      {query.isError ? (
        <ErrorBlock error={query.error} what="Factory orders" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise">
          <DataTable
            label="Factory orders"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(l) => `${l.purchase_order_id}:${l.product_id}:${l.expected_date}`}
            rowHref={(l) => l.path as Route}
            loading={query.isPending}
            skeletonRows={6}
            empty={<EmptyState icon="factory" title="Nothing on order" text="When a purchase order for finished products is approved, its open lines show here until they are received." />}
          />
        </GlassPanel>
      )}
    </Page>
  );
}
