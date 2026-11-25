import type { Metadata } from "next";
import { challanListKey, challanListStateFrom } from "@/features/challans/list-state";
import { ChallanList } from "~/screens/challans/challan-list";

export const metadata: Metadata = { title: "Challans · Operations" };

/** Delivery challans: search, status, type, destination, period, still-out, scope and the page offset live in the URL. */
export default async function ChallansPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = challanListStateFrom(await searchParams);
  return <ChallanList key={challanListKey(state)} state={state} />;
}
