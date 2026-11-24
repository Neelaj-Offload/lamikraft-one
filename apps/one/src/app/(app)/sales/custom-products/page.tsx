import type { Metadata } from "next";
import { customListStateFrom } from "@/features/custom-products/list-state";
import { CustomProductList } from "~/screens/sales/custom-products/custom-product-list";

export const metadata: Metadata = { title: "Custom products · Sales" };

/** Custom products: search, status, scope and the page offset live in the URL. */
export default async function CustomProductsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = customListStateFrom(await searchParams);
  return <CustomProductList key={`${state.q}|${state.status}|${state.scope}|${state.offset}`} state={state} />;
}
