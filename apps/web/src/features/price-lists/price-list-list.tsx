"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { Button } from "@/components/ui/button";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate } from "@/components/ui/format";
import { PageHeader } from "@/components/ui/page-header";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { CreateListDialog } from "@/features/pricing/price-lists";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES, formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { fetchPriceLists } from "./api";
import { PRICE_LISTS_PAGE_SIZE, priceListListHref, priceListListParams, type PriceListListState } from "./list-state";
import { PriceListStatusPill, scopeText } from "./price-list-format";
import { PRICE_LIST_STATUSES, PRICE_SCOPES, PRICE_TYPES, type PriceListSummary } from "./types";

export const PRICES_READ = "pricing.price.read";

export function priceListsAreaNav(currentId?: string) {
  return <AreaNav area="products" label={m.area} leading={[{ id: "products", label: m.nav.products, href: "/products" }]} currentId={currentId} />;
}

function Count({ value }: { value: number }) {
  const { zone } = useSession();
  return <span className="tabular">{formatCount(value, zone.locale)}</span>;
}

export function priceListColumns(): DataTableColumn<PriceListSummary>[] {
  const c = m.priceLists.columns;
  return [
    {
      id: "code",
      header: c.code,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (list) => list.code,
      cell: (list) => (
        <RacLink href={list.path} className={`${linkClasses} font-mono`}>
          {list.code}
        </RacLink>
      ),
    },
    { id: "name", header: c.name, mobile: "key", cell: (list) => list.name },
    { id: "type", header: c.type, cell: (list) => m.priceLists.types[list.price_type] ?? list.price_type },
    { id: "scope", header: c.scope, cell: (list) => scopeText(list.scope_kind, list.party, list.customer_type) },
    { id: "currency", header: c.currency, mobile: "meta", cell: (list) => <span className="font-mono">{list.currency}</span> },
    { id: "from", header: c.validFrom, cell: (list) => <LocalDate value={list.valid_from} /> },
    { id: "to", header: c.validTo, cell: (list) => (list.valid_to ? <LocalDate value={list.valid_to} /> : <span className="text-ink-muted">{m.priceLists.openEnded}</span>) },
    { id: "status", header: c.status, mobile: "status", cell: (list) => <PriceListStatusPill status={list.status} /> },
    { id: "items", header: c.items, numeric: true, mobile: "amount", cell: (list) => <Count value={list.item_count} /> },
    { id: "priority", header: c.priority, numeric: true, cell: (list) => (list.priority === null ? <span className="text-ink-muted">—</span> : <Count value={list.priority} />) },
  ];
}

export function PriceListList({ state }: { state: PriceListListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRICES_READ);
  const canManage = permissionKeys.has("pricing.price_list.manage");
  const [creating, setCreating] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.pricing.priceLists(priceListListParams(state)),
    queryFn: ({ signal }) => fetchPriceLists(state, signal),
    enabled: allowed,
  });
  const go = (next: Partial<PriceListListState>) => router.push(priceListListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const t = m.priceLists;

  useScreenContribution(
    query.data
      ? {
          lists: [
            { key: "price_lists", rows: query.data.items.map((list, index) => ({ type: "pricing.price_list", id: list.id, version: null, ordinal: state.offset + index + 1 })) },
          ],
          filters: { q: state.q, status: state.status ?? "", price_type: state.price_type ?? "", currency: state.currency ?? "", scope_kind: state.scope_kind ?? "" },
        }
      : null,
  );

  if (!allowed) return <PermissionDenied area={t.permissionArea} />;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t.title}
        intro={t.intro}
        nav={priceListsAreaNav()}
        actions={
          canManage ? (
            <Button variant="primary" onPress={() => setCreating(true)}>
              {t.newList}
            </Button>
          ) : undefined
        }
      />
      {canManage ? <CreateListDialog isOpen={creating} onOpenChange={setCreating} /> : null}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))] lg:items-end">
        <SearchField label={t.search} placeholder={t.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={t.statusFilter}
          options={[{ id: "", label: t.anyStatus }, ...PRICE_LIST_STATUSES.map((status) => ({ id: status, label: t.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: PRICE_LIST_STATUSES.find((status) => status === value) ?? null })}
        />
        <Select
          label={t.typeFilter}
          options={[{ id: "", label: t.anyType }, ...PRICE_TYPES.map((type) => ({ id: type, label: t.types[type] ?? type }))]}
          value={state.price_type ?? ""}
          onChange={(value) => go({ price_type: PRICE_TYPES.find((type) => type === value) ?? null })}
        />
        <Select
          label={t.currencyFilter}
          options={[{ id: "", label: t.anyCurrency }, ...CURRENCIES.map((code) => ({ id: code, label: code }))]}
          value={state.currency ?? ""}
          onChange={(value) => go({ currency: CURRENCIES.find((code) => code === value) ?? null })}
        />
        <Select
          label={t.scopeFilter}
          options={[{ id: "", label: t.anyScope }, ...PRICE_SCOPES.map((scope) => ({ id: scope, label: t.scopes[scope] ?? scope }))]}
          value={state.scope_kind ?? ""}
          onChange={(value) => go({ scope_kind: PRICE_SCOPES.find((scope) => scope === value) ?? null })}
        />
      </div>
      {query.isPending ? (
        <Loading label={t.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={t.what} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={t.caption}
          hideCaption
          columns={priceListColumns()}
          rows={query.data.items}
          rowId={(list) => list.id}
          rowHref={(list) => list.path}
          empty={<EmptyState title={t.emptyTitle}>{t.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={t.pages}
              total={query.data.total}
              limit={query.data.limit || PRICE_LISTS_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: priceListListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
