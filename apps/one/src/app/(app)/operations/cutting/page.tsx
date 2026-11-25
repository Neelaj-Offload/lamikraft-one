import type { Metadata } from "next";
import { planListStateFrom } from "@/features/cutting/list-state";
import { PlanList } from "~/screens/cutting/plan-list";

export const metadata: Metadata = { title: "Cut plans · Operations" };

/** Saved cut plans: search, status, whose plans and the page offset live in the URL. */
export default async function CutPlansPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = planListStateFrom(await searchParams);
  return <PlanList key={`${state.q}|${state.status}|${state.scope}|${state.offset}`} state={state} />;
}
