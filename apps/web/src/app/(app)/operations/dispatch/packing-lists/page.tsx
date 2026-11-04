import type { Metadata } from "next";
import { packingStateFrom } from "@/features/logistics/list-state";
import { PackingListsScreen } from "@/features/logistics/packing-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-dispatch-packing-lists");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Packing lists; the status filter lives in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = packingStateFrom(await searchParams);
  return <PackingListsScreen state={state} />;
}
