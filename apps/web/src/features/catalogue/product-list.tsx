"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { Link, LinkButton } from "@/components/ui/link";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { queryKeys } from "@/lib/api/query-keys";
import { cx } from "@/lib/cx";
import { useSession } from "@/lib/session/context";
import { fetchFacets, fetchProducts, fetchStats, productExportHref } from "./api";
import {
  PAGE_SIZES,
  productFilterQuery,
  productListHref,
  productListQuery,
  type PageSize,
  type ProductListState,
  type ProductSort,
} from "./list-state";
import { PRODUCT_STATUSES, type FacetValue, type ProductSize, type ProductStatus, type ProductSummary } from "./types";

export const STATUS_LABEL: Record<ProductStatus, string> = {
  active: "Active",
  inactive: "Inactive",
  under_development: "Under development",
};
const STATUS_TONE: Record<ProductStatus, Tone> = { active: "success", inactive: "neutral", under_development: "warning" };

export function ProductStatusPill({ status, archived = false }: { status: ProductStatus; archived?: boolean }) {
  if (archived) return <StatusPill tone="neutral">Archived</StatusPill>;
  return <StatusPill tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</StatusPill>;
}

export function sizeText(size: ProductSize): string | null {
  if (size.diameter_mm) return `Ø ${size.diameter_mm} mm`;
  if (!size.length_mm || !size.width_mm) return null;
  return `${size.length_mm} × ${size.width_mm}${size.height_mm ? ` × ${size.height_mm}` : ""} mm`;
}

const dash = <span className="text-ink-muted">—</span>;

export function productColumns(): DataTableColumn<ProductSummary>[] {
  return [
    {
      id: "image",
      header: "Image",
      cell: (p) =>
        p.primary_image ? (
          // eslint-disable-next-line @next/next/no-img-element -- same-origin authenticated original (no variants yet)
          <img src={p.primary_image.url} alt={p.primary_image.alt_text ?? ""} className="size-10 rounded-sm border object-cover" loading="lazy" />
        ) : (
          <span className="block size-10 rounded-sm border bg-surface-sunken" aria-hidden="true" />
        ),
    },
    {
      id: "key",
      header: "Product key",
      isRowHeader: true,
      mobile: "title",
      mobileCell: (p) => p.product_key,
      cell: (p) => (
        <RacLink href={p.path} className={cx(linkClasses, "font-mono")}>
          {p.product_key}
        </RacLink>
      ),
    },
    { id: "name", header: "Name", mobile: "key", cell: (p) => p.product_name },
    {
      id: "category",
      header: "Category",
      cell: (p) => (p.subcategory ? `${p.category.name} › ${p.subcategory.name}` : p.category.name),
    },
    { id: "decor", header: "Decor", cell: (p) => (p.decor_no ? <span className="font-mono">{p.decor_no}</span> : dash) },
    { id: "size", header: "Size", mobile: "meta", cell: (p) => sizeText(p.size) ?? dash },
    { id: "thickness", header: "Thickness", numeric: true, cell: (p) => (p.thickness_mm ? `${p.thickness_mm} mm` : dash) },
    { id: "carton", header: "Carton", numeric: true, cell: (p) => (p.carton_qty === null ? dash : String(p.carton_qty)) },
    { id: "status", header: "Status", mobile: "status", cell: (p) => <ProductStatusPill status={p.status} archived={p.archived} /> },
  ];
}

function facetOptions(values: readonly FacetValue[] | undefined, any: string) {
  return [{ id: "", label: any }, ...(values ?? []).map((v) => ({ id: v.value, label: v.label, detail: String(v.count) }))];
}

/** Products home and catalogue (LM-10/14, UI-13/27/32/34/36): summary figures, category chips, URL filters,
 * server pagination with real totals, a phone card list and the export link. */
export function ProductCatalogue({ state }: { state: ProductListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const params = productListQuery(state);
  const products = useQuery({ queryKey: queryKeys.catalogue.products(params), queryFn: ({ signal }) => fetchProducts(state, signal) });
  const filterParams = productFilterQuery(state);
  const facets = useQuery({ queryKey: queryKeys.catalogue.facets(filterParams), queryFn: ({ signal }) => fetchFacets(state, signal) });
  const stats = useQuery({ queryKey: queryKeys.catalogue.stats(), queryFn: ({ signal }) => fetchStats(signal) });
  const go = (next: Partial<ProductListState>) =>
    router.push(productListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const canCreate = permissionKeys.has("catalogue.product.create");
  const canExport = permissionKeys.has("catalogue.product.export");
  const canTaxonomy = permissionKeys.has("catalogue.taxonomy.manage");

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">Products</h1>
          {stats.data ? (
            <p className="text-sm text-ink-muted tabular" aria-label="Catalogue summary">
              {stats.data.total} live products · {stats.data.by_status.active ?? 0} active · {stats.data.updated_last_7_days} updated in 7 days
              {stats.data.without_active_price !== null ? ` · ${stats.data.without_active_price} without a current price` : ""}
              {stats.data.archived ? ` · ${stats.data.archived} archived` : ""}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton href="/products/completeness" variant="quiet">
            Completeness
          </LinkButton>
          {canTaxonomy ? (
            <LinkButton href="/products/taxonomy" variant="quiet">
              Taxonomy
            </LinkButton>
          ) : null}
          {canExport ? (
            <LinkButton href={productExportHref(state)} download>
              Export CSV
            </LinkButton>
          ) : null}
          {canCreate ? (
            <LinkButton href="/products/new" variant="primary">
              Add product
            </LinkButton>
          ) : null}
        </div>
      </header>

      {stats.data && stats.data.by_category.length ? (
        <nav aria-label="Categories" className="flex flex-wrap gap-2">
          {stats.data.by_category.slice(0, 8).map((c) => (
            <Link
              key={c.category_id}
              href={productListHref({ ...state, offset: 0, category: state.category === c.category_id ? null : c.category_id, subcategory: null })}
              aria-current={state.category === c.category_id ? "true" : undefined}
              className={cx(
                "rounded-sm border px-2.5 py-1 text-sm no-underline",
                state.category === c.category_id ? "border-forest bg-forest-tint font-semibold text-ink" : "text-ink-muted",
              )}
            >
              {c.name} <span className="tabular">{c.count}</span>
            </Link>
          ))}
        </nav>
      ) : null}

      <section aria-label="Filters" className="grid grid-cols-1 gap-4 md:grid-cols-3 lg:grid-cols-6 lg:items-end">
        <SearchField
          label="Search"
          placeholder="Key, SKU, name, decor, finish"
          defaultValue={state.q}
          onSubmit={(q) => go({ q, sort: q.trim() ? "relevance" : state.sort })}
          onClear={() => go({ q: "" })}
          className="md:col-span-3 lg:col-span-2"
        />
        <Select
          label="Status"
          options={[{ id: "", label: "Any status" }, ...PRODUCT_STATUSES.map((s) => ({ id: s, label: STATUS_LABEL[s] }))]}
          value={state.status ?? ""}
          onChange={(v) => go({ status: PRODUCT_STATUSES.find((s) => s === v) ?? null })}
        />
        <Select
          label="Subcategory"
          options={facetOptions(facets.data?.subcategories, "Any subcategory")}
          value={state.subcategory ?? ""}
          onChange={(v) => go({ subcategory: v || null })}
        />
        <Select
          label="Thickness"
          options={facetOptions(facets.data?.thicknesses, "Any thickness")}
          value={state.thickness}
          onChange={(v) => go({ thickness: v ?? "" })}
        />
        <Select
          label="Finish"
          options={facetOptions(facets.data?.finishes, "Any finish")}
          value={state.finish}
          onChange={(v) => go({ finish: v ?? "" })}
        />
        <Select
          label="Size"
          options={facetOptions(facets.data?.sizes, "Any size")}
          value={state.size}
          onChange={(v) => go({ size: v ?? "" })}
        />
        <Select
          label="Decor"
          options={facetOptions(facets.data?.decors, "Any decor")}
          value={state.decor}
          onChange={(v) => go({ decor: v ?? "" })}
        />
        <Select
          label="Image"
          options={[
            { id: "", label: "With or without" },
            { id: "true", label: "Has an image" },
            { id: "false", label: "No image" },
          ]}
          value={state.hasImage === null ? "" : String(state.hasImage)}
          onChange={(v) => go({ hasImage: v === "true" ? true : v === "false" ? false : null })}
        />
        <Select
          label="Sort"
          options={[
            { id: "product_key", label: "Product key" },
            { id: "product_name", label: "Name" },
            { id: "-updated_at", label: "Recently changed" },
            ...(state.q.trim() ? [{ id: "relevance", label: "Best match" }] : []),
          ]}
          value={state.sort}
          onChange={(v) => go({ sort: (v as ProductSort) || "product_key" })}
        />
        <Select
          label="Per page"
          options={PAGE_SIZES.map((n) => ({ id: String(n), label: String(n) }))}
          value={String(state.limit)}
          onChange={(v) => go({ limit: (PAGE_SIZES.find((n) => String(n) === v) ?? 25) as PageSize })}
        />
        {state.issue ? (
          <p className="text-sm lg:col-span-2">
            Showing products with the issue <span className="font-mono">{state.issue}</span>.{" "}
            <Link href={productListHref({ ...state, issue: "", offset: 0 })}>Clear</Link>
          </p>
        ) : null}
      </section>

      {products.isPending ? (
        <Loading label="products" />
      ) : products.isError ? (
        <ErrorState error={products.error} what="the products" onRetry={() => void products.refetch()} />
      ) : (
        <DataTable
          caption="Products"
          hideCaption
          columns={productColumns()}
          rows={products.data.items}
          rowId={(p) => p.id}
          rowHref={(p) => p.path}
          empty={
            <EmptyState title="No products match">
              {state.q || state.category || state.status ? "Change or clear the filters." : "Add a product or import the catalogue."}
            </EmptyState>
          }
          footer={
            <OffsetPagination
              label="Product pages"
              total={products.data.total}
              limit={products.data.limit || state.limit}
              offset={products.data.offset}
              shown={products.data.items.length}
              control={(offset) => ({ href: productListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
