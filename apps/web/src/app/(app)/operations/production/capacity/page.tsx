import type { Metadata } from "next";
import { capacityStateFrom } from "@/features/production/list-state";
import { CapacityScreen } from "@/features/production/master-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-capacity");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Load per work centre per day against calendar capacity; the window (from, to) lives in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <CapacityScreen state={capacityStateFrom(await searchParams)} />;
}
