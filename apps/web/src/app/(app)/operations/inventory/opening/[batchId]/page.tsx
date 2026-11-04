import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocumentScreen } from "@/features/inventory/document-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory-opening");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ batchId: string }> }) {
  const { batchId } = await params;
  if (!UUID_PATTERN.test(batchId)) notFound();
  return <DocumentScreen key={batchId} kind="opening_batch" id={batchId} />;
}
