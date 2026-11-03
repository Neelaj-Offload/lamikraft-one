"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { FactStrip, type Fact } from "@/components/ui/fact-strip";
import { RelativeTime } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { swatchForDecor } from "@/features/material-viewer/swatches";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES, formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { fetchProducts, fetchProductStats, productExportHref } from "./api";
import {
  activeFilterCount,
  clearedFiltersHref,
  effectiveSort,
  productListHref,
  productListParams,
  PRODUCTS_PAGE_SIZE,
  type ProductListState,
} from "./list-state";
import { FacetColumn, FiltersDrawerButton, useProductFacets } from "./product-facets";
import { PriceColumnCell, priceColumnFor, ProductStatusPill, SizeCell } from "./product-format";
import { PRODUCT_SORTS, type ProductStats, type ProductSummary } from "./types";

export const PRODUCTS_READ = "catalogue.product.read";

export function productsAreaNav(currentId?: string) {
  return <AreaNav area="products" label={m.area} leading={[{ id: "products", label: m.nav.products, href: "/products" }]} currentId={currentId} />;
}

function DecorCell({ product }: { product: ProductSummary }) {
  if (!product.decor_no && !product.decor_name) return <span className="text-ink-muted">—</span>;
  const swatch = swatchForDecor(product.decor_no, product.decor_name, product.product_name);
  return (
    <span className="inline-flex items-center gap-2">
      {swatch ? (
        // eslint-disable-next-line @next/next/no-img-element -- a 24 px fixture swatch from /public, not an optimised photo
        <img aria-hidden="true" alt="" src={swatch.thumb} width={24} height={24} className="size-6 shrink-0 rounded-xs object-cover" />
      ) : null}
      <span>
        {product.decor_no ? <span className="font-mono text-sm">{product.decor_no}</span> : null}
        {product.decor_no && product.decor_name ? " " : null}
        {product.decor_name}
      </span>
    </span>
  );
}

export function productColumns(currency: string, showPrices: boolean): DataTableColumn<ProductSummary>[] {
  const columns: DataTableColumn<ProductSummary>[] = [
    {
      id: "key",
      header: m.list.columns.key,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (product) => product.product_key,
      cell: (product) => (
        <RacLink href={product.path} className={`${linkClasses} font-mono`}>
          {product.product_key}
        </RacLink>
      ),
    },
    { id: "name", header: m.list.columns.name, mobile: "key", cell: (product) => product.product_name },
    {
      id: "category",
      header: m.list.columns.category,
      cell: (product) => (
        <span>
          {product.category.name}
          {product.subcategory ? <span className="text-ink-muted"> › {product.subcategory.name}</span> : null}
        </span>
      ),
    },
    { id: "decor", header: m.list.columns.decor, cell: (product) => <DecorCell product={product} /> },
    { id: "size", header: m.list.columns.size, cell: (product) => <SizeCell size={product.size} thicknessMm={product.thickness_mm} /> },
    { id: "status", header: m.list.columns.status, mobile: "status", cell: (product) => <ProductStatusPill status={product.status} /> },
    {
      id: "carton",
      header: m.list.columns.cartonQty,
      numeric: true,
      cell: (product) => (product.carton_qty === null ? <span className="text-ink-muted">—</span> : <CartonQty value={product.carton_qty} />),
    },
  ];
  if (showPrices) {
    columns.push({
      id: "price",
      header: m.list.columns.price(currency),
      numeric: true,
      mobile: "amount",
      cell: (product) => <PriceColumnCell column={priceColumnFor(product.prices, currency)} />,
    });
  }
  columns.push({ id: "updated", header: m.list.columns.updated, mobile: "meta", cell: (product) => <RelativeTime value={product.updated_at} className="text-ink-muted" /> });
  return columns;
}

function CartonQty({ value }: { value: number }) {
  const { zone } = useSession();
  return <span className="tabular">{formatCount(value, zone.locale)}</span>;
}

/** The catalogue figures as one line of facts; only keys the server returned. */
export function statsFacts(stats: ProductStats, locale: string): Fact[] {
  const count = (value: number) => formatCount(value, locale);
  const facts: Fact[] = [{ label: m.list.facts.total, value: count(stats.total), href: "/products" }];
  if ("active" in stats.by_status) facts.push({ label: m.list.facts.active, value: count(stats.by_status.active!), href: productListHref({ status: "active" }) });
  if ("under_development" in stats.by_status) {
    facts.push({ label: m.list.facts.underDevelopment, value: count(stats.by_status.under_development!), href: productListHref({ status: "under_development" }) });
  }
  facts.push({ label: m.list.facts.updatedWeek, value: count(stats.updated_last_7_days), href: productListHref({ sort: "-updated_at" }) });
  facts.push({ label: m.list.facts.archived, value: count(stats.archived), href: productListHref({ include_archived: true }) });
  return facts;
}

function StatsStrip() {
  const { zone } = useSession();
  const stats = useQuery({ queryKey: queryKeys.catalogue.stats(), queryFn: ({ signal }) => fetchProductStats(signal) });
  if (!stats.data) return null;
  return <FactStrip label={m.list.facts.label} facts={statsFacts(stats.data, zone.locale)} />;
}

export function ProductList({ state }: { state: ProductListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const canCreate = permissionKeys.has("catalogue.product.create");
  const canExport = permissionKeys.has("catalogue.product.export");
  const query = useQuery({
    queryKey: queryKeys.catalogue.products(productListParams(state)),
    queryFn: ({ signal }) => fetchProducts(state, signal),
    enabled: allowed,
  });
  const facets = useProductFacets(state);
  const go = (next: Partial<ProductListState>) => router.push(productListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);

  useScreenContribution(
    query.data
      ? {
          lists: [
            {
              key: "products",
              rows: query.data.items.map((product, index) => ({ type: "catalogue.product", id: product.id, version: null, ordinal: state.offset + index + 1 })),
            },
          ],
          filters: {
            q: state.q,
            category_id: state.category_id ?? "",
            subcategory_id: state.subcategory_id ?? "",
            family: state.family ?? "",
            size: state.size ?? "",
            thickness: state.thickness ?? "",
            decor: state.decor ?? "",
            finish: state.finish ?? "",
            status: state.status ?? "",
            brand: state.brand ?? "",
            issue: state.issue ?? "",
            include_archived: state.include_archived,
            currency: state.currency,
          },
        }
      : null,
  );

  if (!allowed) return <PermissionDenied area={m.list.title.toLowerCase()} />;

  const sort = effectiveSort(state);
  const sortOptions = PRODUCT_SORTS.filter((option) => option !== "relevance" || state.q).map((option) => ({ id: option, label: m.list.sorts[option] ?? option }));
  const showPrices = query.data?.items.some((product) => product.prices !== null) ?? false;
  const filtered = activeFilterCount(state) > 0;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={m.list.title}
        intro={m.list.intro}
        nav={productsAreaNav()}
        actions={
          canCreate || canExport ? (
            <>
              {canExport ? (
                <LinkButton href={productExportHref(state)} download>
                  {m.list.exportCsv}
                </LinkButton>
              ) : null}
              {canCreate ? (
                <LinkButton href="/products/new" variant="primary">
                  {m.list.addProduct}
                </LinkButton>
              ) : null}
            </>
          ) : undefined
        }
      />
      <StatsStrip />
      <div className="lg:grid lg:grid-cols-[260px_minmax(0,1fr)] lg:gap-8">
        <aside aria-label={m.list.filters} className="hidden lg:block">
          <FacetColumn state={state} facets={facets} />
        </aside>
        <div className="flex min-w-0 flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] md:items-end">
            <SearchField
              label={m.list.search}
              placeholder={m.list.searchPlaceholder}
              defaultValue={state.q}
              onSubmit={(q) => go({ q })}
              onClear={() => go({ q: "" })}
            />
            <Select
              label={m.list.sort}
              options={sortOptions}
              value={sort}
              onChange={(value) => go({ sort: PRODUCT_SORTS.find((option) => option === value) ?? null })}
            />
            <Select
              label={m.list.currency}
              options={CURRENCIES.map((code) => ({ id: code, label: code }))}
              value={state.currency}
              onChange={(value) => go({ currency: CURRENCIES.find((code) => code === value) ?? state.currency })}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Checkbox isSelected={state.include_archived} onChange={(include_archived) => go({ include_archived })}>
              {m.list.includeArchived}
            </Checkbox>
            <FiltersDrawerButton state={state} facets={facets} />
          </div>
          {query.isPending ? (
            <Loading label={m.list.loading} />
          ) : query.isError ? (
            <ErrorState error={query.error} what={m.list.what} onRetry={() => void query.refetch()} />
          ) : (
            <DataTable
              caption={m.list.caption}
              hideCaption
              columns={productColumns(state.currency, showPrices)}
              rows={query.data.items}
              rowId={(product) => product.id}
              rowHref={(product) => product.path}
              empty={
                <EmptyState
                  title={m.list.emptyTitle}
                  action={filtered ? <LinkButton href={clearedFiltersHref(state)}>{m.list.clearFilters}</LinkButton> : undefined}
                >
                  {filtered ? m.list.empty : m.list.emptyNoFilters}
                </EmptyState>
              }
              footer={
                <OffsetPagination
                  label={m.list.pages}
                  total={query.data.total}
                  limit={query.data.limit || PRODUCTS_PAGE_SIZE}
                  offset={query.data.offset}
                  shown={query.data.items.length}
                  control={(offset) => ({ href: productListHref({ ...state, offset }) })}
                />
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
