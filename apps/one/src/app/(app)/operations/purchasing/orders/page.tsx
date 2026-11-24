import type { Metadata } from "next";
import { poStateFrom } from "@/features/procurement/list-state";
import { PurchaseOrderList } from "~/screens/purchasing/po-list";

export const metadata: Metadata = { title: "Purchase orders · Operations" };

/** Purchase orders: search, status, "overdue only" and the page offset live in the URL. */
export default async function PurchaseOrdersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = poStateFrom(await searchParams);
  return <PurchaseOrderList key={state.q} state={state} />;
}
