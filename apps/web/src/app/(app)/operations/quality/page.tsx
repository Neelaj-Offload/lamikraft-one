import type { Metadata } from "next";
import { inspectionStateFrom } from "@/features/quality/list-state";
import { InspectionsScreen } from "@/features/quality/inspection-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-quality");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Quality inspections, waiting ones first; the status filter lives in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = inspectionStateFrom(await searchParams);
  return <InspectionsScreen state={state} />;
}
