import type { Metadata } from "next";
import { capacityStateFrom } from "@/features/production/list-state";
import { Capacity } from "~/screens/production/capacity";

export const metadata: Metadata = { title: "Capacity · Operations" };

/** Load per work centre per day against calendar capacity; the window (`from`, `to`) lives in the URL. */
export default async function CapacityPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <Capacity state={capacityStateFrom(await searchParams)} />;
}
