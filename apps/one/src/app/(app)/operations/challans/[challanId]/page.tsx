import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ChallanRecord } from "~/screens/challans/challan-record";
import { challanViewFrom } from "~/screens/challans/views";

export const metadata: Metadata = { title: "Challan · Operations" };

/** A challan: overview, lines, details, returns, activity and the internal note (`?view=`). */
export default async function ChallanPage({
  params,
  searchParams,
}: {
  params: Promise<{ challanId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { challanId } = await params;
  if (!UUID_PATTERN.test(challanId)) notFound();
  const view = challanViewFrom((await searchParams).view);
  return <ChallanRecord key={challanId} challanId={challanId} view={view} />;
}
