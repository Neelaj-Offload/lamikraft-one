import type { Metadata } from "next";
import { SearchPage, searchPageStateFrom } from "@/features/search/search-page";

export const metadata: Metadata = { title: "Search" };

/** "See all results": the query, one type and the page offset live in the URL. */
export default async function SearchRoute({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = searchPageStateFrom(await searchParams);
  return <SearchPage key={`${state.q}|${state.type}|${state.offset}`} state={state} />;
}
