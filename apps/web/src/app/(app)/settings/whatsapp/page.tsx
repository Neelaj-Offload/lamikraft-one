import type { Metadata } from "next";
import { WhatsAppView } from "@/features/channels/whatsapp-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("settings-whatsapp");

export const metadata: Metadata = { title: `${route.label} · Settings` };

export default function SettingsWhatsAppPage() {
  return <WhatsAppView />;
}
