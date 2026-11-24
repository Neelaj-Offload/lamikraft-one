import type { Metadata } from "next";
import { requisitionStateFrom } from "@/features/procurement/list-state";
import { RequisitionList } from "~/screens/purchasing/requisition-list";

export const metadata: Metadata = { title: "Requisitions · Operations" };

/** Requisitions: the status filter and the page offset live in the URL. */
export default async function RequisitionsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = requisitionStateFrom(await searchParams);
  return <RequisitionList state={state} />;
}
