import type { Metadata } from "next";
import { workOrderStateFrom } from "@/features/production/list-state";
import { WorkOrderList } from "~/screens/production/work-order-list";

export const metadata: Metadata = { title: "Work orders · Operations" };

/** Work orders in the person's scope; search, status, "waiting for material" and the page live in the URL. */
export default async function WorkOrdersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = workOrderStateFrom(await searchParams);
  return <WorkOrderList key={`${state.q}|${state.status}|${state.blocked}|${state.offset}`} state={state} />;
}
