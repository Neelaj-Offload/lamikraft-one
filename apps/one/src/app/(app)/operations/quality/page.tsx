import type { Metadata } from "next";
import { inspectionStateFrom } from "@/features/quality/list-state";
import { InspectionList } from "~/screens/quality/inspection-list";

export const metadata: Metadata = { title: "Quality · Operations" };

/** Quality inspections, waiting ones first: the status filter and the page offset live in the URL. */
export default async function QualityPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = inspectionStateFrom(await searchParams);
  return <InspectionList state={state} />;
}
