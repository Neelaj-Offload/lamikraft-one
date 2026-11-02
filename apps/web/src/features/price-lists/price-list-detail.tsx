"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate, LocalDateTime, Money, Quantity } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SearchField } from "@/components/ui/search-field";
import { StatusPill } from "@/components/ui/badge";
import { EmptyState, ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { formatBusinessDate } from "@/lib/format/time";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { fetchPriceList, fetchPriceListItems } from "./api";
import { PRICE_LISTS_PAGE_SIZE, priceListItemsHref, priceListItemsParams, type PriceListItemsState } from "./list-state";
import { PRICE_LIST_ITEM_TONE, PriceListStatusPill, scopeText } from "./price-list-format";
import { PRICES_READ } from "./price-list-list";
import type { PriceListDetail, PriceListItem } from "./types";

/** Which optional columns at least one row on this page carries; absent (redacted) fields never show. */
export function itemColumnPresence(items: readonly PriceListItem[]) {
  const any = (pick: (item: PriceListItem) => unknown) => items.some((item) => pick(item) !== null);
  return {
    finalPrice: any((item) => item.final_price),
    base: any((item) => item.base_price),
    addOn: any((item) => item.addon_price),
    basis: any((item) => item.price_basis),
    yield: any((item) => item.yield_qty_per_board),
    thickness: any((item) => item.thickness_mm),
  };
}

function itemColumns(items: readonly PriceListItem[], locale: string): DataTableColumn<PriceListItem>[] {
  const c = m.priceList.columns;
  const has = itemColumnPresence(items);
  const dash = <span className="text-ink-muted">—</span>;
  const columns: DataTableColumn<PriceListItem>[] = [
    {
      id: "product",
      header: c.product,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (item) => item.product_key,
      cell: (item) => (
        <RacLink href={`/products/${encodeURIComponent(item.product_id)}`} className={`${linkClasses} font-mono`}>
          {item.product_key}
        </RacLink>
      ),
    },
    { id: "sku", header: c.sku, mobile: "key", cell: (item) => item.display_sku ?? dash },
    { id: "price", header: c.unitPrice, numeric: true, mobile: "amount", cell: (item) => <Money value={item.unit_price} maxFractionDigits={4} /> },
    { id: "unit", header: c.unit, cell: (item) => item.unit_code },
  ];
  if (has.finalPrice) columns.push({ id: "final", header: c.finalPrice, numeric: true, cell: (item) => (item.final_price ? <Money value={item.final_price} maxFractionDigits={4} /> : dash) });
  columns.push(
    { id: "moq", header: c.moq, numeric: true, cell: (item) => (item.moq ? <Quantity value={item.moq} /> : dash) },
    { id: "from", header: c.validFrom, cell: (item) => <LocalDate value={item.valid_from} /> },
    { id: "to", header: c.validTo, cell: (item) => (item.valid_to ? <LocalDate value={item.valid_to} /> : <span className="text-ink-muted">{m.priceLists.openEnded}</span>) },
    {
      id: "status",
      header: c.status,
      mobile: "status",
      cell: (item) => <StatusPill tone={PRICE_LIST_ITEM_TONE[item.status] ?? "neutral"}>{m.priceLists.itemStatus[item.status] ?? item.status}</StatusPill>,
    },
  );
  if (has.base) {
    columns.push({
      id: "base",
      header: c.base,
      numeric: true,
      cell: (item) =>
        item.base_price ? (
          <span className="flex flex-col items-end">
            <Money value={item.base_price} maxFractionDigits={4} />
            {item.base_price_label ? <span className="text-xs text-ink-muted">{item.base_price_label}</span> : null}
          </span>
        ) : (
          dash
        ),
    });
  }
  if (has.addOn) {
    columns.push({
      id: "addon",
      header: c.addOn,
      numeric: true,
      cell: (item) =>
        item.addon_price ? (
          <span className="flex flex-col items-end">
            <Money value={item.addon_price} maxFractionDigits={4} />
            {item.addon_price_label ? <span className="text-xs text-ink-muted">{item.addon_price_label}</span> : null}
          </span>
        ) : (
          dash
        ),
    });
  }
  if (has.basis) columns.push({ id: "basis", header: c.basis, cell: (item) => item.price_basis ?? dash });
  if (has.yield) columns.push({ id: "yield", header: c.yield, numeric: true, cell: (item) => (item.yield_qty_per_board ? formatDecimal(item.yield_qty_per_board, { locale }) : dash) });
  if (has.thickness) columns.push({ id: "thickness", header: c.thickness, numeric: true, cell: (item) => (item.thickness_mm ? formatDecimal(item.thickness_mm, { locale, maxFractionDigits: 3 }) : dash) });
  return columns;
}

export function PriceListDetailView({ priceListId, itemsState }: { priceListId: string; itemsState: PriceListItemsState }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRICES_READ);
  const query = useQuery({ queryKey: queryKeys.pricing.priceList(priceListId), queryFn: ({ signal }) => fetchPriceList(priceListId, signal), enabled: allowed });
  useScreenContribution(query.data ? { focus: { type: "pricing.price_list", id: query.data.id, version: query.data.version } } : null);

  if (!allowed) return <PermissionDenied area={m.priceLists.permissionArea} />;
  if (query.isPending) return <Loading label={m.priceList.loading} variant="detail" />;
  if (query.isError) {
    if (query.error instanceof ProblemError && query.error.status === 404) return <NotAvailable />;
    return <ErrorState error={query.error} what={m.priceList.loading} onRetry={() => void query.refetch()} />;
  }
  return <Record list={query.data} itemsState={itemsState} />;
}

export function priceListFacts(list: PriceListDetail, locale: string): KeyValue[] {
  const f = m.priceList.fields;
  const validity = m.priceList.validityText(formatBusinessDate(list.valid_from, locale) ?? list.valid_from, list.valid_to ? (formatBusinessDate(list.valid_to, locale) ?? list.valid_to) : null);
  const items: (KeyValue | null)[] = [
    { term: f.type, description: m.priceLists.types[list.price_type] ?? list.price_type },
    { term: f.scope, description: m.priceLists.scopes[list.scope_kind] ?? list.scope_kind },
    list.party
      ? {
          term: f.party,
          description: (
            <Link href={`/sales/parties/${encodeURIComponent(list.party.id)}`}>
              {list.party.display_name}
              <span className="font-mono text-sm text-ink-muted"> {list.party.party_number}</span>
            </Link>
          ),
        }
      : null,
    list.customer_type ? { term: f.customerType, description: m.priceLists.customerTypes[list.customer_type] ?? list.customer_type } : null,
    { term: f.currency, description: list.currency, mono: true },
    list.default_unit_code ? { term: f.defaultUnit, description: list.default_unit_code } : null,
    { term: f.validity, description: validity },
    list.priority !== null ? { term: f.priority, description: formatCount(list.priority, locale), numeric: true } : null,
    list.price_basis ? { term: f.priceBasis, description: list.price_basis } : null,
    list.source_kind ? { term: f.source, description: [list.source_kind, list.source_ref].filter(Boolean).join(" · ") } : null,
    list.activated_at ? { term: f.activated, description: <LocalDateTime value={list.activated_at} /> } : null,
    list.retired_at ? { term: f.retired, description: <LocalDateTime value={list.retired_at} /> } : null,
    list.notes ? { term: f.notes, description: <span className="whitespace-pre-line">{list.notes}</span> } : null,
  ];
  return items.filter((item): item is KeyValue => item !== null);
}

function Record({ list, itemsState }: { list: PriceListDetail; itemsState: PriceListItemsState }) {
  const router = useRouter();
  const { zone } = useSession();
  const items = useQuery({
    queryKey: queryKeys.pricing.priceListItems(list.id, priceListItemsParams(itemsState)),
    queryFn: ({ signal }) => fetchPriceListItems(list.id, itemsState, signal),
  });
  const go = (next: Partial<PriceListItemsState>) => router.push(priceListItemsHref(list.id, { ...itemsState, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const t = m.priceList;
  const meta = [m.priceLists.types[list.price_type] ?? list.price_type, scopeText(list.scope_kind, list.party, list.customer_type), list.currency];
  const filtered = itemsState.q !== "";

  return (
    <div className="flex flex-col gap-8">
      <RecordHeader
        back={{ href: "/products/price-lists", label: t.back }}
        recordKey={list.code}
        title={list.name}
        status={<PriceListStatusPill status={list.status} />}
        meta={meta.map((part, index) => (
          <span key={part} className="contents">
            {index > 0 ? <MetaDot /> : null}
            <span>{part}</span>
          </span>
        ))}
      />
      <section aria-label={t.facts}>
        <KeyValueGrid items={priceListFacts(list, zone.locale)} />
      </section>
      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-[650] text-ink">{t.items}</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_auto] md:items-end">
          <SearchField label={t.searchItems} placeholder={t.searchItemsPlaceholder} defaultValue={itemsState.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
          <Checkbox isSelected={itemsState.include_history} onChange={(include_history) => go({ include_history })}>
            {t.includeHistory}
          </Checkbox>
        </div>
        {items.isPending ? (
          <Loading label={t.itemsLoading} />
        ) : items.isError ? (
          <ErrorState error={items.error} what={t.itemsWhat} onRetry={() => void items.refetch()} />
        ) : (
          <DataTable
            caption={t.itemsCaption(list.code)}
            hideCaption
            columns={itemColumns(items.data.items, zone.locale)}
            rows={items.data.items}
            rowId={(item) => item.id}
            rowHref={(item) => `/products/${encodeURIComponent(item.product_id)}`}
            empty={<EmptyState title={t.noItemsTitle}>{filtered ? t.noItemsFiltered : t.noItems}</EmptyState>}
            footer={
              <OffsetPagination
                label={t.itemsPages}
                total={items.data.total}
                limit={items.data.limit || PRICE_LISTS_PAGE_SIZE}
                offset={items.data.offset}
                shown={items.data.items.length}
                control={(offset) => ({ href: priceListItemsHref(list.id, { ...itemsState, offset }) })}
              />
            }
          />
        )}
      </section>
    </div>
  );
}
