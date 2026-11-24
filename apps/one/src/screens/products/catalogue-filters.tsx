"use client";

import type { Route } from "next";
import { useState } from "react";
import {
  activeFilterCount,
  clearedFiltersHref,
  FACET_FILTER_KEY,
  facetClearHref,
  facetToggleHref,
  isFacetSelected,
  productListHref,
  type ProductListState,
} from "@/features/products/list-state";
import { FACET_DIMENSIONS, type FacetDimension, type FacetValue, type ProductFacets } from "@/features/products/types";
import { formatCount } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { ErrorBlock } from "~/shell/states";
import { Button, ButtonLink, ChipGroup, ChipLink, Drawer, SkeletonText, TextLink } from "~/ui";
import { PRODUCT_STATUS_LABEL } from "./format";
import type { CatalogueLayout } from "./links";

/** The catalogue's filters: categories as a chip row, everything else in a drawer, all of it in the URL. */

const DIMENSION_LABEL: Record<FacetDimension, string> = {
  categories: "Category",
  subcategories: "Subcategory",
  families: "Family",
  sizes: "Size",
  thicknesses: "Thickness",
  decors: "Decor",
  finishes: "Finish",
  statuses: "Status",
  brands: "Brand",
};

/** What a completeness gap is called when it filters the catalogue. */
export const ISSUE_LABEL: Record<string, string> = {
  no_decor: "No decor",
  no_specification: "No specification",
  no_thickness: "No thickness",
  no_size: "No size",
  unparsed_dimensions: "Size not understood",
  no_packaging: "No packaging",
  no_carton_qty: "No carton quantity",
  no_unit_weight: "No unit weight",
  category_inactive: "Category switched off",
  no_hsn_sac: "No HSN or SAC code",
  shared_display_sku: "SKU shared with another product",
};

const DRAWER_DIMENSIONS = FACET_DIMENSIONS.filter((dimension) => dimension !== "categories");
const COLLAPSED = 14;

type FacetsQuery = { data: ProductFacets | undefined; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown };

function layoutHref(href: string, layout: CatalogueLayout): Route {
  if (layout === "grid") return href as Route;
  return `${href}${href.includes("?") ? "&" : "?"}view=table` as Route;
}

function valueLabel(dimension: FacetDimension, value: FacetValue): string {
  return dimension === "statuses" ? (PRODUCT_STATUS_LABEL[value.value] ?? value.label) : value.label;
}

/** The selected value stays listed (count 0) even when the server left it out. */
function optionsFor(state: ProductListState, facets: ProductFacets, dimension: FacetDimension): FacetValue[] {
  const values = [...facets[dimension]];
  const current = state[FACET_FILTER_KEY[dimension]];
  if (typeof current === "string" && current && !values.some((value) => isFacetSelected(state, dimension, value.value))) {
    values.unshift({ value: current, label: current, count: 0 });
  }
  return values;
}

/** Categories as one row of chips, the way a printed catalogue is thumbed through. */
export function CategoryChips({ state, layout, facets }: { state: ProductListState; layout: CatalogueLayout; facets: FacetsQuery }) {
  if (!facets.data) return null;
  const categories = optionsFor(state, facets.data, "categories");
  if (categories.length === 0) return null;
  return (
    <ChipGroup label="Filter by category">
      <ChipLink href={layoutHref(facetClearHref(state, "categories"), layout)} selected={!state.category_id} scroll={false}>
        All categories
      </ChipLink>
      {categories.map((category) => (
        <ChipLink
          key={category.value}
          href={layoutHref(facetToggleHref(state, "categories", category.value), layout)}
          selected={isFacetSelected(state, "categories", category.value)}
          count={category.count}
          scroll={false}
        >
          {category.label}
        </ChipLink>
      ))}
    </ChipGroup>
  );
}

function FacetSection({
  dimension,
  state,
  layout,
  facets,
}: {
  dimension: FacetDimension;
  state: ProductListState;
  layout: CatalogueLayout;
  facets: ProductFacets;
}) {
  const [expanded, setExpanded] = useState(false);
  const values = optionsFor(state, facets, dimension);
  if (values.length === 0) return null;
  const shown = expanded ? values : values.slice(0, COLLAPSED);
  return (
    <section className="flex flex-col gap-3">
      <h3 className="t-label text-ink-2">{DIMENSION_LABEL[dimension]}</h3>
      <ChipGroup label={`Filter by ${DIMENSION_LABEL[dimension].toLowerCase()}`} className="flex-wrap!">
        {shown.map((value) => (
          <ChipLink
            key={value.value}
            href={layoutHref(facetToggleHref(state, dimension, value.value), layout)}
            selected={isFacetSelected(state, dimension, value.value)}
            count={value.count}
            scroll={false}
          >
            {valueLabel(dimension, value)}
          </ChipLink>
        ))}
      </ChipGroup>
      {values.length > COLLAPSED ? (
        <div>
          <Button variant="ghost" size="sm" onPress={() => setExpanded((open) => !open)}>
            {expanded ? "Show fewer" : `Show all ${values.length}`}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

/** Every filter beyond category, in a drawer. Each chip is a link, so the list behind updates as you pick. */
export function FiltersButton({
  state,
  layout,
  facets,
  archivedCount,
}: {
  state: ProductListState;
  layout: CatalogueLayout;
  facets: FacetsQuery;
  archivedCount: number | null;
}) {
  const [open, setOpen] = useState(false);
  const count = activeFilterCount(state) - (state.q ? 1 : 0) - (state.category_id ? 1 : 0);
  const total = facets.data?.total;
  const { locale } = useZone();
  return (
    <>
      <Button variant="secondary" size="sm" iconLeft="sliders" onPress={() => setOpen(true)}>
        {count > 0 ? `Filters · ${count}` : "Filters"}
      </Button>
      <Drawer
        isOpen={open}
        onOpenChange={setOpen}
        title="Filter the catalogue"
        description="Pick as many as you need. The numbers show what each one leaves."
        footer={
          <>
            <ButtonLink variant="ghost" href={layoutHref(clearedFiltersHref(state), layout)}>
              Clear all
            </ButtonLink>
            <Button variant="inverse" onPress={() => setOpen(false)}>
              {total === undefined ? "Show products" : `Show ${formatCount(total, locale)} ${total === 1 ? "product" : "products"}`}
            </Button>
          </>
        }
      >
        {facets.isPending ? (
          <SkeletonText lines={8} />
        ) : facets.isError || !facets.data ? (
          <ErrorBlock error={facets.error} what="Filters" onRetry={() => void facets.refetch()} />
        ) : (
          <div className="flex flex-col gap-6">
            {DRAWER_DIMENSIONS.map((dimension) => (
              <FacetSection key={dimension} dimension={dimension} state={state} layout={layout} facets={facets.data!} />
            ))}
            <section className="flex flex-col gap-3">
              <h3 className="t-label text-ink-2">Archive</h3>
              <ChipGroup label="Archived products" className="flex-wrap!">
                <ChipLink
                  href={layoutHref(productListHref({ ...state, include_archived: !state.include_archived, offset: 0 }), layout)}
                  selected={state.include_archived}
                  count={archivedCount ?? undefined}
                  icon="archive"
                  scroll={false}
                >
                  Include archived
                </ChipLink>
              </ChipGroup>
            </section>
          </div>
        )}
      </Drawer>
    </>
  );
}

/** What is narrowing the list right now; each chip removes its own filter. */
export function ActiveFilters({ state, layout, facets }: { state: ProductListState; layout: CatalogueLayout; facets: ProductFacets | undefined }) {
  const chips: { key: string; label: string; href: Route }[] = [];
  if (state.q) chips.push({ key: "q", label: `“${state.q}”`, href: layoutHref(productListHref({ ...state, q: "", offset: 0 }), layout) });
  for (const dimension of FACET_DIMENSIONS) {
    const current = state[FACET_FILTER_KEY[dimension]];
    if (typeof current !== "string" || !current) continue;
    const match = facets?.[dimension].find((value) => isFacetSelected(state, dimension, value.value));
    const text = match ? valueLabel(dimension, match) : dimension === "statuses" ? (PRODUCT_STATUS_LABEL[current] ?? current) : null;
    // A category or subcategory is an id in the URL: wait for its name rather than show the id.
    if (!text && (dimension === "categories" || dimension === "subcategories")) continue;
    chips.push({ key: dimension, label: `${DIMENSION_LABEL[dimension]}: ${text ?? current}`, href: layoutHref(facetClearHref(state, dimension), layout) });
  }
  if (state.issue) {
    chips.push({ key: "issue", label: `Gap: ${ISSUE_LABEL[state.issue] ?? state.issue}`, href: layoutHref(productListHref({ ...state, issue: null, offset: 0 }), layout) });
  }
  if (state.include_archived) {
    chips.push({ key: "archived", label: "Including archived", href: layoutHref(productListHref({ ...state, include_archived: false, offset: 0 }), layout) });
  }
  if (chips.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
      <ChipGroup label="Filters in use">
        {chips.map((chip) => (
          <ChipLink key={chip.key} href={chip.href} selected icon="x" aria-label={`Remove filter ${chip.label}`} scroll={false}>
            {chip.label}
          </ChipLink>
        ))}
      </ChipGroup>
      {chips.length > 1 ? (
        <TextLink href={layoutHref(clearedFiltersHref(state), layout)} className="t-body-sm">
          Clear all
        </TextLink>
      ) : null}
    </div>
  );
}
