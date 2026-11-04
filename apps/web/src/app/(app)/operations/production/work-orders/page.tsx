import type { Metadata } from "next";
import { workOrderStateFrom } from "@/features/production/list-state";
import { WorkOrdersScreen } from "@/features/production/work-order-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-work-orders");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Work orders in the actor's scope; search, status and "blocked only" live in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <WorkOrdersScreen state={workOrderStateFrom(await searchParams)} />;
}
