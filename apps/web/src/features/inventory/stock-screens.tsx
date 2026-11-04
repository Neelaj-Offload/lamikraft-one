"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { FactStrip } from "@/components/ui/fact-strip";
import { LocalDateTime, Quantity } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SearchField } from "@/components/ui/search-field";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { inventoryMessages as m } from "@/messages/inventory";
import {
  fetchMovements,
  fetchReservations,
  fetchShortages,
  fetchStock,
  fetchWarehouses,
  PAGE_SIZE,
  releaseReservation,
  type MovementRow,
  type ReservationRow,
  type StockRow,
} from "./api";
import { useCommand } from "./use-command";

export const OPERATIONS_LEADING = [{ id: "operations", label: "Overview", href: "/operations" }] as const;
const dash = <span className="text-ink-muted">—</span>;

function q(value: string | null | undefined, uom: string | null | undefined) {
  return value != null && uom ? <Quantity value={{ value, uom }} /> : dash;
}

/** The inventory sub-navigation: stock, movements, stock takes (reservations is an Operations context route). */
export function InventoryTabs({ current }: { current: "stock" | "movements" | "stockTakes" }) {
  const tabs = [
    { id: "stock", href: "/operations/inventory", label: m.stock.nav.stock },
    { id: "movements", href: "/operations/inventory/movements", label: m.stock.nav.movements },
    { id: "stockTakes", href: "/operations/inventory/stock-takes", label: m.stock.nav.stockTakes },
  ] as const;
  return (
    <nav aria-label={m.stock.title} className="flex flex-wrap gap-4 text-sm">
      {tabs.map((t) => (
        <RacLink key={t.id} href={t.href} aria-current={t.id === current ? "page" : undefined} className={`${linkClasses} ${t.id === current ? "font-semibold" : ""}`}>
          {t.label}
        </RacLink>
      ))}
    </nav>
  );
}

// =====================================================================================================
// /operations/inventory
// =====================================================================================================
export interface StockState {
  q: string;
  warehouse: string | null;
  short: boolean;
  offset: number;
}

export function stockStateFrom(params: Record<string, string | string[] | undefined>): StockState {
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const offset = Number.parseInt(one("offset") ?? "0", 10);
  return { q: one("q") ?? "", warehouse: one("warehouse") ?? null, short: one("short") === "1", offset: Number.isFinite(offset) && offset > 0 ? offset : 0 };
}

export function stockHref(s: StockState): string {
  const search = new URLSearchParams();
  if (s.q.trim()) search.set("q", s.q.trim());
  if (s.warehouse) search.set("warehouse", s.warehouse);
  if (s.short) search.set("short", "1");
  if (s.offset) search.set("offset", String(s.offset));
  const text = search.toString();
  return text ? `/operations/inventory?${text}` : "/operations/inventory";
}

export function stockColumns(): DataTableColumn<StockRow>[] {
  const c = m.stock.columns;
  return [
    {
      id: "product",
      header: c.product,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (r) => `${r.product.product_key} · ${r.warehouse.code}`,
      cell: (r) => (
        <span className="flex flex-col">
          <span className="font-mono">{r.product.product_key}</span>
          <span className="text-xs text-ink-muted">{r.product.name}</span>
        </span>
      ),
    },
    { id: "warehouse", header: c.warehouse, cell: (r) => r.warehouse.code },
    { id: "onHand", header: c.onHand, numeric: true, cell: (r) => q(r.on_hand, r.unit) },
    { id: "reserved", header: c.reserved, numeric: true, cell: (r) => q(r.reserved, r.unit) },
    { id: "available", header: c.available, numeric: true, mobile: "amount", cell: (r) => q(r.available, r.unit) },
    { id: "qc", header: c.qc, numeric: true, cell: (r) => q(r.qc_hold, r.unit) },
    {
      id: "short",
      header: c.short,
      mobile: "status",
      cell: (r) =>
        r.shortage ? (
          <StatusPill tone="warning">{q(r.shortage, r.unit)}</StatusPill>
        ) : r.below_reorder ? (
          <Badge>{m.stock.facts.below}</Badge>
        ) : (
          dash
        ),
    },
  ];
}

export function StockScreen({ state }: { state: StockState }) {
  const router = useRouter();
  const { locale } = useZone();
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal) });
  const query = useQuery({
    queryKey: queryKeys.inventory.stock({ q: state.q, warehouse: state.warehouse, short: state.short, offset: state.offset }),
    queryFn: ({ signal }) => fetchStock({ q: state.q, warehouse_id: state.warehouse, short_only: state.short, offset: state.offset }, signal),
  });
  const go = (next: Partial<StockState>) => router.push(stockHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const filtered = Boolean(state.q || state.warehouse || state.short);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={m.stock.title} intro={m.stock.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <InventoryTabs current="stock" />
      {query.data ? (
        <FactStrip
          label={m.stock.facts.label}
          facts={[
            { label: m.stock.facts.products, value: formatCount(query.data.totals.products, locale), href: stockHref({ ...state, short: false, offset: 0 }) },
            { label: m.stock.facts.short, value: formatCount(query.data.totals.short_products, locale), href: stockHref({ ...state, short: true, offset: 0 }) },
            { label: m.stock.facts.below, value: formatCount(query.data.totals.below_reorder, locale) },
          ]}
        />
      ) : null}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField label={m.stock.search} placeholder={m.stock.searchPlaceholder} defaultValue={state.q} onSubmit={(qText) => go({ q: qText })} onClear={() => go({ q: "" })} />
        <Select
          label={m.stock.warehouse}
          options={[{ id: "", label: m.stock.anyWarehouse }, ...(warehouses.data ?? []).map((wh) => ({ id: wh.id, label: `${wh.code} · ${wh.name}` }))]}
          value={state.warehouse ?? ""}
          onChange={(value) => go({ warehouse: value || null })}
        />
      </div>
      <Checkbox isSelected={state.short} onChange={(short) => go({ short })}>
        {m.stock.shortOnly}
      </Checkbox>
      {query.isPending ? (
        <Loading label={m.stock.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.stock.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.stock.caption}
          hideCaption
          columns={stockColumns()}
          rows={query.data.items}
          rowId={(r) => `${r.product.id}:${r.warehouse.id}`}
          empty={<EmptyState title={m.stock.emptyTitle}>{filtered ? m.stock.empty : m.stock.emptyStart}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.stock.pages}
              total={query.data.total}
              limit={query.data.limit || PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: stockHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}

// =====================================================================================================
// /operations/inventory/movements
// =====================================================================================================
export function movementColumns(): DataTableColumn<MovementRow>[] {
  const c = m.movements.columns;
  return [
    { id: "when", header: c.when, mobile: "meta", cell: (r) => <LocalDateTime value={r.posted_at} /> },
    {
      id: "product",
      header: c.product,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (r) => `${r.product.product_key} · ${r.from_location.code} → ${r.to_location.code}`,
      cell: (r) => (
        <span className="flex flex-col">
          <span className="font-mono">{r.product.product_key}</span>
          {r.lot ? <span className="text-xs text-ink-muted">{r.lot.lot_code}</span> : null}
        </span>
      ),
    },
    { id: "from", header: c.from, cell: (r) => `${r.from_location.code} (${m.locationTypes[r.from_location.location_type] ?? r.from_location.location_type})` },
    { id: "to", header: c.to, cell: (r) => `${r.to_location.code} (${m.locationTypes[r.to_location.location_type] ?? r.to_location.location_type})` },
    { id: "quantity", header: c.quantity, numeric: true, mobile: "amount", cell: (r) => q(r.quantity, r.unit) },
    {
      id: "source",
      header: c.source,
      mobile: "key",
      mobileCell: (r) => `${m.sources[r.source_type] ?? r.source_type} ${r.source_label ?? ""}`,
      cell: (r) => (
        <span className="flex flex-wrap items-center gap-2">
          <span>{m.sources[r.source_type] ?? r.source_type}</span>
          {r.source_path ? (
            <Link href={r.source_path} className="font-mono">
              {r.source_label ?? r.source_id.slice(0, 8)}
            </Link>
          ) : (
            <span className="font-mono">{r.source_label}</span>
          )}
          {r.is_reversal ? <Badge>{m.movements.reversal}</Badge> : null}
        </span>
      ),
    },
  ];
}

export function MovementsScreen({ offset }: { offset: number }) {
  const query = useQuery({ queryKey: queryKeys.inventory.movements({ offset }), queryFn: ({ signal }) => fetchMovements({ offset }, signal) });
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={m.movements.title} intro={m.movements.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <InventoryTabs current="movements" />
      {query.isPending ? (
        <Loading label={m.movements.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.movements.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.movements.caption}
          hideCaption
          columns={movementColumns()}
          rows={query.data.items}
          rowId={(r) => r.id}
          empty={<EmptyState title={m.movements.emptyTitle}>{m.movements.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.movements.pages}
              total={query.data.total}
              limit={query.data.limit || PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(next) => ({ href: next ? `/operations/inventory/movements?offset=${next}` : "/operations/inventory/movements" })}
            />
          }
        />
      )}
    </div>
  );
}

// =====================================================================================================
// /operations/reservations
// =====================================================================================================
export function ReservationsScreen({ status, offset }: { status: string | null; offset: number }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const listKey = useMemo(() => queryKeys.inventory.reservations({ status, offset }), [status, offset]);
  const query = useQuery({ queryKey: listKey, queryFn: ({ signal }) => fetchReservations({ status, offset }, signal) });
  const shortages = useQuery({ queryKey: queryKeys.inventory.shortages(), queryFn: ({ signal }) => fetchShortages(signal) });
  const { run, pending } = useCommand<null>(listKey);
  const r = m.reservations;
  const columns: DataTableColumn<ReservationRow>[] = [
    {
      id: "product",
      header: r.columns.product,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => `${row.product.product_key} · ${row.demand_label ?? ""}`,
      cell: (row) => <span className="font-mono">{row.product.product_key}</span>,
    },
    { id: "warehouse", header: r.columns.warehouse, cell: (row) => row.warehouse.code },
    {
      id: "demand",
      header: r.columns.demand,
      mobile: "key",
      mobileCell: (row) => row.demand_label ?? row.demand_type,
      cell: (row) => (row.demand_path ? <Link href={row.demand_path}>{row.demand_label ?? row.demand_type}</Link> : (row.demand_label ?? row.demand_type)),
    },
    { id: "reserved", header: r.columns.reserved, numeric: true, cell: (row) => q(row.quantity, row.unit) },
    { id: "remaining", header: r.columns.remaining, numeric: true, mobile: "amount", cell: (row) => q(row.remaining, row.unit) },
    { id: "status", header: r.columns.status, mobile: "status", cell: (row) => <StatusPill tone={row.status === "active" ? "info" : "neutral"}>{r.statuses[row.status] ?? row.status}</StatusPill> },
    {
      id: "actions",
      header: r.columns.actions,
      cell: (row) =>
        row.capabilities.release?.allowed && permissionKeys.has("inventory.stock.reserve") ? (
          <Button size="sm" variant="quiet" isPending={pending === row.id} onPress={() => void run(row.id, (k) => releaseReservation(row.id, k), { done: r.released, failed: r.failed })}>
            {r.release}
          </Button>
        ) : null,
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={r.title} intro={r.intro} nav={<AreaNav area="operations" label={m.area} leading={OPERATIONS_LEADING} />} />
      <SectionCard title={r.shortages} description={r.shortagesIntro}>
        {shortages.isPending ? (
          <Loading label={r.loading} />
        ) : shortages.isError ? (
          <ErrorState error={shortages.error} what={r.shortages} onRetry={() => void shortages.refetch()} compact headingLevel={3} backToToday={false} />
        ) : shortages.data.length === 0 ? (
          <p className="text-sm text-ink-muted">{r.shortagesEmpty}</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {shortages.data.map((s) => (
              <li key={s.id} className="flex flex-col gap-1 py-2 text-sm">
                <span>
                  <span className="font-mono">{s.product.product_key}</span> · {s.warehouse.code} · {r.shortBy(`${s.shortfall} ${s.unit ?? ""}`.trim())}
                </span>
                <span className="flex flex-wrap gap-x-3 text-ink-muted">
                  {s.caused_by.map((c) => (c.path ? <Link key={c.id} href={c.path}>{c.label ?? c.type}</Link> : <span key={c.id}>{c.label ?? c.type}</span>))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
      <Select
        label={r.status}
        className="max-w-xs"
        options={[{ id: "", label: "Any" }, ...Object.entries(r.statuses).map(([id, label]) => ({ id, label }))]}
        value={status ?? ""}
        onChange={(value) => router.push((value ? `/operations/reservations?status=${value}` : "/operations/reservations") as Parameters<typeof router.push>[0])}
      />
      {query.isPending ? (
        <Loading label={r.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={r.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={r.caption}
          hideCaption
          columns={columns}
          rows={query.data.items}
          rowId={(row) => row.id}
          empty={<EmptyState title={r.emptyTitle}>{r.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={r.pages}
              total={query.data.total}
              limit={query.data.limit || PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(next) => ({ href: `/operations/reservations?${new URLSearchParams({ ...(status ? { status } : {}), ...(next ? { offset: String(next) } : {}) })}` })}
            />
          }
        />
      )}
    </div>
  );
}
