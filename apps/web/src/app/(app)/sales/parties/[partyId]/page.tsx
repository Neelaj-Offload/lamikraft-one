import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PartyDetail } from "@/features/parties/party-detail";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-party");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** The customer record: header facts, contacts, addresses, tax identifiers and the customer's quotes. */
export default async function PartyPage({ params }: { params: Promise<{ partyId: string }> }) {
  const { partyId } = await params;
  if (!UUID_PATTERN.test(partyId)) notFound();
  return <PartyDetail key={partyId} partyId={partyId} />;
}
