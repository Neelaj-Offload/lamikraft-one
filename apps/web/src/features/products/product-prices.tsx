"use client";

import { useQuery } from "@tanstack/react-query";
import { Link as RacLink } from "react-aria-components";
import { StatusPill } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate, LocalDateTime, Money, Quantity } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { fetchProductCosts, fetchProductPrices } from "@/features/price-lists/api";
import { PRICE_LIST_ITEM_TONE, scopeText } from "@/features/price-lists/price-list-format";
import type { ProductCost, ProductPrice } from "@/features/price-lists/types";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import type { ProductDetail } from "./types";

export const PRICES_READ = "pricing.price.read";
export const COST_READ = "pricing.cost.read";

function priceColumns(): DataTableColumn<ProductPrice>[] {
  const c = m.detail.priceTable.columns;
  return [
    {
      id: "list",
      header: c.list,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => `${row.price_list_code} · ${row.price_list_name}`,
      cell: (row) => (
        <span className="flex flex-col">
          <RacLink href={`/products/price-lists/${encodeURIComponent(row.price_list_id)}`} className={`${linkClasses} font-mono`}>
            {row.price_list_code}
          </RacLink>
          <span className="text-sm text-ink-muted">{row.price_list_name}</span>
        </span>
      ),
    },
    { id: "type", header: c.type, mobile: "key", cell: (row) => m.priceLists.types[row.price_type] ?? row.price_type },
    { id: "scope", header: c.scope, cell: (row) => scopeText(row.scope_kind, row.party, row.customer_type) },
    { id: "price", header: c.unitPrice, numeric: true, mobile: "amount", cell: (row) => <Money value={row.unit_price} maxFractionDigits={4} /> },
    { id: "unit", header: c.unit, cell: (row) => row.unit_code },
    { id: "moq", header: c.moq, numeric: true, cell: (row) => (row.moq ? <Quantity value={row.moq} /> : <span className="text-ink-muted">—</span>) },
    { id: "from", header: c.validFrom, cell: (row) => <LocalDate value={row.valid_from} /> },
    { id: "to", header: c.validTo, cell: (row) => (row.valid_to ? <LocalDate value={row.valid_to} /> : <span className="text-ink-muted">{m.priceLists.openEnded}</span>) },
    {
      id: "status",
      header: c.status,
      mobile: "status",
      cell: (row) => <StatusPill tone={PRICE_LIST_ITEM_TONE[row.status] ?? "neutral"}>{m.priceLists.itemStatus[row.status] ?? row.status}</StatusPill>,
    },
  ];
}

function CostCard({ productId, cost }: { productId: string; cost: ProductCost }) {
  const { permissionKeys, zone } = useSession();
  const canReadCost = permissionKeys.has(COST_READ);
  const history = useQuery({
    queryKey: queryKeys.pricing.productCosts(productId),
    queryFn: ({ signal }) => fetchProductCosts(productId, signal),
    enabled: canReadCost,
  });
  const t = m.detail.priceTable.cost;
  const items: KeyValue[] = [
    { term: t.unitCost, description: cost.unit_cost ? <Money value={cost.unit_cost} maxFractionDigits={4} /> : <span className="text-ink-muted">—</span>, numeric: true },
    { term: m.detail.priceTable.columns.unit, description: cost.unit_code },
    { term: t.effectiveFrom, description: <LocalDate value={cost.effective_from} /> },
    { term: t.recorded, description: <LocalDateTime value={cost.recorded_at} /> },
    { term: t.version, description: formatCount(cost.cost_version, zone.locale), numeric: true },
    { term: t.source, description: cost.source_kind },
  ];
  const earlier = history.data?.items.filter((entry) => entry.id !== cost.id) ?? [];
  return (
    // costing is restricted: the whole card is blacked out in masked screenshots (ai-routing §4.2)
    <div data-restricted="true">
      <SectionCard title={t.title} description={t.description}>
        <KeyValueGrid items={items} columns={3} />
        {cost.cost_components && cost.cost_components.length > 0 ? (
          <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-1 text-sm">
            <dt className="col-span-2 font-semibold text-ink">{t.components}</dt>
            {cost.cost_components.map((component) => (
              <div key={component.label} className="contents">
                <dt className="text-ink-muted">{component.label}</dt>
                <dd className="text-end tabular text-ink">
                  <Money value={{ amount: component.amount, currency: cost.unit_cost?.currency ?? "" }} maxFractionDigits={4} />
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        {canReadCost ? (
          history.isError ? (
            <ErrorState error={history.error} what={t.historyWhat} onRetry={() => void history.refetch()} backToToday={false} compact headingLevel={3} />
          ) : earlier.length > 0 ? (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-ink">{t.history}</h3>
              <ul aria-label={t.historyCaption} className="flex flex-col divide-y text-sm">
                {earlier.map((entry) => (
                  <li key={entry.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
                    <span className="text-ink-muted">
                      <LocalDate value={entry.effective_from} /> · v{formatCount(entry.cost_version, zone.locale)} · {entry.source_kind}
                    </span>
                    <span className="tabular text-ink">
                      {entry.unit_cost ? <Money value={entry.unit_cost} maxFractionDigits={4} /> : "—"}
                      <span className="text-ink-muted"> / {entry.unit_code}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null
        ) : null}
      </SectionCard>
    </div>
  );
}

export function ProductPricesTab({ product }: { product: ProductDetail }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRICES_READ);
  const query = useQuery({
    queryKey: queryKeys.pricing.productPrices(product.id),
    queryFn: ({ signal }) => fetchProductPrices(product.id, signal),
    enabled: allowed,
  });
  const t = m.detail.priceTable;
  if (!allowed) return <PermissionDenied area={t.noPermission} headingLevel={2} />;
  if (query.isPending) return <Loading label={t.loading} />;
  if (query.isError) return <ErrorState error={query.error} what={t.what} onRetry={() => void query.refetch()} />;
  return (
    <div className="flex flex-col gap-8">
      <DataTable
        caption={t.caption}
        hideCaption
        columns={priceColumns()}
        rows={query.data.prices}
        rowId={(row) => row.id}
        rowHref={(row) => `/products/price-lists/${encodeURIComponent(row.price_list_id)}`}
        empty={<EmptyState title={t.emptyTitle}>{t.empty}</EmptyState>}
      />
      {query.data.current_cost ? <CostCard productId={product.id} cost={query.data.current_cost} /> : null}
    </div>
  );
}
