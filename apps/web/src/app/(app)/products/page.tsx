import type { Metadata } from "next";
import { productListStateFrom } from "@/features/catalogue/list-state";
import { ProductCatalogue } from "@/features/catalogue/product-list";
import { getRoute } from "@/lib/routes";

const route = getRoute("products");

export const metadata: Metadata = { title: route.label };

/** Products: summary figures, category chips and the catalogue list; every filter lives in the URL. */
export default async function ProductsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = productListStateFrom(await searchParams);
  return <ProductCatalogue key={JSON.stringify(state)} state={state} />;
}
