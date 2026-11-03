import type { Metadata } from "next";
import { planListStateFrom } from "@/features/cutting/list-state";
import { PlanList } from "@/features/cutting/plan-list";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-cutting");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Saved cut plans: search, status, scope and the page offset all live in the URL. */
export default async function CutPlansPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = planListStateFrom(await searchParams);
  return <PlanList key={`${state.q}|${state.status}|${state.scope}|${state.offset}`} state={state} />;
}
