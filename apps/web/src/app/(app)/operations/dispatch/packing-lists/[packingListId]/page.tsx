import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PackingListScreen } from "@/features/logistics/packing-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-dispatch-packing-list");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ packingListId: string }> }) {
  const { packingListId } = await params;
  if (!UUID_PATTERN.test(packingListId)) notFound();
  return <PackingListScreen key={packingListId} packingListId={packingListId} />;
}
