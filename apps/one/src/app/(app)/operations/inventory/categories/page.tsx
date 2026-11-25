import type { Metadata } from "next";
import { StockByCategory } from "~/screens/stock/categories";
import { categoryHref, categoryStateFrom } from "~/screens/stock/category-state";

export const metadata: Metadata = { title: "Stock by category" };

export default async function StockCategoriesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = categoryStateFrom(await searchParams);
  return <StockByCategory key={categoryHref(state)} state={state} />;
}
