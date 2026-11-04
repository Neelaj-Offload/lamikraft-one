import type { Metadata } from "next";
import { requisitionStateFrom } from "@/features/procurement/list-state";
import { RequisitionsScreen } from "@/features/procurement/requisition-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-purchasing-requisitions");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Purchase requisitions; the status filter lives in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = requisitionStateFrom(await searchParams);
  return <RequisitionsScreen status={state.status} />;
}
