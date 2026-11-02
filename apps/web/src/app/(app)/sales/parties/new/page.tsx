import type { Metadata } from "next";
import { PartyCreate } from "@/features/parties/party-create";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-party-new");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** New customer; the form needs `parties.party.create` (otherwise it explains the missing access). */
export default function NewPartyPage() {
  return <PartyCreate />;
}
