import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocumentScreen } from "@/features/inventory/document-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory-adjustment");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ adjustmentId: string }> }) {
  const { adjustmentId } = await params;
  if (!UUID_PATTERN.test(adjustmentId)) notFound();
  return <DocumentScreen key={adjustmentId} kind="adjustment" id={adjustmentId} />;
}
