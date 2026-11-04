"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate, Money } from "@/components/ui/format";
import { PageHeader } from "@/components/ui/page-header";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { queryKeys } from "@/lib/api/query-keys";
import { ordersMessages as m } from "@/messages/orders";
import { fetchOrders, ORDER_STATUSES, ORDERS_PAGE_SIZE, type OrderSummary } from "./api";

export const ORDER_TONES: Record<string, Tone> = { draft: "neutral", confirmed: "info", on_hold: "warning", completed: "success", cancelled: "neutral" };

export function OrderStatusPill({ status }: { status: string }) {
  return <StatusPill tone={ORDER_TONES[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

export interface OrderListState {
  q: string;
  status: string | null;
  offset: number;
}

export function orderListStateFrom(params: Record<string, string | string[] | undefined>): OrderListState {
  const one = (k: string) => (Array.isArray(params[k]) ? params[k]?.[0] : params[k]) as string | undefined;
  const offset = Number.parseInt(one("offset") ?? "0", 10);
  return { q: one("q") ?? "", status: ORDER_STATUSES.find((s) => s === one("status")) ?? null, offset: Number.isFinite(offset) && offset > 0 ? offset : 0 };
}

export function orderListHref(state: OrderListState): string {
  const search = new URLSearchParams();
  if (state.q.trim()) search.set("q", state.q.trim());
  if (state.status) search.set("status", state.status);
  if (state.offset) search.set("offset", String(state.offset));
  const text = search.toString();
  return text ? `/sales/orders?${text}` : "/sales/orders";
}

const dash = <span className="text-ink-muted">—</span>;

export function orderColumns(): DataTableColumn<OrderSummary>[] {
  const c = m.list.columns;
  return [
    {
      id: "number",
      header: c.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (o) => `${o.order_number} · ${o.party.display_name}`,
      cell: (o) => (
        <RacLink href={o.path} className={`${linkClasses} font-mono`}>
          {o.order_number}
        </RacLink>
      ),
    },
    { id: "customer", header: c.customer, cell: (o) => o.party.display_name },
    { id: "quote", header: c.quote, mobile: "meta", cell: (o) => <span className="font-mono text-sm">{o.quote.quote_number}</span> },
    { id: "status", header: c.status, mobile: "status", cell: (o) => <OrderStatusPill status={o.status} /> },
    { id: "fulfilment", header: c.fulfilment, cell: (o) => m.fulfilment[o.fulfilment_state] ?? o.fulfilment_state },
    { id: "total", header: c.total, numeric: true, mobile: "amount", cell: (o) => (o.total ? <Money value={o.total} /> : dash) },
    { id: "date", header: c.date, cell: (o) => <LocalDate value={o.order_date} /> },
    { id: "owner", header: c.owner, cell: (o) => o.owner.display_name ?? dash },
  ];
}

export function OrderList({ state }: { state: OrderListState }) {
  const router = useRouter();
  const query = useQuery({
    queryKey: queryKeys.orders.list({ q: state.q, status: state.status, offset: state.offset }),
    queryFn: ({ signal }) => fetchOrders(state, signal),
  });
  const go = (next: Partial<OrderListState>) => router.push(orderListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const filtered = Boolean(state.q.trim() || state.status);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={m.list.title} intro={m.list.intro} nav={<AreaNav area="sales" label={m.area} />} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField label={m.list.search} placeholder={m.list.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={m.list.status}
          options={[{ id: "", label: m.list.anyStatus }, ...ORDER_STATUSES.map((s) => ({ id: s, label: m.status[s] ?? s }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: ORDER_STATUSES.find((s) => s === value) ?? null })}
        />
      </div>
      {query.isPending ? (
        <Loading label={m.list.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.list.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.list.caption}
          hideCaption
          columns={orderColumns()}
          rows={query.data.items}
          rowId={(o) => o.id}
          rowHref={(o) => o.path}
          empty={<EmptyState title={m.list.emptyTitle}>{filtered ? m.list.empty : m.list.emptyStart}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.list.pages}
              total={query.data.total}
              limit={query.data.limit || ORDERS_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: orderListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
