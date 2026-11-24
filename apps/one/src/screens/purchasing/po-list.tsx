"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchPurchaseOrders, PAGE_SIZE, PO_STATUSES, type PoSummary } from "@/features/procurement/api";
import { poListHref, type PoListState } from "@/features/procurement/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, Money, SearchField, type Column } from "~/ui";
import { poStatus } from "./labels";
import { ListFooter, PurchasingSwitch, stagger, StatusBadge } from "./parts";
import { asRoute } from "./views";

const COLUMNS: Column<PoSummary>[] = [
  {
    key: "number",
    header: "Purchase order",
    primary: true,
    cell: (po) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <Code>{po.po_number}</Code>
        <span className="t-caption text-ink-3">
          Ordered <DateText value={po.order_date} style="business" />
        </span>
      </span>
    ),
  },
  {
    key: "vendor",
    header: "Vendor",
    cell: (po) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-ink" title={po.vendor.display_name}>
          {po.vendor.display_name}
        </span>
        {po.owner.display_name ? <span className="t-caption text-ink-3">Buyer: {po.owner.display_name}</span> : null}
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    cell: (po) => (
      <span className="flex flex-wrap items-center gap-1.5">
        <StatusBadge look={poStatus(po.status)} />
        {po.is_overdue ? (
          <Badge tone="ember" icon="clock">
            Overdue
          </Badge>
        ) : null}
      </span>
    ),
  },
  { key: "expected", header: "Next delivery", cell: (po) => <DateText value={po.next_expected_date} style="business" /> },
  { key: "warehouse", header: "Deliver to", hideOnMobile: true, cell: (po) => <span title={po.warehouse.name}>{po.warehouse.code}</span> },
  { key: "total", header: "Total", numeric: true, cell: (po) => <Money value={{ amount: po.total_amount, currency: po.currency }} className="t-label text-ink" /> },
];

/** Purchase orders: every order to a vendor. Search, status, the overdue filter and the page live in the URL. */
export function PurchaseOrderList({ state }: { state: PoListState }) {
  const router = useRouter();
  const [text, setText] = useState(state.q);
  const query = useQuery({
    queryKey: queryKeys.procurement.orders({ q: state.q, status: state.status, overdue: state.overdue, offset: state.offset }),
    queryFn: ({ signal }) => fetchPurchaseOrders(state, signal),
  });
  const href = (next: Partial<PoListState>) => asRoute(poListHref({ ...state, offset: 0, ...next }));
  const known = PO_STATUSES.find((status) => status === state.status) ?? null;
  const filtered = Boolean(state.q.trim() || known || state.overdue);

  return (
    <Page>
      <PageHeader eyebrow="Purchasing" title="Purchase orders" lead="Every order to a vendor, with the day its next delivery is due. Late ones are flagged." />

      <div className="rise flex min-w-0 flex-col gap-4" style={stagger(1)}>
        <PurchasingSwitch current="orders" />
        <SearchField
          className="min-w-0 md:max-w-xl"
          label="Search purchase orders"
          placeholder="PO number or vendor"
          value={text}
          onChange={(value) => {
            setText(value);
            if (value === "" && state.q) router.push(href({ q: "" }));
          }}
          onSubmit={(value) => router.push(href({ q: value }))}
        />
        <ChipGroup label="Filter purchase orders">
          <ChipLink href={href({ overdue: !state.overdue })} selected={state.overdue} icon="clock" scroll={false}>
            Overdue only
          </ChipLink>
          <ChipLink href={href({ status: null })} selected={known === null} scroll={false}>
            Any status
          </ChipLink>
          {PO_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={known === status} scroll={false}>
              {poStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Purchase orders" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Purchase orders"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(po) => po.id}
            rowHref={(po) => asRoute(po.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No purchase orders match"
                  text="Nothing fits this search and these filters."
                  actions={
                    <ButtonLink href="/operations/purchasing/orders" variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="cart"
                  title="No purchase orders yet"
                  text="A purchase order begins as an approved requisition. Open one and choose Create purchase order."
                  actions={
                    <ButtonLink href={asRoute("/operations/purchasing/requisitions?status=approved")} variant="secondary" iconRight="arrowRight">
                      See approved requisitions
                    </ButtonLink>
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      <ListFooter page={query.data} noun="purchase orders" label="Purchase order pages" pageSize={PAGE_SIZE} hrefFor={(offset) => asRoute(poListHref({ ...state, offset }))} />
    </Page>
  );
}
