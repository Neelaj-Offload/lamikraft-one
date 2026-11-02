import type { Metadata } from "next";
import { ProductListPage, type ProductsSearchParams } from "@/features/products/product-list-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("products");

export const metadata: Metadata = { title: route.label };

/** The catalogue: search, facets, sort, price currency and the page offset all live in the URL. */
export default function ProductsPage({ searchParams }: { searchParams: ProductsSearchParams }) {
  return <ProductListPage searchParams={searchParams} />;
}
