import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { RequisitionRecord } from "~/screens/purchasing/requisition-record";
import { requisitionViewFrom } from "~/screens/purchasing/views";

export const metadata: Metadata = { title: "Requisition · Operations" };

/** A requisition: overview and lines (`?view=`). */
export default async function RequisitionPage({
  params,
  searchParams,
}: {
  params: Promise<{ requisitionId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { requisitionId } = await params;
  if (!UUID_PATTERN.test(requisitionId)) notFound();
  const view = requisitionViewFrom((await searchParams).view);
  return <RequisitionRecord key={requisitionId} requisitionId={requisitionId} view={view} />;
}
