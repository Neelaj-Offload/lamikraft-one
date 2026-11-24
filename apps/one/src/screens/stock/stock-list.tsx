"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PAGE_SIZE, type StockRow } from "@/features/inventory/api";
import { stockHref, type StockState } from "@/features/inventory/list-state";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, useStock, useWarehouses } from "~/data/stock";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { stagger } from "~/screens/sales/quotations/parts";
import { Badge, ButtonLink, ChipGroup, ChipLink, CountUp, Dash, DataTable, EmptyState, GlassPanel, PageSummary, Pagination, Qty, SearchField, Select, Skeleton, StatRow, StatTile, type Column } from "~/ui";
import { ProductCell, StockViews } from "./parts";

const ALL_WAREHOUSES = "all";

function qty(value: string | null | undefined, unit: string | null | undefined, className?: string) {
  return value != null && unit ? <Qty value={{ value, uom: unit }} className={className} /> : <Dash />;
}

/** What needs a second look on a stock line: a shortage, a low level, units waiting on quality. */
function Watch({ row }: { row: StockRow }) {
  const short = isPositiveDecimalStr(row.shortage);
  const held = isPositiveDecimalStr(row.qc_hold);
  if (!short && !row.below_reorder && !held) return <Dash />;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {short ? (
        <Badge tone="ember" icon="alert" size="sm">
          Short by {qty(row.shortage, row.unit)}
        </Badge>
      ) : null}
      {row.below_reorder ? (
        <Badge tone="amber" size="sm">
          Below reorder level
        </Badge>
      ) : null}
      {held ? (
        <Badge tone="cobalt" size="sm" outline>
          {qty(row.qc_hold, row.unit)} on quality hold
        </Badge>
      ) : null}
    </span>
  );
}

const COLUMNS: Column<StockRow>[] = [
  { key: "product", header: "Product", primary: true, cell: (row) => <ProductCell product={row.product} /> },
  {
    key: "warehouse",
    header: "Warehouse",
    cell: (row) => (
      <span className="lk-mono" title={row.warehouse.name}>
        {row.warehouse.code}
      </span>
    ),
  },
  { key: "onHand", header: "On hand", numeric: true, cell: (row) => qty(row.on_hand, row.unit) },
  { key: "reserved", header: "Reserved", numeric: true, cell: (row) => qty(row.reserved, row.unit) },
  { key: "available", header: "Free to promise", numeric: true, cell: (row) => qty(row.available, row.unit, "t-label text-ink") },
  { key: "watch", header: "Watch", cell: (row) => <Watch row={row} /> },
];

function Figure({ value }: { value: number | undefined }) {
  return value === undefined ? <Skeleton width={44} height={32} /> : <CountUp value={value} />;
}

/** Stock on hand by product and warehouse. Search, warehouse, "short only" and the page live in the URL. */
export function StockList({ state }: { state: StockState }) {
  const router = useRouter();
  const [text, setText] = useState(state.q);
  const warehouses = useWarehouses();
  const query = useStock(state);
  const href = (next: Partial<StockState>) => asRoute(stockHref({ ...state, offset: 0, ...next }));
  const filtered = Boolean(state.q.trim() || state.warehouse || state.short);
  const limit = query.data?.limit || PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const totals = query.data?.totals;
  const warehouseOptions = [
    { value: ALL_WAREHOUSES, label: "All warehouses" },
    ...(warehouses.data ?? []).map((warehouse) => ({ value: warehouse.id, label: warehouse.name, description: warehouse.code })),
  ];

  return (
    <Page>
      <PageHeader eyebrow="Operations" title="Stock" lead="What each warehouse holds, what is promised to orders, and what is still free to promise." />

      <StockViews current="stock" />

      {query.isError ? null : (
        <GlassPanel padding="md" className="rise" style={stagger(1)} aria-label="Stock at a glance" role="group">
          <StatRow>
            <StatTile label="Stock lines" value={<Figure value={totals?.products} />} foot="Products with a stock record" href={href({ short: false })} />
            <StatTile label="Short" value={<Figure value={totals?.short_products} />} foot="Promised beyond what is free" href={href({ short: true })} />
            <StatTile label="Below reorder level" value={<Figure value={totals?.below_reorder} />} foot="Time to buy or make more" />
          </StatRow>
        </GlassPanel>
      )}

      <div className="rise flex min-w-0 flex-col gap-3" style={stagger(2)}>
        <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center">
          <SearchField
            className="min-w-0 md:max-w-xl md:flex-1"
            label="Search stock"
            placeholder="Product key, name or decor"
            value={text}
            onChange={(value) => {
              setText(value);
              if (value === "" && state.q) router.push(href({ q: "" }));
            }}
            onSubmit={(value) => router.push(href({ q: value }))}
          />
          {warehouses.data && warehouses.data.length > 1 ? (
            <Select
              className="min-w-0 md:w-64"
              label="Warehouse"
              hideLabel
              options={warehouseOptions}
              value={state.warehouse ?? ALL_WAREHOUSES}
              onChange={(value) => router.push(href({ warehouse: value === ALL_WAREHOUSES ? null : value }))}
            />
          ) : null}
        </div>
        <ChipGroup label="Filter by shortage">
          <ChipLink href={href({ short: false })} selected={!state.short} scroll={false}>
            All stock
          </ChipLink>
          <ChipLink href={href({ short: true })} selected={state.short} scroll={false} icon="alert">
            Short only
          </ChipLink>
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Stock" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(3)}>
          <DataTable
            label="Stock by product and warehouse"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(row) => `${row.product.id}:${row.warehouse.id}`}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title={state.short && !state.q.trim() && !state.warehouse ? "Nothing is short" : "No stock matches"}
                  text={state.short && !state.q.trim() && !state.warehouse ? "Every order's stock is covered by what the warehouses hold." : "Nothing fits this search and these filters."}
                  actions={
                    <ButtonLink href="/operations/inventory" variant="secondary" size="sm">
                      {state.short && !state.q.trim() && !state.warehouse ? "See all stock" : "Clear filters"}
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="warehouse"
                  title="No stock yet"
                  text="Stock shows here once an opening stock batch is approved, a purchase is received or a challan is posted to a warehouse."
                />
              )
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="stock lines" />
          {total > limit ? (
            <Pagination
              label="Stock pages"
              page={Math.floor(query.data.offset / limit) + 1}
              pages={Math.ceil(total / limit)}
              hrefFor={(page) => asRoute(stockHref({ ...state, offset: (page - 1) * limit }))}
            />
          ) : null}
        </div>
      ) : null}
    </Page>
  );
}
