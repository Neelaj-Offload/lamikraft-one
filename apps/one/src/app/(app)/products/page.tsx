import type { Metadata } from "next";
import { productListStateFrom } from "@/features/products/list-state";
import { Catalogue } from "~/screens/products/catalogue";
import { catalogueLayoutFrom } from "~/screens/products/links";

export const metadata: Metadata = { title: "Catalogue" };

/** The catalogue: search, filters, sort, price currency, layout and page all live in the URL. */
export default async function ProductsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const search = await searchParams;
  return <Catalogue state={productListStateFrom(search)} layout={catalogueLayoutFrom(search.view)} />;
}
