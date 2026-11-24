import type { Metadata } from "next";
import { searchPageStateFrom } from "@/features/search/page-state";
import { SearchScreen } from "~/screens/search/search-screen";

export const metadata: Metadata = { title: "Search" };

/** The query, one result type and the page offset live in the URL. */
export default async function SearchPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = searchPageStateFrom(await searchParams);
  return <SearchScreen state={state} />;
}
