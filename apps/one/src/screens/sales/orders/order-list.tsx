"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchOrders, ORDER_STATUSES, ORDERS_PAGE_SIZE, type OrderSummary } from "@/features/orders/api";
import { orderListHref, type OrderListState } from "@/features/orders/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, FULFILMENT_LABEL, orderStatus } from "~/data/sales-deals";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, Money, PageSummary, Pagination, SearchField, type Column, type Tone } from "~/ui";
import { stagger, StatusBadge } from "../quotations/parts";

const FULFILMENT_TONE: Record<string, Tone> = { none: "neutral", partial: "amber", complete: "leaf" };

export function FulfilmentBadge({ state }: { state: string }) {
  return (
    <Badge tone={FULFILMENT_TONE[state] ?? "neutral"} outline={state === "none"} icon={state === "complete" ? "check" : state === "partial" ? "truck" : undefined}>
      {FULFILMENT_LABEL[state] ?? state}
    </Badge>
  );
}

const COLUMNS: Column<OrderSummary>[] = [
  {
    key: "number",
    header: "Order",
    primary: true,
    cell: (order) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <Code>{order.order_number}</Code>
        <span className="t-caption text-ink-3">from {order.quote.quote_number}</span>
      </span>
    ),
  },
  {
    key: "customer",
    header: "Customer",
    cell: (order) => (
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-ink" title={order.party.display_name}>
          {order.party.display_name}
        </span>
        {order.owner.display_name ? <span className="t-caption text-ink-3">Owner: {order.owner.display_name}</span> : null}
      </span>
    ),
  },
  { key: "status", header: "Status", cell: (order) => <StatusBadge look={orderStatus(order.status)} /> },
  { key: "delivery", header: "Delivery", cell: (order) => <FulfilmentBadge state={order.fulfilment_state} /> },
  { key: "total", header: "Total", numeric: true, cell: (order) => <Money value={order.total} className="t-label text-ink" /> },
  { key: "date", header: "Ordered", hideOnMobile: true, cell: (order) => <DateText value={order.order_date} style="business" /> },
];

/** Orders: won quotations in motion. Search, status and page live in the URL. */
export function OrderList({ state }: { state: OrderListState }) {
  const router = useRouter();
  const [text, setText] = useState(state.q);
  const query = useQuery({
    queryKey: queryKeys.orders.list({ q: state.q, status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchOrders(state, signal),
  });
  const href = (next: Partial<OrderListState>) => asRoute(orderListHref({ ...state, offset: 0, ...next }));
  const filtered = Boolean(state.q.trim() || state.status);
  const limit = query.data?.limit || ORDERS_PAGE_SIZE;
  const total = query.data?.total ?? 0;

  return (
    <Page>
      <PageHeader eyebrow="Sales" title="Orders" lead="Won quotations in motion: confirmed, reserved, dispatched, delivered." />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <SearchField
          className="min-w-0 md:max-w-xl"
          label="Search orders"
          placeholder="Order number, quotation number or customer"
          value={text}
          onChange={(value) => {
            setText(value);
            if (value === "" && state.q) router.push(href({ q: "" }));
          }}
          onSubmit={(value) => router.push(href({ q: value }))}
        />
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={state.status === null} scroll={false}>
            All
          </ChipLink>
          {ORDER_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={state.status === status} scroll={false}>
              {orderStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Orders" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Orders"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(order) => order.id}
            rowHref={(order) => asRoute(order.path)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No orders match"
                  text="Nothing fits this search and status."
                  actions={
                    <ButtonLink href="/sales/orders" variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="cart"
                  title="No orders yet"
                  text="An order begins when a won quotation is converted. Open a won quotation and choose Convert to order."
                  actions={
                    <ButtonLink href={asRoute("/sales/quotes?status=won&scope=all")} variant="secondary" iconRight="arrowRight">
                      See won quotations
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
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="orders" />
          {total > limit ? (
            <Pagination
              label="Order pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(orderListHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
