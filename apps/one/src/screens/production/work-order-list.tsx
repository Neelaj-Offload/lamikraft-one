"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchWorkOrders, PAGE_SIZE, type WorkOrderSummary } from "@/features/production/api";
import { workOrdersHref, type WorkOrderListState } from "@/features/production/list-state";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, WORK_ORDER_STATUSES, workOrderStatus } from "~/data/production";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { ButtonLink, ChipGroup, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, PageSummary, Pagination, Qty, SearchField, TextLink, type Column } from "~/ui";
import { BlockedBadge, PATHS, ProductionNav, stagger, StatusBadge, useCanOpen } from "./parts";

/** Work orders: what the floor is making. Search, status, "waiting for material" and the page live in the URL. */
export function WorkOrderList({ state }: { state: WorkOrderListState }) {
  const router = useRouter();
  const canOpen = useCanOpen();
  const [text, setText] = useState(state.q);
  const query = useQuery({
    queryKey: queryKeys.production.workOrders({ ...state }),
    queryFn: ({ signal }) => fetchWorkOrders({ q: state.q, status: state.status as WorkOrderSummary["status"] | null, blocked: state.blocked, offset: state.offset }, signal),
  });
  const href = (next: Partial<WorkOrderListState>) => asRoute(workOrdersHref({ ...state, offset: 0, ...next }));
  const filtered = Boolean(state.q.trim() || state.status || state.blocked);
  const canPlan = canOpen(PATHS.newWorkOrder);
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;

  const columns: Column<WorkOrderSummary>[] = [
    {
      key: "number",
      header: "Work order",
      primary: true,
      cell: (order) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <Code>{order.wo_number}</Code>
          <span className="t-caption text-ink-3" title={order.product.name}>
            {order.product.name} · {order.product.product_key}
          </span>
        </span>
      ),
    },
    {
      key: "quantity",
      header: "To make",
      numeric: true,
      cell: (order) => (
        <span className="flex flex-col items-end gap-0.5">
          <Qty value={{ value: order.qty_planned, uom: order.uom_code }} className="t-label text-ink" />
          {isPositiveDecimalStr(order.qty_good) ? (
            <span className="t-caption text-ink-3">
              <Qty value={{ value: order.qty_good, uom: order.uom_code }} /> made
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (order) => (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <StatusBadge look={workOrderStatus(order.status)} />
          {order.is_blocked ? <BlockedBadge size="sm" /> : null}
        </span>
      ),
    },
    { key: "start", header: "Planned start", hideOnMobile: true, cell: (order) => <DateText value={order.planned_start_date} style="business" /> },
    { key: "due", header: "Due", cell: (order) => <DateText value={order.due_date} style="business" /> },
    {
      key: "order",
      header: "For order",
      hideOnMobile: true,
      cell: (order) =>
        order.sales_order ? (
          canOpen(order.sales_order.path) ? (
            <TextLink href={asRoute(order.sales_order.path)}>
              <Code>{order.sales_order.order_number}</Code>
            </TextLink>
          ) : (
            <Code>{order.sales_order.order_number}</Code>
          )
        ) : (
          <span className="t-caption text-ink-3">For stock</span>
        ),
    },
  ];

  return (
    <Page>
      <PageHeader
        eyebrow="Production"
        title="Work orders"
        lead="What the floor is making, and what is held up waiting for material."
        actions={
          canPlan ? (
            <ButtonLink href={asRoute(PATHS.newWorkOrder)} iconLeft="plus">
              Plan work order
            </ButtonLink>
          ) : undefined
        }
      />
      <ProductionNav current="workOrders" />

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(1)}>
        <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center">
          <SearchField
            className="min-w-0 md:w-full md:max-w-xl"
            label="Search work orders"
            placeholder="Work order number, product or order"
            value={text}
            onChange={(value) => {
              setText(value);
              if (value === "" && state.q) router.push(href({ q: "" }));
            }}
            onSubmit={(value) => router.push(href({ q: value }))}
          />
          <ChipGroup label="Filter by material">
            <ChipLink href={href({ blocked: !state.blocked })} selected={state.blocked} icon="alert" scroll={false}>
              Waiting for material
            </ChipLink>
          </ChipGroup>
        </div>
        <ChipGroup label="Filter by status">
          <ChipLink href={href({ status: null })} selected={state.status === null} scroll={false}>
            All
          </ChipLink>
          {WORK_ORDER_STATUSES.map((status) => (
            <ChipLink key={status} href={href({ status })} selected={state.status === status} scroll={false}>
              {workOrderStatus(status).label}
            </ChipLink>
          ))}
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Work orders" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label="Work orders"
            columns={columns}
            rows={query.data?.items ?? []}
            rowKey={(order) => order.id}
            rowHref={(order) => asRoute(`${PATHS.workOrders}/${order.id}`)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No work orders match"
                  text="Nothing fits this search and these filters."
                  actions={
                    <ButtonLink href={asRoute(PATHS.workOrders)} variant="secondary" size="sm">
                      Clear filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="hammer"
                  title="No work orders yet"
                  text="Plan the first one: choose a product with an approved bill of materials and say how many to make."
                  actions={
                    canPlan ? (
                      <ButtonLink href={asRoute(PATHS.newWorkOrder)} variant="secondary" iconLeft="plus">
                        Plan work order
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
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="work orders" />
          {total > limit ? (
            <Pagination
              label="Work order pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(workOrdersHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
