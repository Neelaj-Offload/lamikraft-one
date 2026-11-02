import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/api/query-keys";
import { serverGetJson } from "@/lib/session/server";
import { productListQueryString, PRODUCTS_PATH } from "./api";
import { productListHref, productListParams, productListStateFrom } from "./list-state";
import { pageOf, parseProductSummary } from "./parse";
import { ProductList } from "./product-list";

export type ProductsSearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Server part of /products: prefetches the first list page with the browser's cookies so rows
 * are in the HTML; the same query key hydrates the client. A failed or unreadable response
 * prefetches nothing, and the client fetches again and reports it. Facets and stats load on
 * the client. The list is keyed by its URL so a new filter remounts it (and closes the drawer).
 */
export async function ProductListPage({ searchParams }: { searchParams: ProductsSearchParams }) {
  const state = productListStateFrom(await searchParams);
  const queryClient = new QueryClient();
  const raw = await serverGetJson(`${PRODUCTS_PATH}?${productListQueryString(state)}`);
  if (raw !== null) {
    try {
      queryClient.setQueryData(queryKeys.catalogue.products(productListParams(state)), pageOf(raw, parseProductSummary));
    } catch {
      // Unreadable: the client fetches again and reports it.
    }
  }
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <ProductList key={productListHref(state)} state={state} />
    </HydrationBoundary>
  );
}
