"use client";

import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { productExportHref } from "@/features/products/api";
import { activeFilterCount, effectiveSort, PRODUCTS_PAGE_SIZE, type ProductListState } from "@/features/products/list-state";
import { PRODUCT_SORTS } from "@/features/products/types";
import { CURRENCIES, formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import {
  PRICES_READ,
  PRODUCTS_CREATE,
  PRODUCTS_EXPORT,
  PRODUCTS_READ,
  useCatalogue,
  useCatalogueFacets,
  useCatalogueStats,
  useCompleteness,
  type CatalogueProduct,
} from "~/data/products";
import { riseStyle } from "./motion";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import {
  Badge,
  Banner,
  ButtonLink,
  Code,
  CountUp,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Icon,
  MediaCell,
  PageSummary,
  Pagination,
  SearchField,
  SegmentedLinks,
  Select,
  Skeleton,
  StatRow,
  StatTile,
  type Column,
} from "~/ui";
import { ActiveFilters, CategoryChips, FiltersButton } from "./catalogue-filters";
import { priceColumnFor, ProductStatusBadge, SizeText, StandardPrice } from "./format";
import { catalogueHref, productViewHref, type CatalogueLayout } from "./links";
import { decorSwatch } from "./swatch";

const SORT_LABEL: Record<string, string> = {
  relevance: "Best match first",
  product_key: "By code",
  product_name: "By name",
  "-updated_at": "Recently updated",
};

function imageFor(product: CatalogueProduct): { src: string; thumb: string; own: boolean } | null {
  if (product.primary_image) return { src: product.primary_image.url, thumb: product.primary_image.url, own: true };
  const swatch = decorSwatch(product.decor_no, product.decor_name, product.product_name);
  return swatch ? { src: swatch.albedo, thumb: swatch.thumb, own: false } : null;
}

function decorText(product: CatalogueProduct): string | null {
  const text = [product.decor_no, product.decor_name].filter(Boolean).join(" ");
  return text || null;
}

/** The numbers that describe the catalogue; each one opens the list it counts. */
function CatalogueStats({ layout }: { layout: CatalogueLayout }) {
  const stats = useCatalogueStats();
  if (stats.isPending) {
    return (
      <StatRow>
        {[0, 1, 2, 3].map((index) => (
          <GlassPanel key={index} className="flex flex-col gap-3">
            <Skeleton width="45%" />
            <Skeleton width="30%" height={32} />
          </GlassPanel>
        ))}
      </StatRow>
    );
  }
  if (!stats.data) return null;
  const tiles: { label: string; value: number; href: Route; foot?: string }[] = [
    { label: "Products", value: stats.data.total, href: catalogueHref({}, layout), foot: "In the catalogue today" },
  ];
  if ("active" in stats.data.by_status) {
    tiles.push({ label: "Active", value: stats.data.by_status.active ?? 0, href: catalogueHref({ status: "active" }, layout), foot: "Ready to quote" });
  }
  if ("under_development" in stats.data.by_status) {
    tiles.push({
      label: "In development",
      value: stats.data.by_status.under_development ?? 0,
      href: catalogueHref({ status: "under_development" }, layout),
      foot: "Not yet for sale",
    });
  }
  tiles.push({ label: "Updated this week", value: stats.data.updated_last_7_days, href: catalogueHref({ sort: "-updated_at" }, layout), foot: "Newest changes first" });
  return (
    <StatRow>
      {tiles.map((tile, index) => (
        <GlassPanel key={tile.label} interactive className="rise" style={riseStyle(index)}>
          <StatTile label={tile.label} value={<CountUp value={tile.value} />} foot={tile.foot} href={tile.href} />
        </GlassPanel>
      ))}
    </StatRow>
  );
}

/** One line that sends the person to the work queue when products have gaps. */
function GapsNotice() {
  const { zone } = useSession();
  const completeness = useCompleteness();
  if (!completeness.data) return null;
  const gaps = completeness.data.total_products - completeness.data.complete_products;
  if (gaps <= 0) return null;
  return (
    <Banner
      tone="amber"
      title={`${formatCount(gaps, zone.locale)} ${gaps === 1 ? "product has" : "products have"} details missing.`}
      action={
        <ButtonLink href="/products/completeness" variant="secondary" size="sm" iconRight="arrowRight">
          See what is missing
        </ButtonLink>
      }
    >
      A product with gaps quotes slowly and packs wrong. The completeness screen lists each gap and the products behind it.
    </Banner>
  );
}

function ProductCard({ product, currency, showPrices, index }: { product: CatalogueProduct; currency: string; showPrices: boolean; index: number }) {
  const { zone } = useSession();
  const image = imageFor(product);
  const decor = decorText(product);
  const quiet = product.archived || product.status !== "active";
  return (
    <GlassPanel as="article" padding="none" interactive className="rise-plain relative flex flex-col overflow-hidden" style={riseStyle(index)}>
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-sand-soft">
        {image ? (
          // Decor swatches are build assets and product photos come from the API; neither needs the image optimiser.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={image.src} alt="" loading="lazy" decoding="async" className={`h-full w-full ${image.own ? "object-contain" : "object-cover"}`} />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-ink-3">
            <Icon name="image" size={28} />
            <span className="t-caption">No photo yet</span>
          </div>
        )}
        {quiet ? (
          <div className="absolute left-3 top-3 flex flex-wrap gap-2">
            {product.archived ? (
              <span className="rounded-pill bg-surface">
                <Badge size="sm" icon="archive">
                  Archived
                </Badge>
              </span>
            ) : (
              <span className="rounded-pill bg-surface">
                <ProductStatusBadge status={product.status} size="sm" />
              </span>
            )}
          </div>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="t-code-sm lk-mono text-ink-3">{product.product_key}</p>
          <h3 className="t-h4">
            <Link href={productViewHref(product.id, "summary")} className="stretched text-ink no-underline">
              {product.product_name}
            </Link>
          </h3>
          <p className="t-body-sm truncate text-ink-2" title={decor ?? product.category.name}>
            {decor ?? product.category.name}
          </p>
        </div>
        <dl className="hairline-top mt-auto grid grid-cols-2 gap-3 pt-4">
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="t-caption text-ink-3">Size, mm</dt>
            <dd className="t-label m-0 text-ink">
              <SizeText size={product.size} thicknessMm={product.thickness_mm} />
            </dd>
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="t-caption text-ink-3">{showPrices ? `Price, ${currency}` : "Per carton"}</dt>
            <dd className="t-label m-0 text-ink">
              {showPrices ? (
                <StandardPrice column={priceColumnFor(product.prices, currency)} />
              ) : product.carton_qty === null ? (
                <span className="text-ink-3">Not set</span>
              ) : (
                <span className="lk-tnum">{formatCount(product.carton_qty, zone.locale)}</span>
              )}
            </dd>
          </div>
        </dl>
      </div>
    </GlassPanel>
  );
}

function GridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" role="status" aria-label="Loading products">
      {Array.from({ length: 8 }, (_, index) => (
        <GlassPanel key={index} padding="none" className="overflow-hidden">
          <Skeleton height="auto" className="aspect-[4/3]" style={{ borderRadius: 0 }} />
          <div className="flex flex-col gap-3 p-5">
            <Skeleton width="35%" />
            <Skeleton width="80%" height={16} />
            <Skeleton width="55%" />
          </div>
        </GlassPanel>
      ))}
    </div>
  );
}

function tableColumns(state: ProductListState, showPrices: boolean, locale: string): Column<CatalogueProduct>[] {
  const columns: Column<CatalogueProduct>[] = [
    {
      key: "product",
      header: "Product",
      primary: true,
      cell: (product) => {
        const image = imageFor(product);
        return (
          <MediaCell
            src={image?.thumb}
            icon="box"
            title={product.product_name}
            subtitle={
              <>
                <span className="lk-mono">{product.product_key}</span> · {product.subcategory ? `${product.category.name}, ${product.subcategory.name}` : product.category.name}
              </>
            }
          />
        );
      },
    },
    {
      key: "decor",
      header: "Decor",
      hideOnMobile: true,
      cell: (product) =>
        product.decor_no || product.decor_name ? (
          <span>
            {product.decor_no ? <Code>{product.decor_no}</Code> : null} {product.decor_name}
          </span>
        ) : (
          <span className="text-ink-3">None</span>
        ),
    },
    { key: "size", header: "Size, mm", mobileLabel: "Size, mm", cell: (product) => <SizeText size={product.size} thicknessMm={product.thickness_mm} /> },
    // The fifth column follows the sort: carton quantity by default, the date when the list is ordered by it.
    effectiveSort(state) === "-updated_at"
      ? { key: "updated", header: "Updated", mobileLabel: "Updated", hideOnMobile: true, cell: (product) => <DateText value={product.updated_at} style="relative" /> }
      : {
          key: "carton",
          header: "Per carton",
          mobileLabel: "Per carton",
          numeric: true,
          hideOnMobile: true,
          cell: (product) => (product.carton_qty === null ? <span className="text-ink-3">Not set</span> : <span className="lk-tnum">{formatCount(product.carton_qty, locale)}</span>),
        },
  ];
  if (showPrices) {
    columns.push({
      key: "price",
      header: `Price, ${state.currency}`,
      mobileLabel: `Price, ${state.currency}`,
      numeric: true,
      cell: (product) => <StandardPrice column={priceColumnFor(product.prices, state.currency)} quiet />,
    });
  }
  columns.push({
    key: "status",
    header: "Status",
    cell: (product) => (product.archived ? <span className="t-body-sm text-ink-3">Archived</span> : <ProductStatusBadge status={product.status} size="sm" />),
  });
  return columns;
}

/**
 * The catalogue, and the landing screen of the Products area. A grid of what you sell by default,
 * a table when you need to compare; search, sort, price currency and every filter live in the URL.
 */
export function Catalogue({ state, layout }: { state: ProductListState; layout: CatalogueLayout }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const canCreate = permissionKeys.has(PRODUCTS_CREATE);
  const canExport = permissionKeys.has(PRODUCTS_EXPORT);
  const canSeePrices = permissionKeys.has(PRICES_READ);
  const query = useCatalogue(state, allowed);
  const facets = useCatalogueFacets(state, allowed);
  const stats = useCatalogueStats(allowed);
  useScreenContribution(
    query.data
      ? {
          lists: [{ key: "products", rows: query.data.items.map((product, index) => ({ type: "catalogue.product", id: product.id, version: null, ordinal: state.offset + index + 1 })) }],
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

  if (!allowed) {
    return (
      <Page>
        <PageHeader display title="Catalogue" />
        <NotPermitted what="The catalogue" icon="box" />
      </Page>
    );
  }

  const go = (patch: Partial<ProductListState>) => router.push(catalogueHref({ ...state, offset: 0, ...patch }, layout));
  const filtered = activeFilterCount(state) > 0;
  const sort = effectiveSort(state);
  const sortOptions = PRODUCT_SORTS.filter((option) => option !== "relevance" || state.q).map((option) => ({ value: option, label: SORT_LABEL[option] ?? option }));
  const showPrices = canSeePrices && (query.data?.items.some((product) => product.prices !== null) ?? false);
  const data = query.data;
  const limit = data?.limit || PRODUCTS_PAGE_SIZE;
  const page = data ? Math.floor(data.offset / limit) + 1 : 1;
  const pages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;

  const empty = filtered ? (
    <EmptyState
      icon="search"
      title="Nothing in the catalogue matches"
      text="Loosen the search or drop a filter to see more."
      actions={
        <ButtonLink href={catalogueHref({ sort: state.sort, currency: state.currency }, layout)} variant="secondary">
          Clear search and filters
        </ButtonLink>
      }
    />
  ) : (
    <EmptyState
      icon="box"
      title="Add your first product"
      text="A product is one design in one decor and one size. Start with its code and category; the rest can follow."
      actions={
        canCreate ? (
          <ButtonLink href="/products/new" iconLeft="plus">
            Add product
          </ButtonLink>
        ) : undefined
      }
    />
  );

  return (
    <Page>
      <PageHeader
        display
        eyebrow="Products"
        title="Catalogue"
        lead="Every design, decor and size you sell, with what it measures and what it costs."
        actions={
          canCreate || canExport ? (
            <>
              {canExport ? (
                <ButtonLink external href={productExportHref(state)} download variant="secondary" iconLeft="download">
                  Export CSV
                </ButtonLink>
              ) : null}
              {canCreate ? (
                <ButtonLink href={"/products/new-design" as Route} variant="secondary" iconLeft="layers">
                  Add a design
                </ButtonLink>
              ) : null}
              {canCreate ? (
                <ButtonLink href="/products/new" iconLeft="plus">
                  Add product
                </ButtonLink>
              ) : null}
            </>
          ) : undefined
        }
      />

      <CatalogueStats layout={layout} />
      <GapsNotice />

      <section className="stack" aria-label="Products">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <SearchField
              key={state.q}
              label="Search the catalogue"
              placeholder="Search by code, name, decor or finish"
              defaultValue={state.q}
              onSubmit={(q) => go({ q: q.trim() })}
              onChange={(value) => {
                if (value === "" && state.q) go({ q: "" });
              }}
              className="min-w-0 flex-1 basis-64"
            />
            <SegmentedLinks
              label="Layout"
              value={layout}
              options={[
                { value: "grid", label: "Grid", href: catalogueHref(state, "grid") },
                { value: "table", label: "Table", href: catalogueHref(state, "table") },
              ]}
            />
            <Select
              label="Order"
              hideLabel
              size="md"
              className="w-48"
              options={sortOptions}
              value={sort}
              onChange={(value) => go({ sort: PRODUCT_SORTS.find((option) => option === value) ?? null })}
            />
            {canSeePrices ? (
              <Select
                label="Price currency"
                hideLabel
                size="md"
                className="w-40"
                options={CURRENCIES.map((code) => ({ value: code, label: `Prices in ${code}` }))}
                value={state.currency}
                onChange={(value) => go({ currency: CURRENCIES.find((code) => code === value) ?? state.currency })}
              />
            ) : null}
          </div>
          <div className="flex min-w-0 items-center gap-3">
            <div className="min-w-0 flex-1">
              <CategoryChips state={state} layout={layout} facets={facets} />
            </div>
            <div className="flex-none">
              <FiltersButton state={state} layout={layout} facets={facets} archivedCount={stats.data?.archived ?? null} />
            </div>
          </div>
          <ActiveFilters state={state} layout={layout} facets={facets.data} />
        </div>

        {query.isError && !data ? (
          <ErrorBlock error={query.error} what="The catalogue" onRetry={() => void query.refetch()} />
        ) : layout === "table" ? (
          <GlassPanel padding="none">
            <DataTable
              label="Products"
              columns={tableColumns(state, showPrices, zone.locale)}
              rows={data?.items ?? []}
              rowKey={(product) => product.id}
              rowHref={(product) => productViewHref(product.id, "summary")}
              loading={query.isPending}
              skeletonRows={8}
              empty={empty}
            />
          </GlassPanel>
        ) : query.isPending ? (
          <GridSkeleton />
        ) : data && data.items.length > 0 ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {data.items.map((product, index) => (
              <ProductCard key={product.id} product={product} currency={state.currency} showPrices={showPrices} index={index} />
            ))}
          </div>
        ) : (
          <GlassPanel>{empty}</GlassPanel>
        )}

        {data && data.total > 0 ? (
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
            <PageSummary from={data.offset + 1} to={data.offset + data.items.length} total={data.total} noun="products" />
            {pages > 1 ? (
              <Pagination label="Catalogue pages" page={page} pages={pages} hrefFor={(target) => catalogueHref({ ...state, offset: (target - 1) * limit }, layout)} />
            ) : null}
          </div>
        ) : null}
      </section>
    </Page>
  );
}
