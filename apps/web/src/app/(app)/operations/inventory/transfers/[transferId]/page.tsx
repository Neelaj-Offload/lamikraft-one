import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocumentScreen } from "@/features/inventory/document-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory-transfer");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ transferId: string }> }) {
  const { transferId } = await params;
  if (!UUID_PATTERN.test(transferId)) notFound();
  return <DocumentScreen key={transferId} kind="transfer" id={transferId} />;
}
