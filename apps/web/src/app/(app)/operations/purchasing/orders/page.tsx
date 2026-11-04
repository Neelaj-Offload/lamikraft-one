import type { Metadata } from "next";
import { poStateFrom } from "@/features/procurement/list-state";
import { PurchaseOrdersScreen } from "@/features/procurement/po-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-purchasing-orders");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Purchase orders: search, status and "only overdue" live in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = poStateFrom(await searchParams);
  return <PurchaseOrdersScreen state={state} />;
}
