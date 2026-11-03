import type { Metadata } from "next";
import { lookupStateFrom } from "@/features/catalogue/lookup-state";
import { LookupBrowser } from "@/features/catalogue/lookups";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-lookups");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default async function LookupsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = lookupStateFrom(await searchParams);
  return <LookupBrowser key={JSON.stringify(state)} state={state} />;
}
