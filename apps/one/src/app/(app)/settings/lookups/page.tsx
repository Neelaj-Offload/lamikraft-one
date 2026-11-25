import type { Metadata } from "next";
import { lookupStateFrom } from "@/features/catalogue/lookup-state";
import { Lookups } from "~/screens/settings-data/lookups";

export const metadata: Metadata = { title: "Lookup reference · Settings" };

/** The legacy lookup tables: type, search and page live in the URL. */
export default async function LookupsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = lookupStateFrom(await searchParams);
  return <Lookups key={JSON.stringify(state)} state={state} />;
}
