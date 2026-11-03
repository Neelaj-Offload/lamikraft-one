import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ChallanWorkspace } from "@/features/challans/challan-workspace";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-challan");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** The challan workspace: details, lines with autosave, allowed transitions, returns, history and the internal note. */
export default async function ChallanPage({ params }: { params: Promise<{ challanId: string }> }) {
  const { challanId } = await params;
  if (!UUID_PATTERN.test(challanId)) notFound();
  return <ChallanWorkspace key={challanId} challanId={challanId} />;
}
