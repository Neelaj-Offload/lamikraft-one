import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ChallanPrintView } from "@/features/challans/challan-print";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("print-challan");

export const metadata: Metadata = { title: route.label };

/** The browser print view: the same data the PDF is rendered from; the internal note is never part of it. */
export default async function ChallanPrintPage({ params }: { params: Promise<{ challanId: string }> }) {
  const { challanId } = await params;
  if (!UUID_PATTERN.test(challanId)) notFound();
  return <ChallanPrintView key={challanId} challanId={challanId} />;
}
