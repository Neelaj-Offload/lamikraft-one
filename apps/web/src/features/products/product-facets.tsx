"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { FacetGroup, type FacetOption } from "@/components/ui/facet-group";
import { ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { productsMessages as m } from "@/messages/products";
import { fetchProductFacets } from "./api";
import { activeFilterCount, facetClearHref, facetToggleHref, isFacetSelected, productFilterParams, FACET_FILTER_KEY, type ProductListState } from "./list-state";
import { FACET_DIMENSIONS, type FacetDimension, type ProductFacets } from "./types";

/** Facet options for one dimension; the selected value stays listed (count 0) even when the server omitted it. */
export function facetOptions(state: ProductListState, facets: ProductFacets, dimension: FacetDimension): FacetOption[] {
  const options = facets[dimension].map((value) => ({
    value: value.value,
    label: dimension === "statuses" ? (m.status[value.value] ?? value.label) : value.label,
    count: value.count,
    href: facetToggleHref(state, dimension, value.value),
    selected: isFacetSelected(state, dimension, value.value),
  }));
  const current = state[FACET_FILTER_KEY[dimension]];
  if (typeof current === "string" && current && !options.some((option) => option.selected)) {
    options.unshift({
      value: current,
      label: dimension === "statuses" ? (m.status[current] ?? current) : current,
      count: 0,
      href: facetToggleHref(state, dimension, current),
      selected: true,
    });
  }
  return options;
}

export function useProductFacets(state: ProductListState) {
  return useQuery({
    queryKey: queryKeys.catalogue.facets(productFilterParams(state)),
    queryFn: ({ signal }) => fetchProductFacets(state, signal),
  });
}

/** Every facet dimension as URL-driven link groups (the lg+ side column and the phone drawer body). */
export function FacetColumn({ state, facets }: { state: ProductListState; facets: ReturnType<typeof useProductFacets> }) {
  if (facets.isPending) return <Loading label={m.list.filters.toLowerCase()} variant="inline" />;
  if (facets.isError) return <ErrorState error={facets.error} what={m.list.filters.toLowerCase()} onRetry={() => void facets.refetch()} backToToday={false} compact headingLevel={3} />;
  return (
    <div className="flex flex-col gap-5">
      {FACET_DIMENSIONS.map((dimension) => (
        <FacetGroup
          key={dimension}
          label={m.list.facets[dimension]}
          options={facetOptions(state, facets.data, dimension)}
          clearHref={facetClearHref(state, dimension)}
          max={dimension === "decors" || dimension === "sizes" ? 12 : 8}
        />
      ))}
    </div>
  );
}

/** Below lg the facets live in a drawer behind a "Filters (n)" button. */
export function FiltersDrawerButton({ state, facets }: { state: ProductListState; facets: ReturnType<typeof useProductFacets> }) {
  const [open, setOpen] = useState(false);
  const count = activeFilterCount(state);
  return (
    <>
      <Button onPress={() => setOpen(true)} className="lg:hidden">
        {count > 0 ? m.list.filtersWithCount(count) : m.list.filters}
      </Button>
      <Drawer isOpen={open} onOpenChange={setOpen} title={m.list.filtersTitle} description={m.list.filtersDescription}>
        <FacetColumn state={state} facets={facets} />
      </Drawer>
    </>
  );
}
