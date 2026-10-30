import type { Metadata } from "next";
import { CustomProductList, customListStateFrom } from "@/features/custom-products/list";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-custom-products");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** Custom products: search, status and scope filters and the page offset live in the URL. */
export default async function CustomProductsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = customListStateFrom(await searchParams);
  return <CustomProductList key={`${state.q}|${state.status}|${state.scope}|${state.offset}`} state={state} />;
}
