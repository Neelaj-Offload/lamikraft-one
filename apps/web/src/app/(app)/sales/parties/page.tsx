import type { Metadata } from "next";
import { partyListStateFrom } from "@/features/parties/api";
import { PartyList } from "@/features/parties/parties";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-parties");

export const metadata: Metadata = { title: `${route.label} · Sales` };

export default async function PartiesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = partyListStateFrom(await searchParams);
  return <PartyList key={JSON.stringify(state)} state={state} />;
}
