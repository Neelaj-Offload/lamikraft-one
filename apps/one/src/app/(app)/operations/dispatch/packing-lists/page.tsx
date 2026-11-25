import type { Metadata } from "next";
import { packingStateFrom } from "@/features/logistics/list-state";
import { PackingListList } from "~/screens/dispatch/packing-list-list";

export const metadata: Metadata = { title: "Packing lists · Operations" };

/** Packing lists; the status filter and the page offset live in the URL. */
export default async function PackingListsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = packingStateFrom(await searchParams);
  return <PackingListList key={`${state.status}|${state.offset}`} state={state} />;
}
