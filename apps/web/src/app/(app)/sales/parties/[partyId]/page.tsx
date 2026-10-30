import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PartyDetailView } from "@/features/parties/parties";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-party");

export const metadata: Metadata = { title: `${route.label} · Sales` };

export default async function PartyPage({ params }: { params: Promise<{ partyId: string }> }) {
  const { partyId } = await params;
  if (!UUID_PATTERN.test(partyId)) notFound();
  return <PartyDetailView key={partyId} partyId={partyId} />;
}
