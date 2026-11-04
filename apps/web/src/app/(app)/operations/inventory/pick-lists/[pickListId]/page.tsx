import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PickListScreen } from "@/features/inventory/document-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory-pick-list");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ pickListId: string }> }) {
  const { pickListId } = await params;
  if (!UUID_PATTERN.test(pickListId)) notFound();
  return <PickListScreen key={pickListId} pickListId={pickListId} />;
}
