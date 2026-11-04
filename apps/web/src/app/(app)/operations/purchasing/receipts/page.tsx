import type { Metadata } from "next";
import { receiptStateFrom } from "@/features/procurement/list-state";
import { ReceiptsScreen } from "@/features/procurement/receipt-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-purchasing-receipts");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Goods receipts; "only waiting for QC" lives in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = receiptStateFrom(await searchParams);
  return <ReceiptsScreen awaitingQc={state.awaitingQc} />;
}
